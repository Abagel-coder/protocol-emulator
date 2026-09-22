# cocotb suites

Four suites, one Makefile each, all run by the GitHub `test` workflow (`make -B` in this directory; `make` exits 0 even when a test fails, so check the `FAIL=0` summary or grep `results.xml` for `failure`):

- `Makefile` (`test_host.py`, `tb.v`): the whole chip through its Tiny Tapeout pins -- SPI loader protocol, RUN pin, status/FIFO/GPIO commands, datasheet byte sequences; pin-only, so it also runs at gate level (`GATES=yes` with `gate_level_netlist.v`, which the `gds` workflow does).
- `Makefile.core` (`test_core.py`, `test_diff.py`, `tb_core.v`): directed core tests with backdoor instruction-memory load, plus the differential fuzzer against `tools/sim.py` (`DIFF_PROGRAMS`, default 200).
- `Makefile.blocks` (`test_blocks.py`, `tb_blocks.v`): timebase and GPIO blocks on their own.
- `Makefile.uartfw` (`test_uart_fw.py`, `tb_uartfw.v`): `firmware/uart_tx.s` on the core versus the fixed transmitter `src/uart_tx.v`, cycle for cycle.

Waveforms land in `tb*.fst` (view with `gtkwave tb.fst tb.gtkw` or `surfer tb.fst`).
