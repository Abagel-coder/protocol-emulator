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
| 2026-10-16 | **SRAM instruction memory on branch `sram-imem` (not merged): first complete flow, results not final (superseded by the 2026-10-17 row).** 512 x 16 IHP macro `RM_IHPSG13_1P_512x16_c2_bm_bist` in place of the 64-word flip-flop memory; `WRITE_IMEM` words that arrive while the core is active are dropped and reported in `READ_STATUS` bit 5. GitHub `gds` run [#38841114120](https://github.com/Abagel-coder/protocol-emulator/actions/runs/38841114120) (commit `10a9583`): power grid connected on VPWR and VGND, LVS and antenna checks pass, hold clean, 1 macro + 5,535 standard cells; setup violations in the slow corner and Magic DRC errors around the macro, and the job stopped at the artifact upload (storage quota), so the metrics gate, precheck and gate-level run did not execute. Both are pending owner decisions (HANDOFF.md). The numbers of that run are not in the Results table; the green run is below. |
| 2026-10-17 | **SRAM harden green; merged into `main` the same day (`658d152`).** GitHub `gds` run [#39014059324](https://github.com/Abagel-coder/protocol-emulator/actions/runs/39014059324) on commit `4badf9e` (512 x 16 SRAM macro instruction memory, per-register precompute of the `WAITT` compare, `SYNTH_STRATEGY` "DELAY 4"): the `gds`, `metrics_gate`, `precheck` (KLayout DRC) and `gl_test` jobs pass; slow-corner setup slack +1.91 ns at 50 MHz, hold +0.120 ns, routing DRC 0, antenna 0, LVS 0. The `viewer` job failed because GitHub Pages was unpublished when the repository went public on 2026-10-16 (the owner re-enables Pages). The label "core v1.0" is provisional until the owner names the release; the merge of `sram-imem` is the owner's decision. Results row below. |

## Results

| Date | Design | Tiles | Std cells (logic / repair+clock) | Std-cell area | Utilisation | Setup WS @ 50 MHz (slow corner) | Hold WS | Route DRC | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 2026-09-15 | warm-up UART TX | 6x4 | 252 (184 / 68) | 3,507 µm² | 0.39 % of 902,417 µm² core | +13.34 ns | +0.128 ns | 0 (after 3 iterations), 0 antenna | Local LibreLane 3.1.0.dev3 on cmos5l; GDS written; run stopped at the final Magic LEF step by a Docker Desktop file-sharing stall (see PLAN.md risks) |
| 2026-09-18 | core v0 (64-word FF instruction memory, host SPI port, no lanes) | 6x4 | 12,757 (9,561 / 3,196) | 193,038 µm² | 21.39 % of 902,417 µm² core | +2.58 ns | +0.117 ns | 0 (after 4 iterations), 0 antenna (8 diodes inserted, 22 antenna cells) | GitHub Actions `gds` run [#35402020440](https://github.com/Abagel-coder/protocol-emulator/actions/runs/35402020440) (commit `f743131`) |
| 2026-10-02 | core v0.1 (wrap-safe WAITT, 64-word FF IMEM, no lanes) | 6x4 | 12,561 (9,410 / 3,151) | 192,394 µm² | 21.32 % of 902,417 µm² core | +4.85 ns | +0.123 ns | 0 (re-route after antenna repair: 55, 8, 5, 0 violations per iteration), 0 antenna (9 diodes inserted, 9 antenna cells) | GitHub Actions `gds` run [#37027426422](https://github.com/Abagel-coder/protocol-emulator/actions/runs/37027426422) (commit `ac0e555`); metrics in [tests/data/metrics_core_v01.json](tests/data/metrics_core_v01.json) |
| 2026-10-17 | core v1.0 (512x16 SRAM instruction memory, wrap-safe WAITT, DELAY 4 synthesis, no lanes) | 6x4 | 6,797 (5,527 / 1,270) + 1 macro | 94,717 µm² + 45,309 µm² macro | 15.52 % of 902,417 µm² core (std cells + macro) | +1.91 ns | +0.120 ns | 0 (re-route: 344, 56, 55, 0, 1, 1, 0 violations per iteration), 0 antenna (10 diodes inserted, 20 antenna cells) | GitHub Actions `gds` run [#39014059324](https://github.com/Abagel-coder/protocol-emulator/actions/runs/39014059324) (commit `4badf9e`); metrics saved locally (git-ignored) as `.superpowers/sdd/metrics-4badf9e.json` |

Measured library data from the warm-up run: a reset flip-flop (`sg13cmos5l_dfrbpq_1`) is ~49 µm²; the average cell in that netlist is ~13.8 µm². Details and budget implications in [docs/research/competition-brief.md](docs/research/competition-brief.md). Core v0's std-cell split is 9,561 logic cells (buffers, inverters, the 1,604 `sg13cmos5l_dfrbpq_1` flip-flops, and combinational gates, from the post-synthesis stat report) plus 3,196 cells the place-and-route stages added for timing/hold repair and clock-tree buffering (2,959 timing-repair buffers, 147 clock buffers, 68 clock inverters, 22 antenna cells); routed wirelength 450,841 µm over 12,674 nets, 0 max-cap violations, 109 max-fanout violations (both corners), a `Checker.MaxSlewViolations` warning for max-slew violations in the `nom_slow_1p08V_125C` corner only (the typical and fast corners reported none; the violation count is not in the job log), and 0 LVS/DRC errors from Magic. Core v0.1 (the wrap-safe `WAITT` and the timeout adder moved off the advance path; same 1,604 flip-flops) is 196 cells and 644 µm² smaller than core v0 (12,561 against 12,757 cells; 21.32 % against 21.39 % utilisation). Its split is 9,410 logic cells (from the post-synthesis stat report) plus 3,151 cells added by place-and-route (2,916 timing-repair buffers, of which 1,748 hold buffers, 159 clock buffers, 67 clock inverters, 9 antenna diodes); the routed wirelength is 438,203 µm (`route__wirelength`) over 12,481 nets (`route__net`), with 0 max-cap and 0 max-slew violations in all three corners (`design__max_cap_violation__count`, `design__max_slew_violation__count`; core v0 had a max-slew warning in `nom_slow_1p08V_125C`, this run raised none), 111 max-fanout violations in each corner (`design__max_fanout_violation__count`) and 0 LVS/Magic DRC errors. The setup and hold slacks are read from the run's `metrics.json` (saved unchanged as `tests/data/metrics_core_v01.json`): worst setup slack `timing__setup__ws__corner:nom_slow_1p08V_125C` = +4.848 ns (core v0: +2.58 ns), worst hold slack `timing__hold__ws` = +0.123 ns, which is the `nom_fast_1p32V_m40C` corner (core v0: +0.117 ns). The flow raised only configuration-level warnings (no PnR/signoff SDC files, `VSRC_LOC_FILES` unset, the single 1,605-terminal `clk` net, an unset wire-length threshold, KLayout DRC skipped); no timing, slew, capacitance, antenna, LVS or DRC checker warned.

Core v1.0 (the 512 x 16 IHP SRAM macro `RM_IHPSG13_1P_512x16_c2_bm_bist` as the instruction memory, `pe_imem`; commit `4badf9e`, `gds` run [#39014059324](https://github.com/Abagel-coder/protocol-emulator/actions/runs/39014059324)) places 1 macro (45,309.31 µm²) and 6,797 standard cells (94,717.11 µm², 581 sequential flip-flops, 4,368 multi-input combinational cells, 424 buffers, 154 inverters). The split is 5,527 logic cells (the post-synthesis cell count of 5,528 less the macro) plus 1,270 cells added by place-and-route (1,157 timing-repair buffers, of which 745 are hold buffers, 68 clock buffers, 25 clock inverters, 20 antenna cells); core v0.1 had 12,561 cells, so the standard-cell count is 5,764 lower (the 64-word flip-flop array is gone and the macro holds eight times the words). The utilisation 15.52 % is `design__instance__utilization` = (94,717 + 45,309) µm² over the 902,417 µm² core, and the 62,572 fill cells are not counted. Routed wirelength is 323,585 µm over 6,777 nets (`route__wirelength`, `route__net`); 0 max-slew and 0 max-cap violations in all three corners and 94 max-fanout violations in each (`design__max_fanout_violation__count`); 0 LVS errors. The slacks are read from the run's `metrics.json` and match the `metrics_gate` job log: worst setup slack in the slow corner +1.906 ns, in the typical corner +8.766 ns, worst hold slack +0.120 ns (the `nom_fast_1p32V_m40C` corner).

Timing with the macro took three steps. With the flow's default synthesis (`AREA 0`) at commits `714d81a`/`a850747` the macro's clock-to-output of about 6.3 ns sat inside the fetch loop (`A_DOUT` to decode to the next program counter to `A_ADDR`) and the slow-corner setup slack was -0.740 ns at the 20 ns clock. Two flow experiments with no RTL change moved it: `SYNTH_STRATEGY` "DELAY 1" gave +0.655 ns (run 39007956049) and "DELAY 4" +1.367 ns (run 39007956627). Precomputing the `WAITT` deadline compare and the zero test of every register in parallel and selecting the result after decode (commit `20edbfe`, which takes the 16-bit subtract off the path from the instruction word to the advance signal) together with "DELAY 4" gave +1.906 ns in this run, so the 50 MHz clock stays. The commit after it (`ad51c21`) adds only tests and comments and has the same netlist. The `precheck` job ran KLayout DRC on the submission GDS and passed, and the gate-level simulation `gl_test` job passed (22 of 22 tests). The flow's own Magic DRC step reports 57,923 errors and the `Report Manufacturability` block therefore shows DRC as failed with "KLayout DRC errors: N/A" (the in-flow KLayout DRC step is switched off); Magic DRC is non-fatal by configuration while the macro is present (the layout carries the macro as an abstract view), the count is not broken down here, and the KLayout check in `precheck` is the DRC gate. Magic also reports 5 illegal overlaps (`magic__illegal_overlap__count`, a flow warning). Antenna and LVS pass in the same block. The flow raised the same configuration-level warnings as before and, in addition, the warning that netlists were found for the macro but no parasitics extraction at any corner, so the netlist cannot be used for timing on that module.

## Layout

```
src/        Verilog sources of the chip (list the files of info.yaml `source_files` and the test
            Makefiles); it also holds the synthesis-only blackbox
            RM_IHPSG13_1P_512x16_c2_bm_bist.v and the flow's pdn_cfg.tcl / config.json, which are
            not simulated;
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

- `test` — the four cocotb suites on Icarus (Ubuntu's `iverilog`, cocotb 2.0.1 from `test/requirements.txt`): `test/Makefile` (host/top level, 22 tests), `test/Makefile.core` (19 directed core tests + the 200-program differential fuzzer against `tools/sim.py`, each program tiled 8 times over the 512 words), `test/Makefile.blocks` (7), `test/Makefile.uartfw` (1, cycle-exact UART-firmware equivalence); each suite's `results*.xml` is grepped for `failure`.
- `tools` — `pytest -q` (assembler, generator, simulator, host encoders; 50 tests, pyyaml 6.0.3 / pytest 8.4.2 pinned), `tools/gen_isa.py --check` (the three generated files match `isa/isa.yaml`), and all five SymbiYosys tasks of `formal/core.sby` on OSS CAD Suite release 2026-09-15.
- `gds` — hardening with LibreLane via `tt-gds-action@ihp-cmos5l`, then a metrics gate (`test/check_metrics.py` on `runs/wokwi/final/metrics.json`: worst setup slack in the slow and typical corners, worst hold slack, route DRC errors, antenna-violating nets and LVS errors must be within limits; the Tiny Tapeout flow itself goes green on negative slack), the Tiny Tapeout precheck, the gate-level run of `test/Makefile` (`GATES=yes`, host suite only) against the routed netlist, and the GDS viewer. The gate is its own job (`metrics_gate`, needs `gds`, reads the `GDS_logs` artifact), so a failing gate does not skip the precheck, the gate-level run or the viewer; those jobs need only the `gds` job to pass.
- `docs` — the datasheet build from `docs/info.md`.

Not run in CI: Verilator lint (`verilator --lint-only -Wall -Wno-DECLFILENAME -Isrc src/project.v src/pe_timebase.v src/pe_gpio.v src/pe_imem.v src/pe_fifo.v src/pe_core.v src/pe_host_spi.v src/RM_IHPSG13_1P_512x16_c2_bm_bist.v --top-module tt_um_abagel_coder_protocol_emulator`, run locally: the seven source files plus the SRAM macro's port-only blackbox), and local hardening.

## License

Apache-2.0, see [LICENSE](LICENSE).
