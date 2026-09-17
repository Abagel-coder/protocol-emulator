/*
 * Copyright (c) 2026 anbaghel
 * SPDX-License-Identifier: Apache-2.0
 *
 * Tiny Tapeout top level: protocol-emulator core v0.
 *   ui_in[4] SCK, ui_in[5] MOSI, ui_in[6] CS_n, uo_out[7] MISO  (host SPI)
 *   ui_in[7] RUN;  ui_in[3:0] protocol inputs;  uo_out[6:0] protocol outputs;  uio[7:0] bidirectional
 */
`default_nettype none
module tt_um_abagel_coder_protocol_emulator (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);
  wire [15:0] t_out; wire tick;
  wire [7:0] ui_sync, uio_sync, ui_prev, uio_prev; wire [6:0] uo_core;
  wire wr_en, wr_bank, pin_en, pin_bank, pin_val; wire [1:0] wr_op; wire [7:0] wr_mask; wire [2:0] pin_idx;
  wire [9:0] imem_addr, imem_waddr; wire [15:0] imem_data, imem_wdata; wire imem_wr;
  wire ctrl_run, core_reset; wire [7:0] prescale; wire miso;
  wire h2c_push, h2c_pop, h2c_valid, h2c_full; wire [15:0] h2c_wdata, h2c_rdata;
  wire c2h_push, c2h_pop, c2h_valid, c2h_full; wire [15:0] c2h_data, c2h_rdata;
  wire [9:0] pc; wire halted, active, adv; wire [2:0] flags;

  pe_timebase u_tb (.clk(clk), .rst_n(rst_n), .en(1'b1), .prescale(prescale), .t_out(t_out), .tick(tick));
  pe_gpio u_gpio (.clk(clk), .rst_n(rst_n), .ui_in(ui_in), .uio_in(uio_in), .ui_sync(ui_sync), .uio_sync(uio_sync),
                  .ui_prev(ui_prev), .uio_prev(uio_prev), .wr_en(wr_en), .wr_op(wr_op), .wr_bank(wr_bank), .wr_mask(wr_mask),
                  .pin_en(pin_en), .pin_bank(pin_bank), .pin_idx(pin_idx), .pin_val(pin_val),
                  .uo_out(uo_core), .uio_out(uio_out), .uio_oe(uio_oe));
  pe_imem_ff u_imem (.clk(clk), .raddr(imem_addr), .rdata(imem_data), .wr_en(imem_wr), .waddr(imem_waddr), .wdata(imem_wdata));
  pe_fifo u_h2c (.clk(clk), .rst_n(rst_n), .push(h2c_push), .wdata(h2c_wdata), .pop(h2c_pop), .rdata(h2c_rdata), .valid(h2c_valid), .full(h2c_full));
  pe_fifo u_c2h (.clk(clk), .rst_n(rst_n), .push(c2h_push), .wdata(c2h_data), .pop(c2h_pop), .rdata(c2h_rdata), .valid(c2h_valid), .full(c2h_full));
  pe_core u_core (.clk(clk), .rst_n(rst_n), .run(ui_in[7] | ctrl_run), .core_reset(core_reset),
                  .imem_addr(imem_addr), .imem_data(imem_data), .t_in(t_out),
                  .ui_sync(ui_sync), .uio_sync(uio_sync), .ui_prev(ui_prev), .uio_prev(uio_prev), .uo_rb(uo_core), .uio_rb(uio_out),
                  .gpio_wr_en(wr_en), .gpio_wr_op(wr_op), .gpio_wr_bank(wr_bank), .gpio_wr_mask(wr_mask),
                  .gpio_pin_en(pin_en), .gpio_pin_bank(pin_bank), .gpio_pin_idx(pin_idx), .gpio_pin_val(pin_val),
                  .h2c_valid(h2c_valid), .h2c_data(h2c_rdata), .h2c_pop(h2c_pop),
                  .c2h_push(c2h_push), .c2h_data(c2h_data), .c2h_full(c2h_full),
                  .pc(pc), .halted(halted), .flags_out(flags), .active(active), .adv(adv));
  pe_host_spi u_host (.clk(clk), .rst_n(rst_n), .sck(ui_in[4]), .mosi(ui_in[5]), .cs_n(ui_in[6]), .miso(miso),
                      .imem_wr(imem_wr), .imem_waddr(imem_waddr), .imem_wdata(imem_wdata),
                      .ctrl_run(ctrl_run), .core_reset(core_reset), .prescale(prescale),
                      .halted(halted), .running(active), .pc(pc), .flags(flags),
                      .ui_in(ui_in), .uio_in(uio_in), .uo_out(uo_core), .uio_out(uio_out), .uio_oe(uio_oe),
                      .h2c_push(h2c_push), .h2c_wdata(h2c_wdata), .h2c_valid(h2c_valid),
                      .c2h_pop(c2h_pop), .c2h_rdata(c2h_rdata), .c2h_valid(c2h_valid));
  assign uo_out = {miso, uo_core};
  wire _unused = &{ena, tick, h2c_full, adv, 1'b0};
endmodule
