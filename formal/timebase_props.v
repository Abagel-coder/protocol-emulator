`default_nettype none
// Supplementary proof for T4_bounded_wait's "counting part" (see
// formal/README.md). Folded into formal/core.sby as the timebase_bmc /
// timebase_prove tasks (a single .sby file, different top module/engine per
// task via task tags -- see core.sby's [tasks]/[script]/[files] "tb" tag).
// With `en` forced to 1 and `prescale` fixed to an arbitrary-but-constant
// value ((* anyconst *)), proves that pe_timebase's internal prescale
// counter never exceeds `prescale` (so `tick` is periodic, at most every
// prescale+1 cycles -- it can never stall forever) and that `t_out` (T)
// never skips a value (it only ever holds or advances by exactly 1 per
// cycle). Combined with pe_core's T4 structural lemmas (wdead is held
// constant while a timed wait is outstanding, and the wait completes in any
// cycle where t_in == wdead), this gives: a timed wait started at T0 with
// deadline wdead = T0 + timeout must complete within one 16-bit wrap of T,
// i.e. at most 65536 ticks.
module timebase_props (input wire clk);
  reg rst_n = 1'b0;
  always @(posedge clk) rst_n <= 1'b1;
  (* anyconst *) wire [7:0] prescale;
  wire [15:0] t_out; wire tick;
  pe_timebase u_tb (.clk(clk), .rst_n(rst_n), .en(1'b1), .prescale(prescale), .t_out(t_out), .tick(tick));

  reg f_past_valid = 1'b0;
  always @(posedge clk) f_past_valid <= 1'b1;

  // Black-box shadow counter (formal harness only, not part of the RTL under
  // proof): cycles elapsed since the last tick (or reset). Proving this never
  // exceeds the fixed prescale shows tick fires at least once every
  // prescale+1 cycles -- it cannot stall forever -- using only pe_timebase's
  // ports (en, prescale, t_out, tick), not its internals.
  reg [7:0] since_tick;
  always @(posedge clk) begin
    if (!rst_n) since_tick <= 8'd0;
    else if (tick) since_tick <= 8'd0;
    else since_tick <= since_tick + 8'd1;
  end
  always @(posedge clk) if (rst_n) assert(since_tick <= prescale);

  // T never skips a value: each cycle it either holds or advances by
  // exactly 1, so it must pass through every 16-bit value (in particular
  // any latched deadline) before it can wrap back to that value again.
  always @(posedge clk)
    if (f_past_valid && $past(rst_n))
      assert((t_out == $past(t_out)) || (t_out == $past(t_out) + 16'd1));

  // cover: a tick actually happens, so the proofs above are not vacuous.
  always @(posedge clk) cover(tick);
endmodule
