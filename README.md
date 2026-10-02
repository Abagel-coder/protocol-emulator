![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/tools/badge.svg) ![](../../workflows/fpga/badge.svg)

# Protocol Emulator — Jane Street ASIC Competition entry

An open-source programmable protocol-emulator CPU for IHP 130 nm SG13CMOS5L via Tiny Tapeout (6x4 tiles). Protocols such as UART, SPI and I2C run as firmware on a small deterministic core whose instruction set is built for pin I/O and exact cycle timing.

- Competition: https://blog.janestreet.com/protocol-emulator-asic-competition/ (deadline 2027-01-18)
- Plan and schedule: [PLAN.md](PLAN.md)
- Architecture proposal: [docs/superpowers/specs/2026-09-15-protocol-emulator-design.md](docs/superpowers/specs/2026-09-15-protocol-emulator-design.md)
- Research notes: [docs/research/](docs/research/)
- Datasheet text (Tiny Tapeout): [docs/info.md](docs/info.md)

## Status

| Date | Milestone |
|---|---|
| 2026-09-15 | Repo scaffolded from the `cmos5l` template; fixed 8N1 UART transmitter (then in `src/`, now the test-only reference `test/uart_tx_ref.v`) with cycle-exact cocotb tests (3/3 passing locally on Icarus) as the warm-up block; local toolchain installed and verified |
| 2026-09-18 | **Core v0 complete and hardened.** ISA (`isa/isa.yaml`) generates the assembler, Python simulator and Verilog decode constants; `pe_core`/`pe_timebase`/`pe_gpio`/`pe_fifo`/`pe_imem_ff` wired to a host SPI loader (`pe_host_spi`) on the Tiny Tapeout pins; differential fuzzer (RTL vs Python model) and a cycle-accurate UART-firmware equivalence test both pass; core properties (deadline exactness, static timing, reset safety, RUN synchronisation) proved with SymbiYosys; hardened for IHP SG13CMOS5L via the GitHub `gds` flow, gate-level simulation green. Next: lanes (pin engines) |

## Results

