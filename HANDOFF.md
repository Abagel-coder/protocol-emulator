# Handoff — protocol-emulator ASIC (Jane Street / Tiny Tapeout CMOS5L)

Written 2026-09-18, updated 2026-10-17 after plan C (protocol firmware) was implemented. **`main` holds core v0 and core v0.1 (merged 2026-10-15, `ac0e555`). The SRAM instruction memory is on branch `sram-imem`: the code is complete and reviewed, the flow completes in CI, and the branch is NOT merged. Plan C (UART receiver, SPI master modes 0-3, I2C master firmware with spec-derived reference models) is on branch `protocol-fw`, off `sram-imem` at `a850747`, implemented, reviewed task by task and as a whole branch, with the final review's fixes applied (2026-10-17), also NOT merged and with no RTL change. Nothing has been merged since 2026-10-15; the merge order (`sram-imem` first, then `protocol-fw`) and the open decisions below are the owner's. Do not merge without the owner's say-so.**

## Paste this into the new session

> Continue the protocol-emulator ASIC project in this folder. Read `HANDOFF.md` first, then `PLAN.md`. Branch `sram-imem` (512 x 16 SRAM instruction memory) is reviewed and its flow completes in CI, but two things block the green run: the GitHub artifact quota and negative slow-corner setup slack. Check "What is left" for the open owner decisions, ask which have been answered, then apply the answers (Task 4's README results row needs a green `gds` run). Plan C (required protocols) is implemented on branch `protocol-fw`, its whole-branch review and fix wave are done, and it waits for the owner: ask about the merge order in "What is left", then merge `sram-imem` first, merge or re-base `protocol-fw` onto it (README conflict resolution below) and re-run the three protocol suites on the merged tree. Run at most two agents, only one of them committing, tell each to do the work itself in the foreground, and free memory on this Mac first (see "Environment").

## Where everything is

| What | Path |
|---|---|
| Competition plan, timeline, decision log, risks | `PLAN.md` |
| Approved architecture (v1) | `docs/superpowers/specs/2026-09-15-protocol-emulator-design.md` |
| Implementation plans executed | `docs/superpowers/plans/2026-09-16-core-v0.md` (core v0, 10 tasks), `docs/superpowers/plans/2026-10-15-sram-imem.md` (SRAM, 4 tasks; Task 4 = docs and results row, open), `docs/superpowers/plans/2026-10-16-protocol-firmware.md` (plan C, 4 tasks, on branch `protocol-fw` only) |
| SRAM instruction-memory design | `docs/superpowers/specs/2026-10-15-sram-imem-design.md` |
| Plan C design (pin map, model interface, protocol semantics, tolerances; branch `protocol-fw`) | `docs/superpowers/specs/2026-10-16-protocol-firmware-design.md` |
| Research: brief, prior art, verification, novelty decisions N1–N10 | `docs/research/` |
| ISA source of truth and generated reference | `isa/isa.yaml`, `docs/isa.md` |
| Tools: generator, assembler, cycle-accurate oracle, host encoders | `tools/gen_isa.py`, `tools/asm.py`, `tools/sim.py`, `tools/host.py` |
| RTL | `src/project.v` (top), `src/pe_core.v`, `pe_gpio.v`, `pe_timebase.v`, `pe_fifo.v`, `pe_host_spi.v` and `src/pe_imem.v` (exactly `info.yaml`'s `source_files`). `pe_imem.v` has two builds selected by `IMPL`: `MACRO` (the chip: one IHP `RM_IHPSG13_1P_512x16_c2_bm_bist` single-port SRAM) and `FLOPS` (a 512 x 16 flip-flop array for simulation and FPGA only, not a chip fallback at 512 words) |
| SRAM macro blackbox | `src/RM_IHPSG13_1P_512x16_c2_bm_bist.v`: port-only view for synthesis. Not a source file: the flow places the macro, and `src/config.json` names its instance and position |
| Power grid | `src/pdn_cfg.tcl`: Loom's pdngen wrapper (Apache-2.0, attributed in its header, commit-pinned) that runs the aligned Metal4 stripes through the macro's supply columns and checks it; `src/config.json` holds the stripe-grid parameters, the macro's instance name (`u_imem.g_macro.u_sram`), its placement and `CLOCK_PERIOD` (20 ns today) |
| SRAM simulation models | `test/models/` (the IHP behavioural macro, vendored, unmodified, `-DFUNCTIONAL`; why they are needed is in `test/models/README.md`) |
| Metrics gate | `test/check_metrics.py` (run by the `gds` workflow on `runs/wokwi/final/metrics.json`: setup slack in the slow and typical corners, hold slack, route DRC, antenna, LVS) and its tests `tests/test_check_metrics.py`; the saved core v0.1 `metrics.json` is `tests/data/metrics_core_v01.json` |
| Simulation backdoor for the instruction memory | `test/imem_load.py`: deposits a program straight into the behavioural macro's array (RTL simulations without a host; unwritten words set to 0 so the core never fetches X). Over SPI, `tools/host.py` `encode_write_imem` builds the `WRITE_IMEM` stream |
| Test-only UART timing reference | `test/uart_tx_ref.v` |
| Firmware | `firmware/blink.s`, `firmware/uart_tx.s`; on `protocol-fw`: `firmware/uart_rx.s` (36 words), `firmware/spi_master.s` (71), `firmware/i2c_master.s` (167); each file has one `.equ` block (`PRESCALE` and every timing constant, with formulas) and its datasheet section is "Protocol firmware" in `docs/info.md` |
| Reference models (`protocol-fw`) | `tools/refmodels/uart_rx_ref.py`, `spi_slave_ref.py`, `i2c_slave_ref.py`: cycle-stepped, `step(uo, uio_out, uio_oe) -> (ui, uio_in)`, a `violations` list, written from the protocol definitions with tolerances from protocol parameters and `CLK_HZ`, never from the firmware |
| Firmware harnesses (`protocol-fw`) | `tests/fw_harness.py` (oracle: `load`, `run_model`; the firmware on `tools/sim.py` with the two-cycle input latency), `test/fw_harness.py` (RTL: `PinBus`, `HostPort`, `boot`, `run_model`, `drain`, `host_push`, `status`: the whole chip through its pins with the host SPI port); oracle tests and case tables in `tests/test_fw_uart_rx.py`, `test_fw_spi.py`, `test_fw_i2c.py` (the cocotb modules import them); `tools/asm.py` `constants()` reads a firmware's `.equ` table |
| Tests | `tests/` (pytest), `test/` (cocotb: `Makefile` = host/top level, `Makefile.core`, `Makefile.blocks`, `Makefile.uartfw`, and on `protocol-fw` `Makefile.uartrx`, `Makefile.spifw`, `Makefile.i2cfw`; the three protocol suites build in `sim_build/uartrx`, `spifw`, `i2cfw`) |
| Formal proofs and their honest scope | `formal/core.sby`, `formal/core_props.v`, `formal/timebase_props.v`, `formal/README.md` |
| Toolchain bootstrap | `scripts/setup_env.sh` (writes `env.sh`, git-ignored) |
| Per-task briefs, reports, review diffs, progress ledger (**local only, git-ignored**) | `.superpowers/sdd/` (SRAM: `sram-task-N-brief.md`, `sram-task-N-report.md`, `sram-final-review.md`, `sram-final-rereview.md`; plan C, in the `protocol-fw` worktree `.claude/worktrees/agitated-hamilton-5fbcad/.superpowers/sdd/`: `pc-task-N-brief.md`, `pc-task-N-report.md` (mutation tables, measured figures, deviations), `pc-task-N-review.md`, `pc-task-N-rereview.md`, `review-<from>..<to>.diff`; Task 4's report has the measured suite table); CI logs are saved there when downloaded (`gds-ac0e555.log`, `gds-10a9583.log`; the log of `714d81a` was not saved) |
| GitHub | https://github.com/Abagel-coder/protocol-emulator (**private**; Pages enabled) |

## State

- Branch `sram-imem`: the commit that carries this handoff update (`git log -1`) sits on `41ac372` (RTL, tools, tests and flow files are unchanged by it; it edits documents and one comment in `src/pdn_cfg.tcl`). `origin/sram-imem` was last pushed at `10a9583`; check `git status -sb` for what is still local. `main` is at `ac0e555` (core v0.1, merged 2026-10-15 by fast-forward; CI on it green on all four workflows).
- The SRAM work: design `docs/superpowers/specs/2026-10-15-sram-imem-design.md`, plan `docs/superpowers/plans/2026-10-15-sram-imem.md`. Tasks 1-3 (the `pe_imem` block, the chip integration with 512-word tools and tests and `READ_STATUS` bit 5, the flow configuration and metrics gate) are implemented, each reviewed with mutation checks; the whole-branch review and its fix wave are approved (reports `.superpowers/sdd/sram-*.md`, local only). Task 4 (this handoff, the README results row once a green run exists) is the open one.
- Local suites at `41ac372` (2026-10-16): host 22, core 20 (19 directed + the 200-program differential fuzzer, each program tiled 8 times over the 512 words), blocks 7, UART firmware equivalence 1, pytest 50, Verilator lint clean, `formal/core.sby` five tasks pass (sby 5/5), `tools/gen_isa.py --check` clean.
- GitHub Actions on `sram-imem`: the `test` and `docs` workflows failed on `714d81a` only at the artifact upload ("Artifact storage quota has been hit"; every test step was green); the `gds` workflow is the subject of the section below. After the quota failure the controller deleted 42 artifacts (GDS_logs, gds_render, tt_submission; 1.68 GB) from 14 intermediate runs and later the bundle of the main-merge run 36945175253; the bundles of the runs of record 35402020440 (core v0) and 37027426422 (core v0.1) were kept.

- Branch `protocol-fw` (plan C): off `sram-imem` at `a850747`; the commit that carries this handoff is `git log -1`. Commits: `c5f55ee` spec, `31ad76b` plan, `cce2fd3` Task 1 (UART RX and the shared harnesses), `ea5034b` Task 1 fix, `71283fa` Task 2 (SPI master), `61f2487` docs, `e86c170` Task 2 fix, `c98f5ae` docs, `2d435cb` Task 3 (I2C master), `008cf7f` Task 3 fix, `b55d499` docs (Task 4), `15b1406` final-review fixes (I2C `TRISE` stretch detection, model `rise_cycles` and the `rise_time` case, UART break case, CI result-file checks), then this documentation commit. Nothing is merged and nothing was pushed except the branch itself (first push 2026-10-17 04:47 UTC). `git diff a850747 HEAD -- src isa formal tools/sim.py tools/host.py` is empty: only `tools/asm.py` (`constants()`), new files, documents and `.github/workflows/test.yaml` (three new steps) differ. **The base has moved.** `sram-imem` is now at `4badf9e` and beyond: `ea630e2` (metrics gate as its own job), `147e69b` (fetch-loop timing plan), `20edbfe` (`pe_core.v` precomputed `WAITT` compare), `4badf9e` (`SYNTH_STRATEGY` DELAY 4), then `ad51c21` (a directed `WAITT R0` core test, oracle and RTL, and a `pe_core.v` comment; the local `sram-imem` ref) and `658d152` (`origin/sram-imem`, documents only: the green hardening run 39014059324 on `4badf9e`, slow-corner setup +1.91 ns at 50 MHz, precheck and gl_test green). So `protocol-fw` must be re-based or merged onto it and the three protocol suites re-run after that RTL change. `git merge-tree` of `sram-imem` at `ad51c21` with `15b1406` shows one conflict, `README.md` "What CI runs": take `protocol-fw`'s `test`/`tools` bullets and `sram-imem`'s `gds` bullet. Against `658d152` (and with this documentation commit) `HANDOFF.md` and `PLAN.md` conflict as well: keep `sram-imem`'s hardening sections and status, and add `protocol-fw`'s plan C bullets, mutant table and minors. Trial run of that merge (the `ad51c21` + `15b1406` tree, extracted to a scratch directory, 2026-10-17): pytest 140 passed, `Makefile.i2cfw` 12/12, `Makefile.uartrx` 9/9, `Makefile.spifw` 8/8, `Makefile.core` 21/21, 0 warnings; after the merge the CI count check for `results_core.xml` must be 21 (the new directed test), not 20. The merge order remains `sram-imem` first, then `protocol-fw`; the owner's call.
- Local suites on `protocol-fw` (2026-10-17, measured after the final-review fixes, commands in `.superpowers/sdd/pc-final-fix-report.md`): host 22, core 20, blocks 7, UART TX firmware equivalence 1, UART RX firmware 9, SPI master firmware 8, I2C master firmware 12 (seven cocotb suites, 79 tests, all pass with 0 warnings), pytest 138, `tools/gen_isa.py --check` clean. Wall-clock (the machine was swapping, 5.2 GB): host 18 s, core 58 s, blocks 2 s, uartfw 6 s, uartrx 59 s, spifw 43 s, i2cfw 66 s (the same uartrx suite took 921 s on the trial-merge copy under heavier swap). Verilator lint and `formal/core.sby` were not re-run (no RTL change; last run at `41ac372`).
- GitHub Actions on `protocol-fw`, pushed head `008cf7f` (first push, 2026-10-17 04:47 UTC): `test` run 39003870786 success with all seven suite steps green, `tools` run 39003870830 success, `docs` success. The `gds` run 39003870770 on `protocol-fw` `008cf7f` FAILED at the "Metrics gate" step (slow-corner setup; precheck, gl_test and viewer skipped), the same as `sram-imem`'s run 38988882606 on `a850747` -- the RTL was identical. The fix is `sram-imem`'s (`20edbfe`, `4badf9e`), which `protocol-fw` picks up at the merge. `15b1406` and this commit are not pushed.

### Core v0 hardening result (GitHub `gds` run 35402020440, commit `f743131`)

| Metric | Value |
|---|---|
| Standard cells | 12,757 (9,561 logic, 3,196 timing-repair and clock) |
| Standard-cell area | 193,038 µm² |
| Utilisation of the 6x4 core | 21.39 % |
| Setup slack @ 50 MHz, slow corner | +2.58 ns |
| Hold slack | +0.117 ns |
| Routing DRC / antenna violations | 0 / 0 |

Implications: the design is bigger than the 7–8K-cell estimate, mainly the 64-word flip-flop instruction memory, so the SRAM macro matters; setup slack is fine but not generous, so lanes need timing care.

### Core v0.1 hardening result (GitHub `gds` run 37027426422, commit `ac0e555`, branch `core-v0.1`, all jobs green)

Source: the job log (`.superpowers/sdd/gds-ac0e555.log`, git-ignored) and the run's `metrics.json`, saved unchanged as `tests/data/metrics_core_v01.json` (metric key in brackets).

| Metric | Value (core v0 in brackets) |
|---|---|
| Standard cells | 12,561 (9,410 logic, 3,151 timing-repair, clock and antenna) [12,757 (9,561, 3,196)] |
| Standard-cell area | 192,394 µm² (`design__instance__area__stdcell`) [193,038 µm²] |
| Utilisation of the 6x4 core | 21.32 % (`design__instance__utilization`) [21.39 %] |
| Setup slack @ 50 MHz, slow corner | +4.848 ns (`timing__setup__ws__corner:nom_slow_1p08V_125C`) [+2.58 ns] |
| Hold slack (worst corner, fast) | +0.123 ns (`timing__hold__ws`) [+0.117 ns] |
| Routing DRC / antenna violations | 0 / 0 (`route__drc_errors`, `antenna__violating__nets`) |
| LVS / Magic DRC | 0 / 0 (`design__lvs_error__count`, `magic__drc_error__count`) |
| Max slew / max cap / max fanout violations | 0 / 0 / 111 per corner [core v0: a max-slew warning in the slow corner, 109 max-fanout] |

Core v0.1 is 196 cells smaller than core v0 and its worst setup slack is 2.27 ns higher (4.848 against 2.58 ns). The slack numbers come from `metrics.json`; the run summary is not needed.

### Core v1 hardening (SRAM) status: GitHub `gds` runs on `sram-imem`

Core v0.1 had 12,561 standard cells and no macro. Two runs so far (both stopped by the artifact quota, not by the flow):

| | Harden 1: run 38838496042, commit `714d81a` | Harden 2: run [38841114120](https://github.com/Abagel-coder/protocol-emulator/actions/runs/38841114120), commit `10a9583`, 59 min |
|---|---|---|
| Flow | macro placed, `CheckMacroInstances` passed, routed in 21 min, then stopped at `OpenROAD.IRDropReport` | complete, to `ReportManufacturability` |
| Cells | 4,262 including the macro | 1 macro + 5,535 standard cells: 568 sequential, 3,450 combinational, 1,174 timing-repair buffers, 73 clock buffers, 27 clock inverters, 242 inverters, 1 buffer |
| PDN | PSM-0069 on VPWR and VGND: the macro's `VDD!`/`VSS!` unconnected (stripes cut around the macro) | Loom's pdngen wrapper checks pass; PSM-0040 all shapes connected on VPWR and VGND |
| LVS | not reached | pass |
| Antenna | not reached | pass (4 diodes) |
| Setup | not reached | `Checker.SetupViolations`: violations in `nom_slow_1p08V_125C`; the post-PnR table lists 91 violating endpoints; the slack value is in the run's step summary, not the job log |
| Hold | not reached | clean |
| Max slew / max cap | not reached | max-slew violations in the slow corner / max-cap clean |
| Magic DRC | not reached | 57,923 errors (non-fatal by configuration while the macro is present; the precheck's KLayout DRC is the real DRC gate and did not run) |
| Job result | failed at IRDropReport | failed only at the artifact upload (quota), so the metrics gate, precheck, `gl_test` and the viewer were skipped |

The fix between the runs was `10a9583` (adopt Loom's pdngen wrapper in `src/pdn_cfg.tcl`; Apache-2.0, attributed): the first file was LibreLane's default minus the macro grid, which left the Metal4 stripes short of the macro. The standard-cell count is 5,535 plus the macro, against 12,561 cells for core v0.1 (the 64-word flip-flop memory is gone and the macro holds eight times the words). The timing cause is the macro's clock-to-output of about 6.3 ns inside the fetch loop (`A_DOUT` -> decode -> `next_pc` -> `A_ADDR`) at the 20 ns clock. None of these numbers are in `README.md`'s Results table: there is no complete run to quote. Logs: `.superpowers/sdd/gds-10a9583.log` is saved; `gds-714d81a.log` is not.

### Plan C: reference models and the mutants that show they are decisive

Each protocol's firmware passes its cases on the oracle and the RTL, and the suites (and the oracle tests) fail on firmware mutants applied to the source text in memory; one sentinel per protocol is a test in the cocotb suite itself, the rest are oracle tests or were run by the task agents and the reviewers with scratch scripts (decisive lines in the task reports). Cases in brackets are the ones that kill the mutant.

| Protocol | Mutants and the check that kills them |
|---|---|
| UART RX (`test/Makefile.uartrx`, `tests/test_fw_uart_rx.py`) | U1 `BIT` 210 (sentinel, in the cocotb suite; also every probe frame); U2 `HALF` 160 (probe frames); U3 false-start check removed (glitch); U4 bit order (nominal); U5 framing flag never set (framing); U6 `PRESCALE` 0 (nominal); U7 stop bit sampled at +HALF (nominal); U-new idle wait removed (break: six words instead of two, oracle test `test_uart_rx_break_fails_without_the_idle_wait`, and on the RTL). The review's finding that a falling-edge wait misses a start bit arriving while the timed wait rearms led to the level-wait design; the regression scan at gaps 130,870-130,873 (oracle) fails on the old text at 130,871 and 130,872 |
| SPI master (`test/Makefile.spifw`, `tests/test_fw_spi.py`) | S1 `HALF` 27 (sentinel; edge-to-edge interval check); S2 CPHA and CPOL masks swapped (modes 1 and 2); S3 CPOL ignored (the idle check, modes 2 and 3); S4 LSB first (every case, after the palindromic case bytes were replaced); S5 `CSLEAD` 2 (lead); S6 MISO sampled on the shifting edge (window); S7 final CPHA=0 toggle removed (modes 0 and 2); CS_n never rises (`finish()`); the bare `WAITF` that lost a result word (full-FIFO test) |
| I2C master (`test/Makefile.i2cfw`, `tests/test_fw_i2c.py`) | I1 `Q` 96 (sentinel; tHD;STA, tLOW and period); I2 SDA set after the SCL release (data-valid rule); I3 tHD;STA removed; I4 stretching ignored (stretch and timeout cases); I5 ACK not sampled (addr_nack, data_nack); I6 tSU;STO removed; I7 STRETCHED never set (stretch); the stale result word on a START timeout (start_timeout); an abort that pulls SCL low (the SCL-release check); sampling in the low phase or after the fall (the slave drives the complement until tVD;DAT); sticky STRETCHED (the third word of stretch); TXE retry removed (full-FIFO test); the pre-fix single SCL read-back five cycles after the release (`DELAY 3` / `BPIN`), which set STRETCHED on every result at a 3-cycle (60 ns) rise (`test_i2c_master_single_readback_flags_a_rise_as_a_stretch`; every oracle case runs at rise 0 and 3, `rise_time` at 50) |

## What is left (in order)

1. **Owner decisions** (all open; the code documents the current choice):
   1. **Artifact quota.** The repository is private and the free quota is 500 MB; each `gds` run adds about 130 MB, and GitHub's accounting lagged the deletions by hours (294 MB stored still hit the quota). Make the repository public (the competition requires open source, and public repositories have no artifact quota) or set an Actions spending limit above zero. Until then every run that reaches an upload fails and the metrics gate, precheck, `gl_test` and viewer are skipped.
   2. **Timing.** Decided: the owner decided on 2026-10-16 to keep 50 MHz (recorded in `sram-imem`'s plan commit 147e69b), so no retargeting is planned; the core change is on `sram-imem` (`20edbfe`, `4badf9e`). Retargeting a firmware to another clock means editing its `.equ` block (values and formulas), `CLK_HZ` in its oracle test module (`tests/test_fw_uart_rx.py`, `tests/test_fw_spi.py`, `tests/test_fw_i2c.py`, which the cocotb suites import), the sentinel mutant text (`MUTANT_BIT`, `MUTANT_HALF`, `MUTANT_Q`, re-chosen so the mutant stays outside the tolerance), the 50 MHz literals in the model self-tests, the measured figures in `docs/info.md`, and `clock_hz` in `info.yaml`; the models and their tolerances follow from `CLK_HZ`.
   3. **Release label.** `src/project.v` calls the SRAM build "core v1", which collides with "spec v1"; the owner names the release.
   4. **Merge of `sram-imem`** into `main`, after 1 and 2 and a green run.
2. **Task 4 of the SRAM plan:** once one `gds` run is green end to end (metrics gate, precheck, `gl_test`), add the README results row from that run's `metrics.json` (save it unchanged under `tests/data/`, as was done for core v0.1), and delete the superseded run bundles to stay under the quota.
3. **Plan C merge.** The three required protocols are implemented on `protocol-fw` (UART RX, SPI master modes 0-3, I2C master, each with a spec-derived reference model); the whole-branch review (`.superpowers/sdd/pc-final-review.md`) and its fix wave (`15b1406`, report `pc-final-fix-report.md`) are done. The merge order remains `sram-imem` first, then `protocol-fw`, the owner's call; after the merge, set the CI core count to 21 and re-run the three protocol suites on the merged tree (a trial merge passed, see "State"). The release-label decision is unchanged by plan C. Schedule: required-protocol freeze Nov 8 (`PLAN.md` section 3).

### Minor findings logged during task reviews (triaged in the whole-branch review)

- **Plan C (`protocol-fw`), final-review minors deferred** (fixed in `15b1406` and the documentation commit: the `DELAY 3` margin, now the `TRISE` wait; the late-sampler wording; R4's low byte at `nostart`; host-misuse note; CI result-file checks; the SPI `HALF 26` note):
  - `HOST_PUSH_CYCLES` duplicated in the two cocotb modules (`test/test_spi_fw.py`, `test/test_i2c_fw.py`), and the exact-H edge check in both SPI harnesses.
  - I2C: bit-level stretching untested (the model stretches once, after an ACK bit); START/STOP decoded only between bytes; `case_errors` reads `ks[0]` unguarded; mutant B's kill relies on `T_SLAVE = 0`.
  - UART: `REARM_OLD` matches a firmware comment; the last probe frame has no gap rule.
  - SPI: the one-sided MISO window's late side is reached only by model tests; CPOL settles one cycle before CS_n falls.

(`pe_imem_ff` was replaced by `pe_imem` on `sram-imem`, so the `pe_imem_ff` `WORDS`/`AW` items below no longer apply there; the instruction-memory array is still uninitialised on silicon.)

Status after the fix wave (2026-09-22): fixed -- unused `importlib`; assembler dead code / `max_pc` / `.equ`-`.org`-`.word` error wrapping; `reserved_alu_fn_is_noop` (now rs != rd, checks C); stale HALT comment; post-reset assertion and `running` bit; `sim.py` prescale docstring; `w_rt` decode pinned formally; `IN`/PUSH/POP/CALL/RET/IRQ/WAITL/zero-timeout semantics documented. Deferred to the next plan (owner decisions): `pull_request` trigger (all workflows are push-only by convention); `pe_gpio` OE-clear / pin 7 / `tick` block tests; `alu_valid` comment; `pe_imem_ff` `WORDS = 1 << AW`; `h2c_full` gate; `imem_waddr` increment placement; CS_n hold wording; `cs_start` wire; fuzzer `pc` compare; `uart_tx.s` idle-segment check. (The `t_in + tmo` adder on the critical path was taken off it on `core-v0.1`.)

- `tests/test_gen_isa.py`: unused `importlib` import. `.github/workflows/tools.yaml`: no `pull_request` trigger.
- `tools/asm.py`: dead pass-2 address-collision check and unused `max_pc`; `.equ` error wrapping inconsistent with the rest.
- `isa/isa.yaml` semantics do not define the `WAITF`/`BFLAG` flag-id mapping (RXV=0, TXE=1, TO=2).
- `pe_gpio`: no test for the OE-clear path or `pin_idx==7` on the `uo` bank; `tick` never asserted directly.
- `pe_core`: `reserved_alu_fn_is_noop` does not check C; stale HALT comment in `pin_bank_field_truthiness`; `alu_valid` magnitude compare duplicates the `case` default; `pe_imem_ff` `WORDS`/`AW` not cross-checked; instruction-memory and FIFO arrays are uninitialised (host must load before RUN).
- `pe_host_spi`: `h2c_full` gate is redundant with `pe_fifo` and untested; READ_GPIO's synchronised wiring is not distinguishable by the test; no top-level post-reset assertion (`uio_oe`, `uo_out`, MISO idle) since `test/test.py` was removed; `imem_waddr` increment still inside the `cs_act` guard; CS_n hold comment should say "at least one core clock"; dead `cs_start` wire.
- `tools/sim.py` `prescale` is the divisor; the RTL register is divisor − 1 (naming trap).
- Differential fuzzer: per-cycle compare does not assert `pc`; pin-freeze probability 0.85 tuned empirically; the 66,000-cycle wrap test adds about 3 s.
- `firmware/uart_tx.s`: comment why the idle-high block needs a 4-cycle ADDT→pin-write offset while the start bit needs 1; include the idle segment in the RTL edge-spacing check.
- Formal: the WAIT `rt` field decode is now pinned on the port bits (T1b/P4, final fix wave); the other field slices in `pe_core.v` are hand-typed and checked only by the differential fuzzer. The 65,536-tick wait bound is still an argument composed from proved lemmas (now including the "stalled wait keeps `wait_active`" lemma P3 and the deadline-capture lemma P4), with its three environment hypotheses listed in `formal/README.md`.

## Contracts a newcomer must not get wrong

- `active = run_q && !halted && !core_reset`; `run_q` is `run` delayed one cycle; the RUN pin goes through the two-flop input synchroniser first (three cycles pin → first instruction). `core_reset` suppresses all side effects in its own cycle.
- One branch delay slot; every non-wait instruction is exactly one cycle; pin writes are visible from the next cycle; every wait except `WAITT` has a timeout (`Rt = R0` means 65535 ticks).
- The chip's timebase `T` free-runs from reset and never pauses; firmware must use `SETT`/`ADDT` relative deadlines. Only `test/tb_core.v` gates `T` (to align with the oracle's `t0 = 0`).
- `uo[7]` is MISO and never writable by firmware; `ui[7:4]` are host lines and read as 0 to firmware.
- Host SPI: mode 0, MSB first, SCK ≤ clk/16, commands 0x01–0x07 (table in `docs/info.md`); status bit4 = host→core FIFO full.
- `Sim.step()` returns `(cycle, uo, uio_out, uio_oe, halted)`.
- Firmware reads the synchronised inputs two cycles late (`test/test_diff.py`'s convention: a level driven on the pins in cycle k reaches the core in cycle k+2, and an `IN` sees the pin as it was about two cycles before). The reference models are fed accordingly: the oracle harness (`tests/fw_harness.py`) applies the model's levels two cycles late, the RTL harness drives the pins and the chip does the rest. Protocol firmware keeps every timing number in one `.equ` block and uses `SETT`/`ADDT` relative deadlines, re-anchored after every host `POP`; the models and tests take timing from the protocol and `CLK_HZ`, and the tests read only `PRESCALE` from the firmware.
- Generated files (`docs/isa.md`, `tools/isa_defs.py`, `src/isa_defs.vh`) change only via `isa/isa.yaml` + `.venv/bin/python tools/gen_isa.py`; CI fails on drift of those three. The field slices in `src/pe_core.v` are hand-typed and are checked only by the differential fuzzer.
- The instruction memory is 512 words, one IHP SRAM macro on the chip (the `FLOPS` build is simulation/FPGA only). Addresses and jump targets alias modulo 512 (`WRITE_IMEM` takes the low 9 bits of its 10-bit address field); the assembler refuses programs larger than 512 words; the macro has no reset, so load all 512 words (zero-fill) before RUN. Its single port is shared with the core's fetch: a `WRITE_IMEM` word that arrives while the core is active (running, including stalled in a wait) is **dropped**, not queued, and sets `READ_STATUS` bit 5 until the next `WRITE_CTRL` reset; pause (RUN low and `WRITE_CTRL` run=0) or halt the core before loading. Caveat, the RUN-pin race: a word accepted in the last inactive cycle (RUN rising during a load) leaves a stale word in `ir` for one cycle, and the word under a stalled `pc` can change; keep RUN low while loading (`formal/README.md` hypothesis H3 is narrowed to exactly this). `WAITT` is wrap-safe (core v0.1): it completes once bit 15 of `T - Rn` is 0 -- a deadline up to 32,768 ticks ahead releases exactly at `T == Rn`, one already passed (up to 32,767 behind) at once, flags untouched; keep deadlines under 32,768 ticks ahead. Timed waits keep the equality compare on the `T + timeout` they capture when they start, so a timeout that passes while RUN is low waits for `T` to come round again (`docs/info.md`).

## Environment on this Mac

```bash
source env.sh                      # every shell: OSS CAD Suite, venvs, PDK_ROOT, tt_tool
.venv/bin/pytest -q                # tools
make -C test -B                    # host/top-level cocotb
make -C test -B -f Makefile.core   # core directed tests + differential fuzzer (DIFF_PROGRAMS=25 to shorten)
make -C test -B -f Makefile.blocks
make -C test -B -f Makefile.uartfw
make -C test -B -f Makefile.uartrx # protocol-fw: UART receiver firmware
make -C test -B -f Makefile.spifw  # protocol-fw: SPI master firmware (modes 0-3)
make -C test -B -f Makefile.i2cfw  # protocol-fw: I2C master firmware; CI's test workflow runs all seven (README "What CI runs")
verilator --lint-only -Wall -Wno-DECLFILENAME -Isrc src/*.v --top-module tt_um_abagel_coder_protocol_emulator
cd formal && sby -f core.sby       # all five tasks
```

- If `env.sh` is missing: `scripts/setup_env.sh --skip-brew` (Homebrew at `/usr/local` has an unwritable directory; the step is optional).
- cocotb runs from the OSS CAD Suite's own Python (pinned to 2.0.1); the project `.venv` holds pytest and pyyaml only.
- **This Mac runs out of memory under review workloads** (16 GB; 2026-09-22: 5.4 GB swap used, agents stalled every 10 minutes, cocotb suites 100× slower). Before a long session quit Docker Desktop and any idle servers from other projects; check `sysctl vm.swapusage`.
- **Local hardening is unreliable**: Docker Desktop's file sharing stalls and kills the engine during heavy I/O (VM memory was raised to 12 GB; a backup of Docker's settings file sits beside it). Treat the GitHub `gds` workflow as the flow of record.
- Libraries go into virtual environments or `~/ttsetup`, never system-wide (owner's standing preference).

## Lessons about running subagents

- Several agents died when they handed work to a background worker or ended their turn "waiting for a monitor". Tell every agent: do all the work yourself, run long commands in the foreground with a time limit, never wait on notifications.
- Interrupted agents leave uncommitted partial work. On resume, check `git status` and the ledger before re-dispatching, and tell the next agent to treat the working tree as unverified.
- Reviews with mutation testing found real gaps every time (inert tests, surviving mutants in the formal properties). Keep asking reviewers to prove a test or property fails when the fix is reverted.
- Big agents stall when the machine swaps; make every agent write its report file incrementally and commit per group, so a stalled agent can be resumed (SendMessage to its id) or its work finished by hand. Run at most two agents at a time on this Mac (the SRAM work used two when swap was 3.7 GB; earlier sessions stalled when the machine swapped), and only one of them commits: a second agent writes files only and the controller commits, because two agents committing in one working tree swept a staged `git rm` into the wrong commit on 2026-10-15.
- **GitHub artifact quota (private repository, 500 MB free).** Every `gds` run uploads `GDS_logs`, `gds_render` and `tt_submission` (about 130 MB per run); the `test` and `docs` jobs fail at their own upload once the quota is hit even though every test step passed, and a failed gds upload skips the metrics gate, precheck, `gl_test` and viewer. GitHub's usage figure lags deletions by hours. Delete superseded bundles as you go (`gh api repos/Abagel-coder/protocol-emulator/actions/artifacts` lists them, `gh api -X DELETE repos/Abagel-coder/protocol-emulator/actions/artifacts/<id>` removes one) and KEEP the artifacts of the runs of record: 35402020440 (core v0) and 37027426422 (core v0.1). The run of the main merge (36945175253) was identical RTL to core v0 and its bundle is already deleted. Making the repository public removes the quota (owner decision 1).
- A push cancels the `gds` run in progress on the same branch (`cancel-in-progress`); do not push while a run you want is still going. A docs-only commit can carry `[skip ci]`.

## After the SRAM branch: next plans (not written yet)

1. **Lanes (pin engines)**: shift + fractional divider, NRZ → CRC-32 → NRZI/bit-stuffing (USB) → edge-timestamp FIFO → Manchester; start-at-deadline (`LARM`); contention monitors in the GPIO block. Decisions N2–N6 in `docs/research/novelty-synthesis.md`.
2. **Protocol firmware + reference models (plan C)**: UART RX, SPI master (modes 0-3) and I2C master are done on `protocol-fw` (awaiting review and merge); SPI slave, I2C slave, then USB low speed and 10BASE-T are not started.
3. **Verification depth**: MCY mutation score, EQY RTL-vs-netlist equivalence, cocotb-coverage crosses, microcotb replay on the FPGA board, measured AI-assisted property drafting.
4. **Generate field-slice macros** into `src/isa_defs.vh` (e.g. `ISA_BPIN_LEVEL_MSB/LSB`) and use them in `pe_core.v`, so `gen_isa.py --check` really pins the layout (today only the fuzzer does); also generate the class-count sentence in `docs/info.md`.
5. **Owner decisions carried over:** the four open SRAM decisions under "What is left". (Decided 2026-10-01, branch `core-v0.1`: the wrap-safe `WAITT` deadline compare per spec §6, with the `t_in + tmo` adder moved off the `adv` critical path; the UART timing reference moved from `src/` to `test/uart_tx_ref.v`. Decided 2026-10-15: `core-v0` and `core-v0.1` merged into `main`.)

The README-as-evidence-ledger plan (plan A) and plan C are scheduled in `PLAN.md` section 3.

## Owner-side items

- Sign-up form: done. FPGA kit: ordered, owner will say when it arrives. Team (D2): deferred.
- Schedule: `PLAN.md` compressed timeline; required-protocol freeze re-planned to 2026-11-08 (hard stop 2026-11-23); submission deadline 2027-01-18 (aim for 2027-01-15).
