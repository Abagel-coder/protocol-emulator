`default_nettype none
// Mode-0 SPI slave register port. Commands: see docs (WRITE_IMEM 1, WRITE_CTRL 2, READ_STATUS 3,
// PUSH_FIFO 4, POP_FIFO 5, READ_GPIO 6, WRITE_PRESCALE 7). SCK <= clk/16.
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
  assign miso = tx_sh[7];
  // response byte k (k = bidx-1) for read commands
  reg [7:0] resp;
  always @* begin
    resp = 8'd0;
    case (cmd)
      C_STAT: case (bidx) 8'd1: resp = {4'd0, !c2h_valid, h2c_valid, running, halted}; 8'd2: resp = {6'd0, pc[9:8]}; 8'd3: resp = pc[7:0]; 8'd4: resp = {5'd0, flags}; default: resp = 8'd0; endcase
      C_POP:  case (bidx) 8'd1: resp = pop_word[15:8]; 8'd2: resp = pop_word[7:0]; default: resp = 8'd0; endcase
      C_GPIO: case (bidx) 8'd1: resp = ui_in; 8'd2: resp = uio_in; 8'd3: resp = {1'b0, uo_out}; 8'd4: resp = uio_out; 8'd5: resp = uio_oe; default: resp = 8'd0; endcase
      default: resp = 8'd0;
    endcase
  end
  always @(posedge clk) begin
    if (!rst_n) begin
      rx_sh <= 8'd0; tx_sh <= 8'd0; rx_byte <= 8'd0; cmd <= 8'd0; hi_byte <= 8'd0; bitcnt <= 3'd0; bidx <= 8'd0; byte_done <= 1'b0;
      imem_wr <= 1'b0; imem_waddr <= 10'd0; imem_wdata <= 16'd0; ctrl_run <= 1'b0; core_reset <= 1'b0; prescale <= 8'd0;
      h2c_push <= 1'b0; h2c_wdata <= 16'd0; c2h_pop <= 1'b0; pop_word <= 16'd0;
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
        if (byte_done) begin
          if (bidx != 8'hFF) bidx <= bidx + 8'd1;
          if (bidx == 8'd0) begin
            cmd <= rx_byte;
            if (rx_byte == C_POP) begin pop_word <= c2h_valid ? c2h_rdata : 16'd0; c2h_pop <= c2h_valid; end
          end else begin
            case (cmd)
              C_IMEM: begin
                if (bidx == 8'd1) imem_waddr[9:8] <= rx_byte[1:0];
                else if (bidx == 8'd2) imem_waddr[7:0] <= rx_byte;
                else if (bidx[0]) hi_byte <= rx_byte;                       // bidx 3,5,7,... = high byte
                else begin imem_wdata <= {hi_byte, rx_byte}; imem_wr <= 1'b1; end
              end
              C_CTRL: if (bidx == 8'd1) begin ctrl_run <= rx_byte[0]; core_reset <= rx_byte[1]; end
              C_PRE:  if (bidx == 8'd1) prescale <= rx_byte;
              C_PUSH: begin if (bidx == 8'd1) hi_byte <= rx_byte; else if (bidx == 8'd2) begin h2c_wdata <= {hi_byte, rx_byte}; h2c_push <= 1'b1; end end
              default: ;
            endcase
          end
        end
        if (imem_wr) imem_waddr <= imem_waddr + 10'd1;
      end
    end
  end
  // mosi_s[2] and rx_sh[7] exist only to keep the synchroniser/shift-register shapes uniform;
  // the design only ever reads mosi_s[1] (the settled sample) and rx_sh[6:0] (the low 7 bits
  // shifted in before the 8th bit completes rx_byte).
  wire _unused = &{cs_start, mosi_s[2], rx_sh[7], 1'b0};
endmodule
