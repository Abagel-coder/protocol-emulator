`default_nettype none
`timescale 1ns / 1ps
module tb_uartfw;
  initial begin $dumpfile("tb_uartfw.fst"); $dumpvars(0, tb_uartfw); #1; end
  reg clk = 0, rst_n = 0, ena = 1; reg [7:0] ui_in = 8'h40, uio_in = 0;
  wire [7:0] uo_out, uio_out, uio_oe;
  tt_um_abagel_coder_protocol_emulator user_project (.ui_in(ui_in), .uo_out(uo_out), .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe), .ena(ena), .clk(clk), .rst_n(rst_n));
  reg [7:0] ref_data = 8'h55; reg ref_start = 0; wire ref_tx, ref_busy;
  uart_tx #(.CLKS_PER_BIT(434)) u_ref (.clk(clk), .rst_n(rst_n), .data(ref_data), .start(ref_start), .tx(ref_tx), .busy(ref_busy));
endmodule
