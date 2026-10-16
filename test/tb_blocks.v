`default_nettype none
`timescale 1ns / 1ps
module tb_blocks;
  initial begin $dumpfile("tb_blocks.fst"); $dumpvars(0, tb_blocks); #1; end
  reg clk = 0, rst_n = 0, en = 0; reg [7:0] prescale = 0;
  wire [15:0] t_out; wire tick;
  pe_timebase tb_u (.clk(clk), .rst_n(rst_n), .en(en), .prescale(prescale), .t_out(t_out), .tick(tick));
  reg [7:0] ui_in = 0, uio_in = 0; wire [7:0] ui_sync, uio_sync, ui_prev, uio_prev;
  reg wr_en = 0; reg [1:0] wr_op = 0; reg wr_bank = 0; reg [7:0] wr_mask = 0;
  reg pin_en = 0, pin_bank = 0, pin_val = 0; reg [2:0] pin_idx = 0;
  wire [6:0] uo_out; wire [7:0] uio_out, uio_oe;
  pe_gpio g (.clk(clk), .rst_n(rst_n), .ui_in(ui_in), .uio_in(uio_in), .ui_sync(ui_sync), .uio_sync(uio_sync),
             .ui_prev(ui_prev), .uio_prev(uio_prev), .wr_en(wr_en), .wr_op(wr_op), .wr_bank(wr_bank), .wr_mask(wr_mask),
             .pin_en(pin_en), .pin_bank(pin_bank), .pin_idx(pin_idx), .pin_val(pin_val),
             .uo_out(uo_out), .uio_out(uio_out), .uio_oe(uio_oe));
  // pe_imem: both implementations side by side on identical inputs (test_blocks.py imem_* tests)
  reg im_active = 0, im_wr_en = 0; reg [9:0] im_raddr = 0, im_waddr = 0; reg [15:0] im_wdata = 0;
  wire [15:0] im_rdata_m, im_rdata_f; wire im_drop_m, im_drop_f;
  pe_imem #(.IMPL("MACRO")) im_m (.clk(clk), .active(im_active), .raddr(im_raddr), .rdata(im_rdata_m),
                                  .wr_en(im_wr_en), .waddr(im_waddr), .wdata(im_wdata), .wr_dropped(im_drop_m));
  pe_imem #(.IMPL("FLOPS")) im_f (.clk(clk), .active(im_active), .raddr(im_raddr), .rdata(im_rdata_f),
                                  .wr_en(im_wr_en), .waddr(im_waddr), .wdata(im_wdata), .wr_dropped(im_drop_f));
endmodule