| Date | Design | Tiles | Std cells (logic / repair+clock) | Std-cell area | Utilisation | Setup WS @ 50 MHz (slow corner) | Hold WS | Route DRC | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 2026-09-15 | warm-up UART TX | 6x4 | 252 (184 / 68) | 3,507 µm² | 0.39 % of 902,417 µm² core | +13.34 ns | +0.128 ns | 0 (after 3 iterations), 0 antenna | Local LibreLane 3.1.0.dev3 on cmos5l; GDS written; run stopped at the final Magic LEF step by a Docker Desktop file-sharing stall (see PLAN.md risks) |
| 2026-09-18 | core v0 (64-word FF instruction memory, host SPI port, no lanes) | 6x4 | 12,757 (9,561 / 3,196) | 193,038 µm² | 21.39 % of 902,417 µm² core | +2.58 ns | +0.117 ns | 0 (after 4 iterations), 0 antenna (8 diodes inserted, 22 antenna cells) | GitHub Actions `gds` run [#35402020440](https://github.com/Abagel-coder/protocol-emulator/actions/runs/35402020440) (commit `f743131`) |

Measured library data from the warm-up run: a reset flip-flop (`sg13cmos5l_dfrbpq_1`) is ~49 µm²; the average cell in that netlist is ~13.8 µm². Details and budget implications in [docs/research/competition-brief.md](docs/research/competition-brief.md). Core v0's std-cell split is 9,561 logic cells (buffers, inverters, the 1,604 `sg13cmos5l_dfrbpq_1` flip-flops, and combinational gates, from the post-synthesis stat report) plus 3,196 cells the place-and-route stages added for timing/hold repair and clock-tree buffering (2,959 timing-repair buffers, 147 clock buffers, 68 clock inverters, 22 antenna cells); routed wirelength 450,841 µm over 12,674 nets, 0 max-cap violations, 109 max-fanout violations (both corners), a `Checker.MaxSlewViolations` warning for max-slew violations in the `nom_slow_1p08V_125C` corner only (the typical and fast corners reported none; the violation count is not in the job log), and 0 LVS/DRC errors from Magic.

## Layout

```
src/        Verilog sources of the chip (list every file in info.yaml and test/Makefile);
            the warm-up fixed-function UART, kept only as the timing reference for
            test/Makefile.uartfw, lives in test/ (test/uart_tx_ref.v) and is never
            synthesised
isa/        isa.yaml — the single source of truth for the ISA; generates the assembler,
            the Python simulator's decode table, src/isa_defs.vh and docs/isa.md
            (tools/gen_isa.py --check pins the enumerations, mnemonic table and the
            reference to it; the field slices in src/pe_core.v are hand-typed and are
            checked against the ISA by the differential fuzzer, test/test_diff.py)
tools/      asm.py (assembler), sim.py (Python reference model), host.py (host SPI
            loader-protocol encoders + cocotb SpiMaster), gen_isa.py, isa_defs.py
tests/      pytest unit tests for tools/ (assembler, generator, simulator)
firmware/   assembly programs (e.g. blink.s) assembled with tools/asm.py
formal/     SymbiYosys proofs (core.sby) for core properties: deadline exactness,
            static timing, reset safety, RUN synchronisation
test/       cocotb testbenches (tb*.v) and tests (test_*.py): Makefile (host/top level, RTL
            or gate-level with GATES=yes), Makefile.core (core + differential fuzzer),
            Makefile.blocks, Makefile.uartfw (RTL only -- their testbenches instantiate
            sub-modules the flattened netlist no longer has)
docs/       datasheet text (info.md), generated ISA reference (isa.md), research,
            design specs
scripts/    setup_env.sh — local toolchain bootstrap for macOS (Apple Silicon)
info.yaml   Tiny Tapeout project metadata and pinout
```

## Working locally

One-time setup (creates `.venv` for project tooling, installs OSS CAD Suite, Tiny Tapeout tools, LibreLane and the pinned IHP PDK under `~/ttsetup`, and writes `env.sh`). cocotb is installed into the OSS CAD Suite's own Python, because the suite's simulators embed that interpreter; it is pinned to the same version the GitHub `test` workflow uses:

```bash
scripts/setup_env.sh
```

Every shell:

```bash
source env.sh
```

Tool tests (assembler, ISA generator, Python simulator) and the generator drift check:

```bash
.venv/bin/pytest -q
.venv/bin/python tools/gen_isa.py --check
```

RTL simulation — host SPI port (`test/Makefile`), core-only with the differential fuzzer (`test/Makefile.core`), timebase/GPIO blocks (`test/Makefile.blocks`), and the UART-firmware equivalence test (`test/Makefile.uartfw`); each line works on its own or pasted as a block:

```bash
make -C test -B
make -C test -B -f Makefile.core
make -C test -B -f Makefile.blocks
make -C test -B -f Makefile.uartfw
```

(`make` exits 0 even when a cocotb test fails; look for `FAIL=0` in the summary table, or grep `results.xml` for `failure` as CI does. `DIFF_PROGRAMS=25 make -C test -B -f Makefile.core` shortens the fuzzer from 200 programs to 25.)

Formal proofs (core properties: deadline exactness, static timing, reset safety, RUN synchronisation):

```bash
cd formal && sby -f core.sby
```

Harden (RTL to GDS) locally — Docker Desktop must be running:

```bash
tt_tool --create-user-config && tt_tool --harden && tt_tool --print-stats
```

Gate-level simulation after hardening:

```bash
cp runs/wokwi/final/pnl/tt_um_abagel_coder_protocol_emulator.pnl.v test/gate_level_netlist.v
cd test && make -B GATES=yes
```

The flow of record is the GitHub `gds` workflow (`TinyTapeout/tt-gds-action@ihp-cmos5l`); local hardening is for iteration.

## What CI runs

Every workflow runs on every push (`.github/workflows/`). What each one actually executes:

- `test` — the four cocotb suites on Icarus (Ubuntu's `iverilog`, cocotb 2.0.1 from `test/requirements.txt`): `test/Makefile` (host/top level, 18 tests), `test/Makefile.core` (14 directed core tests + the 200-program differential fuzzer against `tools/sim.py`), `test/Makefile.blocks` (3), `test/Makefile.uartfw` (1, cycle-exact UART-firmware equivalence); each suite's `results*.xml` is grepped for `failure`.
- `tools` — `pytest -q` (assembler, generator, simulator, host encoders; 39 tests, pyyaml 6.0.3 / pytest 8.4.2 pinned), `tools/gen_isa.py --check` (the three generated files match `isa/isa.yaml`), and all five SymbiYosys tasks of `formal/core.sby` on OSS CAD Suite release 2026-09-15.
- `gds` — hardening with LibreLane via `tt-gds-action@ihp-cmos5l`, the Tiny Tapeout precheck, the gate-level run of `test/Makefile` (`GATES=yes`, host suite only) against the routed netlist, and the GDS viewer.
- `docs` — the datasheet build from `docs/info.md`.

Not run in CI: Verilator lint (`verilator --lint-only -Wall -Wno-DECLFILENAME -Isrc src/*.v --top-module tt_um_abagel_coder_protocol_emulator`, run locally), and local hardening.

## License

Apache-2.0, see [LICENSE](LICENSE).
