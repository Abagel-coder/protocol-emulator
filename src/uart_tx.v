/*
 * Copyright (c) 2026 anbaghel
 * SPDX-License-Identifier: Apache-2.0
 *
 * Warm-up block: fixed-function 8N1 UART transmitter driving one pin.
 * This is step one of the competition advice ("start with a UART transmitter
 * out of a pin, then make it programmable"). It exists to prove the
 * design -> cocotb -> synthesis -> harden loop end to end and to serve as a
 * timing reference for the firmware version that replaces it.
 *
 * Timing contract (checked by test/test.py):
 *   - `start` is level-sensitive and sampled only while idle.
 *   - The start bit appears on `tx` on the clock edge after `start` is sampled.
 *   - Every bit (start, d0..d7 LSB first, stop) is held for exactly CLKS_PER_BIT cycles.
 *   - `busy` is high from the start bit through the end of the stop bit.
 */

`default_nettype none

module uart_tx #(
    parameter integer CLKS_PER_BIT = 434  // 50 MHz / 115200 baud = 434.03
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] data,
    input  wire       start,
    output reg        tx,
    output wire       busy
);

  localparam integer CNT_W = (CLKS_PER_BIT > 1) ? $clog2(CLKS_PER_BIT) : 1;
  /* verilator lint_off WIDTHTRUNC */
  localparam [CNT_W-1:0] LAST_CYCLE = CLKS_PER_BIT - 1;  // deliberately truncated to the counter width
  /* verilator lint_on WIDTHTRUNC */

  reg [CNT_W-1:0] cnt;      // cycles elapsed in the current bit
  reg [3:0]       bit_idx;  // 0 = start bit, 1..8 = data, 9 = stop bit
  reg [9:0]       frame;    // {stop, d7..d0, start}
  reg             active;

  assign busy = active;

  always @(posedge clk) begin
    if (!rst_n) begin
      tx      <= 1'b1;
      active  <= 1'b0;
      cnt     <= {CNT_W{1'b0}};
      bit_idx <= 4'd0;
      frame   <= 10'h3FF;
    end else if (!active) begin
      if (start) begin
        active  <= 1'b1;
        frame   <= {1'b1, data, 1'b0};
        tx      <= 1'b0;             // start bit
        cnt     <= {CNT_W{1'b0}};
        bit_idx <= 4'd0;
      end
    end else if (cnt == LAST_CYCLE) begin
      cnt <= {CNT_W{1'b0}};
      if (bit_idx == 4'd9) begin
        active <= 1'b0;              // stop bit finished; tx is already high
      end else begin
        bit_idx <= bit_idx + 4'd1;
        tx      <= frame[bit_idx + 4'd1];
      end
    end else begin
      cnt <= cnt + {{(CNT_W-1){1'b0}}, 1'b1};
    end
  end

endmodule
