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

`ifdef FORMAL
  // SymbiYosys property. See formal/README.md and formal/core.sby.
  reg f_past_valid = 1'b0;
  always @(posedge clk) f_past_valid <= 1'b1;

  // T3_reset_safety, grant mask: f_oe_granted accumulates every bit ever
  // granted by an executed OE-*set* write (wr_en && wr_op==ISA_PIN_OE &&
  // wr_bank -- wr_bank==1 means "set" for the OE class, see the port
  // comment above), cleared only on reset. uio_oe may only ever have bits
  // set that have actually been granted this way. A one-shot "has any OE
  // write ever happened" flag (the original formulation) does not catch an
  // OE write that sets uio_oe wider than its own wr_mask, or an OE-clear
  // write that leaves bits on -- see formal/README.md "Mutation testing"
  // for the mutant this replacement is specifically for.
  reg [7:0] f_oe_granted;
  always @(posedge clk) begin
    if (!rst_n) f_oe_granted <= 8'd0;
    else if (wr_en && wr_op == `ISA_PIN_OE && wr_bank) f_oe_granted <= f_oe_granted | wr_mask;
  end
  // Gated by f_past_valid: uio_oe (and f_oe_granted) have no Verilog
  // initializer, so their value at the very first (pre-clock-edge) instant
  // is formally unconstrained until the synchronous reset has actually
  // latched it once, exactly like real flip-flops -- the same reasoning
  // behind every other f_past_valid guard in this proof.
  always @(posedge clk) if (f_past_valid) assert((uio_oe & ~f_oe_granted) == 8'd0);

  // T3b/T3c (spec-pinning restatements, kept for the same reason T1/T5a are
  // -- see formal/README.md): the exact next-state of uio_oe following an
  // executed OE write. An OE-clear write with mask m leaves those bits 0 the
  // next cycle (T3b); an OE-set write with mask m leaves them 1 the next
  // cycle (T3c). Together these pin pe_gpio's own
  // `uio_oe <= wr_bank ? (uio_oe | wr_mask) : (uio_oe & ~wr_mask);` line.
  always @(posedge clk)
    if (f_past_valid && $past(rst_n) && $past(wr_en) && $past(wr_op) == `ISA_PIN_OE && !$past(wr_bank))
      assert((uio_oe & $past(wr_mask)) == 8'd0);
  always @(posedge clk)
    if (f_past_valid && $past(rst_n) && $past(wr_en) && $past(wr_op) == `ISA_PIN_OE && $past(wr_bank))
      assert((uio_oe & $past(wr_mask)) == $past(wr_mask));

  // cover: gated on rst_n && $past(rst_n)/f_past_valid so it cannot be
  // witnessed by pre-reset uninitialised-flop state. A post-reset executed
  // OE-set write is immediately followed by uio_oe reading back exactly the
  // accumulated grant mask -- not more, not less -- so the properties above
  // are not vacuously true because uio_oe never actually gets driven.
  always @(posedge clk)
    if (f_past_valid && rst_n && $past(rst_n) && $past(wr_en) && $past(wr_op) == `ISA_PIN_OE && $past(wr_bank))
      cover(uio_oe == f_oe_granted);
`endif
endmodule
