`default_nettype none
// Formal wrapper for T1-T5 (see formal/README.md). Instantiates the timebase,
// GPIO block and core with a free instruction stream, free inputs and free
// host-side signals ((* anyseq *)); reset (rst_n) is asserted in cycle 0 only.
// This is deliberately more permissive than the real chip (e.g. imem_data is
// free every cycle rather than a deterministic function of imem_addr, and the
// timebase's `en` is tied to the free `run` signal rather than the real
// top level's constant 1) -- any property proved here also holds for every
// more-constrained real environment.
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
  pe_timebase u_tb (.clk(clk), .rst_n(rst_n), .en(run), .prescale(prescale), .t_out(t_out), .tick(tick));
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
endmodule
