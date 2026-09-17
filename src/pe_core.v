`default_nettype none
`include "isa_defs.vh"
// Protocol-emulator core v0: 2-stage fetch/execute, one branch delay slot, bounded waits.
// Timing contract: every non-WAIT instruction completes in one cycle (adv == 1 whenever
// active and the instruction is not a WAIT or HALT). Pin writes reach the GPIO registers on
// the clock edge that ends the executing cycle.
module pe_core (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        run,
    input  wire        core_reset,
    output wire [9:0]  imem_addr,
    input  wire [15:0] imem_data,
    input  wire [15:0] t_in,
    input  wire [7:0]  ui_sync,
    input  wire [7:0]  uio_sync,
    input  wire [7:0]  ui_prev,
    input  wire [7:0]  uio_prev,
    input  wire [6:0]  uo_rb,
    input  wire [7:0]  uio_rb,
    output wire        gpio_wr_en,
    output wire [1:0]  gpio_wr_op,
    output wire        gpio_wr_bank,
    output wire [7:0]  gpio_wr_mask,
    output wire        gpio_pin_en,
    output wire        gpio_pin_bank,
    output wire [2:0]  gpio_pin_idx,
    output wire        gpio_pin_val,
    input  wire        h2c_valid,
    input  wire [15:0] h2c_data,
    output wire        h2c_pop,
    output wire        c2h_push,
    output wire [15:0] c2h_data,
    input  wire        c2h_full,
    output reg  [9:0]  pc,
    output reg         halted,
    output wire [2:0]  flags_out,
    output wire        active,
    output wire        adv
);
  // ---------------------------------------------------------------- state
  reg [15:0] regs [0:7];
  reg        fz, fc, fto;
  reg [9:0]  st0, st1, st2, st3;       // call stack, st0 = top
  reg [2:0]  stcnt;
  reg        redir_v;
  reg [9:0]  redir_t;
  reg        wait_active;
  reg [8:0]  dcnt;
  reg [15:0] wdead;
  reg        run_q;                    // one-cycle-delayed run: the first active cycle's
                                        // side effects must land on the edge *after* the one
                                        // where `run` first goes high, not on that same edge.

  assign active    = run_q && !halted;
  assign flags_out = {fto, fc, fz};

  // ---------------------------------------------------------------- decode
  wire [15:0] ir  = imem_data;
  wire [3:0]  cls = ir[15:12];
  wire [2:0]  f_rd = ir[11:9];
  wire [2:0]  f_rs = ir[8:6];
  wire [15:0] rd_v = (f_rd == 3'd0) ? 16'd0 : regs[f_rd];
  wire [15:0] rs_v = (f_rs == 3'd0) ? 16'd0 : regs[f_rs];
  wire [7:0]  ui_eff   = {4'b0000, ui_sync[3:0]};   // ui[7:4] are host lines, never protocol pins
  wire [7:0]  uip_eff  = {4'b0000, ui_prev[3:0]};

  wire is_misc = (cls == `ISA_CLS_MISC);
  wire is_halt = is_misc && (ir[11:0] == `ISA_MISC_HALT);
  wire is_ret  = is_misc && (ir[11:0] == `ISA_MISC_RET);
  wire is_wait = (cls == `ISA_CLS_WAIT);
  wire is_jmp  = (cls == `ISA_CLS_JMP);

  // ---- wait unit
  wire [2:0]  w_sub  = ir[11:9];
  wire [2:0]  w_rt   = ir[8:6];
  wire [8:0]  w_imm9 = ir[8:0];
  wire        w_bank = ir[5];
  wire [2:0]  w_pin  = ir[4:2];
  wire [1:0]  w_cond = ir[1:0];
  wire [5:0]  w_flag = ir[5:0];
  wire [15:0] rt_v   = (w_rt == 3'd0) ? 16'd0 : regs[w_rt];
  wire [15:0] tmo    = (w_rt == 3'd0) ? 16'hFFFF : rt_v;
  wire [15:0] dead_now = wait_active ? wdead : (t_in + tmo);
  wire        pin_now  = w_bank ? uio_sync[w_pin] : ui_eff[w_pin];
  wire        pin_prev = w_bank ? uio_prev[w_pin] : uip_eff[w_pin];
  wire        cond_met = (w_cond == `ISA_WP_LOW)  ? !pin_now :
                         (w_cond == `ISA_WP_HIGH) ?  pin_now :
                         (w_cond == `ISA_WP_RISE) ? (pin_now && !pin_prev) : (!pin_now && pin_prev);
  wire        flag_v   = (w_flag == {1'b0, `ISA_FLAG_RXV}) ? h2c_valid :
                         (w_flag == {1'b0, `ISA_FLAG_TXE}) ? !c2h_full :
                         (w_flag == {1'b0, `ISA_FLAG_TO})  ? fto : 1'b0;
  wire        waitt_done = (t_in == rt_v);
  wire        delay_done = wait_active ? (dcnt == 9'd0) : (w_imm9 == 9'd0);
  wire        timed_cond = (w_sub == `ISA_WAIT_WAITP) ? cond_met :
                           (w_sub == `ISA_WAIT_WAITF) ? flag_v : 1'b1;   // WAITL: no lanes in v0
  wire        timed_to   = (t_in == dead_now);
  wire        is_timed   = is_wait && (w_sub != `ISA_WAIT_WAITT) && (w_sub != `ISA_WAIT_DELAY);
  wire        wait_done  = (w_sub == `ISA_WAIT_WAITT) ? waitt_done :
                           (w_sub == `ISA_WAIT_DELAY) ? delay_done : (timed_cond || timed_to);
  assign adv = active && !is_halt && (!is_wait || wait_done);

  // ---- branch targets
  wire [9:0] pc_p1 = pc + 10'd1;
  wire [9:0] rel9  = pc_p1 + {{1{ir[8]}}, ir[8:0]};
  wire [9:0] rel7  = pc_p1 + {{3{ir[6]}}, ir[6:0]};
  wire [9:0] rel6  = pc_p1 + {{4{ir[5]}}, ir[5:0]};
  wire [2:0] br_c  = ir[11:9];
  wire br_take = (br_c == `ISA_BR_BZ)  ?  fz : (br_c == `ISA_BR_BNZ) ? !fz :
                 (br_c == `ISA_BR_BC)  ?  fc : (br_c == `ISA_BR_BNC) ? !fc :
                 (br_c == `ISA_BR_BTO) ? fto : (br_c == `ISA_BR_BNTO) ? !fto : 1'b0;
  wire        bp_v  = ir[10] ? uio_sync[ir[9:7]] : ui_eff[ir[9:7]];
  wire [4:0]  bf_f  = ir[10:6];
  wire        bf_v  = (bf_f == `ISA_FLAG_RXV) ? h2c_valid : (bf_f == `ISA_FLAG_TXE) ? !c2h_full : (bf_f == `ISA_FLAG_TO) ? fto : 1'b0;
  wire redirect_new = (cls == `ISA_CLS_BR && br_take) || is_jmp || is_ret ||
                      (cls == `ISA_CLS_BPIN && bp_v == ir[11]) || (cls == `ISA_CLS_BFLAG && bf_v == ir[11]);
  wire [9:0] ret_t  = (stcnt == 3'd0) ? 10'd0 : st0;
  wire [9:0] redirect_tgt = is_jmp ? ir[9:0] : is_ret ? ret_t : (cls == `ISA_CLS_BR) ? rel9 : (cls == `ISA_CLS_BPIN) ? rel7 : rel6;
  wire [9:0] next_pc = !adv ? pc : (redir_v ? redir_t : pc_p1);
  assign imem_addr = rst_n ? next_pc : 10'd0;

  // ---- ALU
  reg  [15:0] alu_y; reg alu_c; reg alu_wr; reg alu_setc;
  wire [16:0] sum  = {1'b0, rd_v} + {1'b0, rs_v};
  wire [16:0] diff = {1'b0, rd_v} + {1'b0, ~rs_v} + 17'd1;
  wire [16:0] addi = {1'b0, rd_v} + {1'b0, {{7{ir[8]}}, ir[8:0]}};
  always @* begin
    alu_y = rs_v; alu_c = fc; alu_wr = 1'b1; alu_setc = 1'b0;
    case (ir[5:2])
      `ISA_ALU_MOV:  begin alu_y = rs_v; end
      `ISA_ALU_ADD:  begin alu_y = sum[15:0];  alu_c = sum[16];  alu_setc = 1'b1; end
      `ISA_ALU_SUB:  begin alu_y = diff[15:0]; alu_c = diff[16]; alu_setc = 1'b1; end
      `ISA_ALU_AND:  begin alu_y = rd_v & rs_v; end
      `ISA_ALU_OR:   begin alu_y = rd_v | rs_v; end
      `ISA_ALU_XOR:  begin alu_y = rd_v ^ rs_v; end
      `ISA_ALU_SHL:  begin alu_y = {rd_v[14:0], 1'b0}; alu_c = rd_v[15]; alu_setc = 1'b1; end
      `ISA_ALU_SHR:  begin alu_y = {1'b0, rd_v[15:1]}; alu_c = rd_v[0];  alu_setc = 1'b1; end
      `ISA_ALU_ROR:  begin alu_y = {rd_v[0], rd_v[15:1]}; alu_c = rd_v[0]; alu_setc = 1'b1; end
      `ISA_ALU_CMP:  begin alu_y = diff[15:0]; alu_c = diff[16]; alu_setc = 1'b1; alu_wr = 1'b0; end
      `ISA_ALU_BITT: begin alu_y = rd_v & rs_v; alu_wr = 1'b0; end
      default:       begin alu_wr = 1'b0; end
    endcase
  end

  // ---- GPIO / host side-effects (single-cycle classes, so adv is implied by active)
  assign gpio_wr_en   = active && (cls == `ISA_CLS_PIN);
  assign gpio_wr_op   = ir[11:10];
  assign gpio_wr_bank = ir[8];
  assign gpio_wr_mask = ir[7:0];
  assign gpio_pin_en   = active && (cls == `ISA_CLS_SETR);
  assign gpio_pin_bank = ir[8];
  assign gpio_pin_idx  = ir[7:5];
  assign gpio_pin_val  = rd_v[ir[3:0]];
  assign h2c_pop  = active && (cls == `ISA_CLS_HOST) &&  ir[8] && h2c_valid;
  assign c2h_push = active && (cls == `ISA_CLS_HOST) && !ir[8] && !c2h_full;
  assign c2h_data = rd_v;
  wire [15:0] in_v = (ir[8:7] == `ISA_BANKI_UI) ? {8'd0, ui_eff} : (ir[8:7] == `ISA_BANKI_UIO) ? {8'd0, uio_sync} :
                     (ir[8:7] == `ISA_BANKI_UOR) ? {9'd0, uo_rb} : {8'd0, uio_rb};
  wire _unused = &{ui_sync[7:4], ui_prev[7:4], 1'b0};
  wire [15:0] ldi_v  = ir[8] ? {ir[7:0], rd_v[7:0]} : {8'd0, ir[7:0]};
  wire [15:0] time_v = (ir[8] == `ISA_TIME_SETT) ? (t_in + {8'd0, ir[7:0]}) : (rd_v + {8'd0, ir[7:0]});

  // ---------------------------------------------------------------- sequential
  integer i;
  always @(posedge clk) begin
    if (!rst_n || core_reset) begin
      pc <= 10'd0; halted <= 1'b0; fz <= 1'b0; fc <= 1'b0; fto <= 1'b0;
      redir_v <= 1'b0; redir_t <= 10'd0; wait_active <= 1'b0; dcnt <= 9'd0; wdead <= 16'd0;
      st0 <= 10'd0; st1 <= 10'd0; st2 <= 10'd0; st3 <= 10'd0; stcnt <= 3'd0; run_q <= 1'b0;
      for (i = 0; i < 8; i = i + 1) regs[i] <= 16'd0;
    end else begin
    run_q <= run;
    if (active) begin
      if (is_halt) halted <= 1'b1;
      if (adv) begin
        pc <= next_pc; redir_v <= redirect_new; redir_t <= redirect_tgt; wait_active <= 1'b0;
        if (is_timed) fto <= !timed_cond;
        case (cls)
          `ISA_CLS_LDI:  begin if (f_rd != 3'd0) regs[f_rd] <= ldi_v; fz <= (ldi_v == 16'd0); end
          `ISA_CLS_ALU:  begin if (alu_wr && f_rd != 3'd0) regs[f_rd] <= alu_y; fz <= (alu_y == 16'd0); if (alu_setc) fc <= alu_c; end
          `ISA_CLS_ADDI: begin if (f_rd != 3'd0) regs[f_rd] <= addi[15:0]; fz <= (addi[15:0] == 16'd0); fc <= addi[16]; end
          `ISA_CLS_IN:   begin if (f_rd != 3'd0) regs[f_rd] <= in_v; fz <= (in_v == 16'd0); end
          `ISA_CLS_TIME: begin if (f_rd != 3'd0) regs[f_rd] <= time_v; end
          `ISA_CLS_HOST: begin if (ir[8] && f_rd != 3'd0) regs[f_rd] <= h2c_valid ? h2c_data : 16'd0; end
          `ISA_CLS_JMP:  begin
            if (ir[11]) begin st0 <= pc + 10'd2; st1 <= st0; st2 <= st1; st3 <= st2; if (stcnt != 3'd4) stcnt <= stcnt + 3'd1; end
          end
          `ISA_CLS_MISC: begin
            if (is_ret && stcnt != 3'd0) begin st0 <= st1; st1 <= st2; st2 <= st3; stcnt <= stcnt - 3'd1; end
          end
          default: ;
        endcase
      end else if (is_wait) begin
        if (!wait_active) begin wait_active <= 1'b1; wdead <= dead_now; dcnt <= w_imm9 - 9'd1; end
        else if (w_sub == `ISA_WAIT_DELAY) dcnt <= dcnt - 9'd1;
      end
    end
    end
  end
endmodule
