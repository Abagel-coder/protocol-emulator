`default_nettype none
// Mode-0 SPI slave register port. Commands: see docs (WRITE_IMEM 1, WRITE_CTRL 2, READ_STATUS 3,
// PUSH_FIFO 4, POP_FIFO 5, READ_GPIO 6, WRITE_PRESCALE 7). SCK <= clk/16.
// CS_n timing: CS_n must stay asserted through the SPI clock edge that samples the last bit of
// a byte (inherent to the protocol -- that edge is what makes the byte "received"). It may be
// raised immediately afterward, even on the very next core clock cycle, with no additional
// minimum hold time: byte-completion processing (command dispatch, IMEM/CTRL/PRESCALE/PUSH
// register writes) is not gated by cs_act, so it still runs on the cycle after the 8th SCK
// rising edge even if cs_act has already dropped by then.
module pe_host_spi (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        sck,
    input  wire        mosi,
    input  wire        cs_n,
    output wire        miso,
    output reg         imem_wr,
    output reg  [9:0]  imem_waddr,
    output reg  [15:0] imem_wdata,
    output reg         ctrl_run,
    output reg         core_reset,
    output reg  [7:0]  prescale,
    input  wire        halted,
    input  wire        running,
    input  wire [9:0]  pc,
    input  wire [2:0]  flags,
    input  wire [7:0]  ui_in,
    input  wire [7:0]  uio_in,
    input  wire [6:0]  uo_out,
    input  wire [7:0]  uio_out,
    input  wire [7:0]  uio_oe,
    output reg         h2c_push,
    output reg  [15:0] h2c_wdata,
    input  wire        h2c_valid,
    input  wire        h2c_full,
    output reg         c2h_pop,
    input  wire [15:0] c2h_rdata,
    input  wire        c2h_valid
);
  localparam [7:0] C_IMEM = 8'd1, C_CTRL = 8'd2, C_STAT = 8'd3, C_PUSH = 8'd4, C_POP = 8'd5, C_GPIO = 8'd6, C_PRE = 8'd7;
  // synchronisers
  reg [2:0] sck_s, mosi_s, cs_s;
  always @(posedge clk) begin
    if (!rst_n) begin sck_s <= 3'd0; mosi_s <= 3'd0; cs_s <= 3'b111; end
    else begin sck_s <= {sck_s[1:0], sck}; mosi_s <= {mosi_s[1:0], mosi}; cs_s <= {cs_s[1:0], cs_n}; end
  end
  wire sck_rise = sck_s[1] && !sck_s[2];
  wire sck_fall = !sck_s[1] && sck_s[2];
  wire cs_act   = !cs_s[1];
  wire cs_start = !cs_s[1] && cs_s[2];
  reg [7:0] rx_sh, tx_sh, rx_byte, cmd, hi_byte; reg [2:0] bitcnt; reg [7:0] bidx; reg byte_done;
  reg [15:0] pop_word;
  // pair_phase tracks hi/lo byte selection for WRITE_IMEM data words independent of bidx:
  // bidx saturates at 0xFF for the response mux (fine there -- no read command needs more than
  // ~5 bytes), but a WRITE_IMEM transaction can carry far more than 255 payload bytes, and once
  // bidx sticks at 0xFF (odd) its parity can no longer track hi/lo. pair_phase toggles once per
  // WRITE_IMEM data byte and never saturates, so it keeps pairing correct no matter how long the
  // transaction runs.
  reg pair_phase;
  assign miso = tx_sh[7];
  // response byte k (k = bidx-1) for read commands
  reg [7:0] resp;
  always @* begin
    resp = 8'd0;
    case (cmd)
      C_STAT: case (bidx) 8'd1: resp = {3'd0, h2c_full, !c2h_valid, h2c_valid, running, halted}; 8'd2: resp = {6'd0, pc[9:8]}; 8'd3: resp = pc[7:0]; 8'd4: resp = {5'd0, flags}; default: resp = 8'd0; endcase
      C_POP:  case (bidx) 8'd1: resp = pop_word[15:8]; 8'd2: resp = pop_word[7:0]; default: resp = 8'd0; endcase
      C_GPIO: case (bidx) 8'd1: resp = ui_in; 8'd2: resp = uio_in; 8'd3: resp = {1'b0, uo_out}; 8'd4: resp = uio_out; 8'd5: resp = uio_oe; default: resp = 8'd0; endcase
      default: resp = 8'd0;
    endcase
  end
  always @(posedge clk) begin
    if (!rst_n) begin
      rx_sh <= 8'd0; tx_sh <= 8'd0; rx_byte <= 8'd0; cmd <= 8'd0; hi_byte <= 8'd0; bitcnt <= 3'd0; bidx <= 8'd0; byte_done <= 1'b0;
      imem_wr <= 1'b0; imem_waddr <= 10'd0; imem_wdata <= 16'd0; ctrl_run <= 1'b0; core_reset <= 1'b0; prescale <= 8'd0;
      h2c_push <= 1'b0; h2c_wdata <= 16'd0; c2h_pop <= 1'b0; pop_word <= 16'd0; pair_phase <= 1'b0;
    end else begin
      imem_wr <= 1'b0; core_reset <= 1'b0; h2c_push <= 1'b0; c2h_pop <= 1'b0; byte_done <= 1'b0;
      if (!cs_act) begin
        bitcnt <= 3'd0; bidx <= 8'd0; tx_sh <= 8'd0;
      end else begin
        if (sck_rise) begin
          rx_sh <= {rx_sh[6:0], mosi_s[1]};
          bitcnt <= bitcnt + 3'd1;
          if (bitcnt == 3'd7) begin rx_byte <= {rx_sh[6:0], mosi_s[1]}; byte_done <= 1'b1; end
        end
        if (sck_fall) tx_sh <= (bitcnt == 3'd0) ? resp : {tx_sh[6:0], 1'b0};
        if (imem_wr) imem_waddr <= imem_waddr + 10'd1;
      end
      // byte_done processing is deliberately NOT gated by cs_act: cs_act is itself a
      // synchronised (2-cycle-delayed) view of cs_n, and byte_done is a one-cycle pulse
      // that fires one cycle after the 8th sck_rise. If the host drops CS_n within a
      // couple of clocks of that last rising edge, cs_act can already read 0 on the very
      // cycle byte_done needs processing. Nesting this under "else !cs_act" would silently
      // drop the last byte's effect (e.g. a WRITE_CTRL run bit never taking effect). Reading
      // bidx/cmd here naturally uses their pre-edge (not-yet-reset) values because these are
      // ordinary register reads; only the register WRITES below are non-blocking, so the
      // `!cs_act` branch above (bidx <= 0 for the next transaction) and this bidx increment
      // both target the same cycle's edge safely: at worst bidx is one cycle "late" to reset
      // when both fire together, and cs_act's own reset branch clears it again the very next
      // idle cycle, well before a new transaction's cs_start could occur.
      if (byte_done) begin
        if (bidx != 8'hFF) bidx <= bidx + 8'd1;
        if (bidx == 8'd0) begin
          cmd <= rx_byte;
          if (rx_byte == C_POP) begin pop_word <= c2h_valid ? c2h_rdata : 16'd0; c2h_pop <= c2h_valid; end
        end else begin
          case (cmd)
            C_IMEM: begin
              if (bidx == 8'd1) imem_waddr[9:8] <= rx_byte[1:0];
              else if (bidx == 8'd2) begin imem_waddr[7:0] <= rx_byte; pair_phase <= 1'b0; end  // next data byte starts a new word, high byte first
              else begin
                pair_phase <= !pair_phase;
                if (!pair_phase) hi_byte <= rx_byte;                      // phase 0 = high byte
                else begin imem_wdata <= {hi_byte, rx_byte}; imem_wr <= 1'b1; end  // phase 1 = low byte, completes the word
              end
            end
            C_CTRL: if (bidx == 8'd1) begin ctrl_run <= rx_byte[0]; core_reset <= rx_byte[1]; end
            C_PRE:  if (bidx == 8'd1) prescale <= rx_byte;
            C_PUSH: begin if (bidx == 8'd1) hi_byte <= rx_byte; else if (bidx == 8'd2) begin h2c_wdata <= {hi_byte, rx_byte}; h2c_push <= !h2c_full; end end
            default: ;
          endcase
        end
      end
    end
  end
  // mosi_s[2] and rx_sh[7] exist only to keep the synchroniser/shift-register shapes uniform;
  // the design only ever reads mosi_s[1] (the settled sample) and rx_sh[6:0] (the low 7 bits
  // shifted in before the 8th bit completes rx_byte).
  wire _unused = &{cs_start, mosi_s[2], rx_sh[7], 1'b0};
endmodule
