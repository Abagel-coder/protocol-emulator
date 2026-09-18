`default_nettype none
`timescale 1ns / 1ps
module tb_core;
  initial begin $dumpfile("tb_core.fst"); $dumpvars(0, tb_core); #1; end
  reg clk = 0, rst_n = 0, run = 0, core_reset = 0; reg [7:0] prescale = 0;
  reg [7:0] ui_in = 0, uio_in = 0;
  wire [15:0] t_out; wire tick;
  wire [7:0] ui_sync, uio_sync, ui_prev, uio_prev; wire [6:0] uo_out; wire [7:0] uio_out, uio_oe;
  wire wr_en, wr_bank, pin_en, pin_bank, pin_val; wire [1:0] wr_op; wire [7:0] wr_mask; wire [2:0] pin_idx;
  wire [9:0] imem_addr; wire [15:0] imem_data;
  reg  h2c_push = 0; reg [15:0] h2c_wdata = 0; wire h2c_pop, h2c_valid, h2c_full; wire [15:0] h2c_rdata;
  wire c2h_push, c2h_valid, c2h_full; wire [15:0] c2h_data, c2h_rdata; reg c2h_pop = 0;
  wire [9:0] pc; wire halted, active, adv; wire [2:0] flags;
  // NOTE: this gating is a TEST-HARNESS-ONLY alignment trick, not chip behaviour. On the
  // real chip (src/project.v) the timebase free-runs from reset (`.en(1'b1)`): T's absolute
  // value when a program starts is unspecified (isa.yaml semantics.timebase), and firmware
  // must never assume T == 0. tools/sim.py's oracle models that by taking a `t0` starting
  // value (default 0) instead of hardcoding T = 0. This testbench exists to check cycle-exact
  // pin traces against that oracle at its default t0 = 0, so it needs T to actually read 0 in
  // the harness's cycle 0 -- hence gating the timebase off run_q_tb (a local mirror of
  // pe_core's internal run_q, which pe_core doesn't expose as a port) instead of tying en to
  // raw `run`: tying en to raw `run` would tick T one cycle too early, since T must read 0 in
  // the cycle where run_q first makes the core active (the cycle address 0 executes). Unlike
  // gating from `active`, this keeps T free-running through HALT, matching tools/sim.py's
  // Sim.step(), which ticks T unconditionally every cycle regardless of halted.
  reg run_q_tb = 1'b0;
  always @(posedge clk) run_q_tb <= (!rst_n || core_reset) ? 1'b0 : run;
  pe_timebase u_tb (.clk(clk), .rst_n(rst_n), .en(run_q_tb), .prescale(prescale), .t_out(t_out), .tick(tick));
  pe_gpio u_gpio (.clk(clk), .rst_n(rst_n), .ui_in(ui_in), .uio_in(uio_in), .ui_sync(ui_sync), .uio_sync(uio_sync),
                  .ui_prev(ui_prev), .uio_prev(uio_prev), .wr_en(wr_en), .wr_op(wr_op), .wr_bank(wr_bank), .wr_mask(wr_mask),
                  .pin_en(pin_en), .pin_bank(pin_bank), .pin_idx(pin_idx), .pin_val(pin_val),
                  .uo_out(uo_out), .uio_out(uio_out), .uio_oe(uio_oe));
  pe_imem_ff u_imem (.clk(clk), .raddr(imem_addr), .rdata(imem_data), .wr_en(1'b0), .waddr(10'd0), .wdata(16'd0));
  pe_fifo u_h2c (.clk(clk), .rst_n(rst_n), .push(h2c_push), .wdata(h2c_wdata), .pop(h2c_pop), .rdata(h2c_rdata), .valid(h2c_valid), .full(h2c_full));
  pe_fifo u_c2h (.clk(clk), .rst_n(rst_n), .push(c2h_push), .wdata(c2h_data), .pop(c2h_pop), .rdata(c2h_rdata), .valid(c2h_valid), .full(c2h_full));
  pe_core u_core (.clk(clk), .rst_n(rst_n), .run(run), .core_reset(core_reset), .imem_addr(imem_addr), .imem_data(imem_data),
                  .t_in(t_out), .ui_sync(ui_sync), .uio_sync(uio_sync), .ui_prev(ui_prev), .uio_prev(uio_prev), .uo_rb(uo_out), .uio_rb(uio_out),
                  .gpio_wr_en(wr_en), .gpio_wr_op(wr_op), .gpio_wr_bank(wr_bank), .gpio_wr_mask(wr_mask),
                  .gpio_pin_en(pin_en), .gpio_pin_bank(pin_bank), .gpio_pin_idx(pin_idx), .gpio_pin_val(pin_val),
                  .h2c_valid(h2c_valid), .h2c_data(h2c_rdata), .h2c_pop(h2c_pop),
                  .c2h_push(c2h_push), .c2h_data(c2h_data), .c2h_full(c2h_full),
                  .pc(pc), .halted(halted), .flags_out(flags), .active(active), .adv(adv));
endmodule
