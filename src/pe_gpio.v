`default_nettype none
`include "isa_defs.vh"
// GPIO block: 2-flop input synchronisers with previous-value registers, and
// registered output / output-enable banks written by the core's pin instructions.
module pe_gpio (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] ui_in,
    input  wire [7:0] uio_in,
    output reg  [7:0] ui_sync,
    output reg  [7:0] uio_sync,
    output reg  [7:0] ui_prev,
    output reg  [7:0] uio_prev,
    input  wire       wr_en,
    input  wire [1:0] wr_op,      // ISA_PIN_SET/CLR/TGL/OE
    input  wire       wr_bank,    // 0 = uo, 1 = uio (for OE: 0 = clear, 1 = set)
    input  wire [7:0] wr_mask,
    input  wire       pin_en,
    input  wire       pin_bank,
    input  wire [2:0] pin_idx,
    input  wire       pin_val,
    output reg  [6:0] uo_out,
    output reg  [7:0] uio_out,
    output reg  [7:0] uio_oe
);
  reg [7:0] ui_meta, uio_meta;
  always @(posedge clk) begin
    if (!rst_n) begin
      ui_meta <= 8'd0; uio_meta <= 8'd0; ui_sync <= 8'd0; uio_sync <= 8'd0; ui_prev <= 8'd0; uio_prev <= 8'd0;
    end else begin
      ui_meta <= ui_in; uio_meta <= uio_in;
      ui_sync <= ui_meta; uio_sync <= uio_meta;
      ui_prev <= ui_sync; uio_prev <= uio_sync;
    end
  end
  wire [7:0] uo_cur  = {1'b0, uo_out};
  wire [7:0] cur     = wr_bank ? uio_out : uo_cur;
  wire [7:0] set_v   = cur | wr_mask;
  wire [7:0] clr_v   = cur & ~wr_mask;
  wire [7:0] tgl_v   = cur ^ wr_mask;
  wire [7:0] new_v   = (wr_op == `ISA_PIN_SET) ? set_v : (wr_op == `ISA_PIN_CLR) ? clr_v : tgl_v;
  always @(posedge clk) begin
    if (!rst_n) begin
      uo_out <= 7'd0; uio_out <= 8'd0; uio_oe <= 8'd0;
    end else begin
      if (wr_en) begin
        if (wr_op == `ISA_PIN_OE) begin
          uio_oe <= wr_bank ? (uio_oe | wr_mask) : (uio_oe & ~wr_mask);
        end else if (wr_bank) begin
          uio_out <= new_v;
        end else begin
          uo_out <= new_v[6:0];
        end
      end
      if (pin_en) begin
        if (pin_bank) uio_out[pin_idx] <= pin_val;
        else if (pin_idx != 3'd7) uo_out[pin_idx] <= pin_val;
      end
    end
  end
endmodule
