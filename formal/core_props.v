`default_nettype none
// Formal wrapper for T1-T5 (see formal/README.md). Instantiates the timebase,
// GPIO block and core with a free instruction stream, free inputs and free
// host-side signals ((* anyseq *)); reset (rst_n) is asserted in cycle 0 only.
// This is deliberately more permissive than the real chip in most respects
// (e.g. imem_data is free every cycle rather than a deterministic function of
// imem_addr) -- any property proved here also holds for every
// more-constrained real environment. One deliberate exception: the
// timebase's `en` is tied to the constant 1'b1 here, exactly as the real top
// level wires it (src/project.v's `pe_timebase` instance uses `.en(1'b1)`,
// not `.en(run)`). Tying `en` to the free `run` signal instead would have
// been a *restriction* relative to the chip, not a relaxation (the real
// timebase always counts, independent of RUN) -- properties proved under a
// restriction do not automatically hold for the real, more-permissive
// environment, so `en` is wired chip-accurately here rather than loosely.
module core_props (input wire clk);
  reg rst_n = 1'b0;
  always @(posedge clk) rst_n <= 1'b1;
  (* anyseq *) wire run, core_reset, h2c_valid, c2h_full;
  (* anyseq *) wire [15:0] imem_data, h2c_data;
  (* anyseq *) wire [7:0] ui_in, uio_in, prescale;
  wire [15:0] t_out; wire tick;
  wire [7:0] ui_sync, uio_sync, ui_prev, uio_prev; wire [6:0] uo_out; wire [7:0] uio_out, uio_oe;
  wire wr_en, wr_bank, pin_en, pin_bank, pin_val; wire [1:0] wr_op; wire [7:0] wr_mask; wire [2:0] pin_idx;
  wire [9:0] imem_addr, pc; wire halted, active, adv, h2c_pop, c2h_push; wire [15:0] c2h_data; wire [2:0] flags;
  pe_timebase u_tb (.clk(clk), .rst_n(rst_n), .en(1'b1), .prescale(prescale), .t_out(t_out), .tick(tick));
  pe_gpio u_gpio (.clk(clk), .rst_n(rst_n), .ui_in(ui_in), .uio_in(uio_in), .ui_sync(ui_sync), .uio_sync(uio_sync),
                  .ui_prev(ui_prev), .uio_prev(uio_prev), .wr_en(wr_en), .wr_op(wr_op), .wr_bank(wr_bank), .wr_mask(wr_mask),
                  .pin_en(pin_en), .pin_bank(pin_bank), .pin_idx(pin_idx), .pin_val(pin_val),
                  .uo_out(uo_out), .uio_out(uio_out), .uio_oe(uio_oe));
  pe_core u_core (.clk(clk), .rst_n(rst_n), .run(run), .core_reset(core_reset), .imem_addr(imem_addr), .imem_data(imem_data),
                  .t_in(t_out), .ui_sync(ui_sync), .uio_sync(uio_sync), .ui_prev(ui_prev), .uio_prev(uio_prev), .uo_rb(uo_out), .uio_rb(uio_out),
                  .gpio_wr_en(wr_en), .gpio_wr_op(wr_op), .gpio_wr_bank(wr_bank), .gpio_wr_mask(wr_mask),
                  .gpio_pin_en(pin_en), .gpio_pin_bank(pin_bank), .gpio_pin_idx(pin_idx), .gpio_pin_val(pin_val),
                  .h2c_valid(h2c_valid), .h2c_data(h2c_data), .h2c_pop(h2c_pop),
                  .c2h_push(c2h_push), .c2h_data(c2h_data), .c2h_full(c2h_full),
                  .pc(pc), .halted(halted), .flags_out(flags), .active(active), .adv(adv));

  // ---- T5c/T5d: the "nothing changes" half of T5_side_effects_only_when_active,
  // stated across the pe_core/pe_gpio module boundary. T5b (inside
  // pe_core.v) only pins pe_core's own strobe *outputs* (gpio_wr_en,
  // gpio_pin_en, h2c_pop, c2h_push) to 0 when !active; it says nothing about
  // what pe_gpio then actually does with them. T5c/T5d close that gap here,
  // where both modules are visible.
  reg f_past_valid = 1'b0;
  always @(posedge clk) f_past_valid <= 1'b1;

  // T5c (independent fact -- requires pe_gpio's own register-hold behaviour,
  // not just pe_core's strobes being 0): whenever the core was not active in
  // the previous cycle (and rst_n was already high), the GPIO output
  // registers uo_out/uio_out/uio_oe are stable.
  always @(posedge clk)
    if (f_past_valid && $past(rst_n) && !$past(active))
      assert(uo_out == $past(uo_out) && uio_out == $past(uio_out) && uio_oe == $past(uio_oe));

  // T5d (wrapper-level restatement of T5b, NOT an independent cross-module
  // fact -- see formal/README.md "What is pinned vs. independent"): both
  // h2c_pop and c2h_push are pe_core outputs, and this harness instantiates
  // no FIFO (h2c_valid/h2c_data/c2h_full are free (* anyseq *) wires, not a
  // real queue), so "h2c_pop/c2h_push are low when !active" is already
  // exactly what T5b (in pe_core.v) asserts about pe_core's own outputs --
  // unlike T5c, nothing outside pe_core (no register-hold behaviour in
  // another module) is needed to state or prove it. Kept anyway as a
  // boundary check: it fails immediately if a future FIFO/host-interface
  // module were instantiated here and wired to different signals.
  always @(posedge clk)
    if (f_past_valid && $past(rst_n) && !$past(active))
      assert(!$past(h2c_pop) && !$past(c2h_push));
endmodule
