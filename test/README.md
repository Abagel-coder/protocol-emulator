# cocotb suites

Four suites, one Makefile each, all run by the GitHub `test` workflow (`make -B` in this directory; `make` exits 0 even when a test fails, so check the `FAIL=0` summary or grep `results.xml` for `failure`):

- `Makefile` (`test_host.py`, `tb.v`): the whole chip through its Tiny Tapeout pins -- SPI loader protocol, RUN pin, status/FIFO/GPIO commands, datasheet byte sequences; pin-only, so it also runs at gate level (`GATES=yes` with `gate_level_netlist.v`, which the `gds` workflow does).
- `Makefile.core` (`test_core.py`, `test_diff.py`, `tb_core.v`): directed core tests with backdoor instruction-memory load (`imem_load.py`), plus the differential fuzzer against `tools/sim.py` (`DIFF_PROGRAMS`, default 200).
- `Makefile.blocks` (`test_blocks.py`, `tb_blocks.v`): timebase, GPIO and instruction-memory (`pe_imem`, both `IMPL` branches side by side) blocks on their own.
- `Makefile.uartfw` (`test_uart_fw.py`, `tb_uartfw.v`, `uart_tx_ref.v`): `firmware/uart_tx.s` on the core versus the fixed transmitter `uart_tx_ref.v` (a test-only reference kept here in `test/`, not part of the chip), cycle for cycle.

The instruction memory is an IHP SRAM macro. Its two PDK simulation models are vendored in `models/` (source and PDK commit in `models/README.md`); every Makefile compiles them with `-DFUNCTIONAL`, RTL and gate level alike (the netlist keeps the macro as a black box). `imem_load.py`'s `load_imem(dut.u_imem, words)` deposits a program straight into the model's array (`u_imem.g_macro.u_sram.i_SRAM_1P_behavioral_bm_bist.memory`) and zero-fills the rest of the 512 words; the host suite loads over SPI instead.

Waveforms land in `tb*.fst` (view with `gtkwave tb.fst tb.gtkw` or `surfer tb.fst`).
