/*
 * Copyright (c) 2026 anbaghel
 * SPDX-License-Identifier: Apache-2.0
 *
 * Tiny Tapeout top level. Currently wraps the warm-up UART transmitter; the
 * programmable protocol-emulator core replaces it once the ISA is frozen.
 *
 * Pin map (warm-up):
 *   ui_in[7:0]  data byte to send
 *   uio_in[0]   START (level; hold high until BUSY rises)
 *   uo_out[0]   TX  (matches the demo board's "UART to USB" option 2 pin)
 *   uo_out[1]   BUSY
 */

`default_nettype none

module tt_um_abagel_coder_protocol_emulator (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

  wire tx;
  wire busy;

  uart_tx #(
      .CLKS_PER_BIT(434)
  ) u_uart_tx (
      .clk  (clk),
      .rst_n(rst_n),
      .data (ui_in),
      .start(uio_in[0]),
      .tx   (tx),
      .busy (busy)
  );

  assign uo_out  = {6'b000000, busy, tx};
  assign uio_out = 8'b00000000;
  assign uio_oe  = 8'b00000000;  // all bidirectional pins are inputs

  // List all unused inputs to prevent warnings
  wire _unused = &{ena, uio_in[7:1], 1'b0};

endmodule
