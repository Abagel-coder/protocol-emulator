# Handoff — protocol-emulator ASIC (Jane Street / Tiny Tapeout CMOS5L)

Written 2026-09-18, updated 2026-10-17 after the first green hardening of the SRAM-macro design. **`main` holds core v0 and core v0.1 (merged 2026-10-15, `ac0e555`). The SRAM instruction memory is on branch `sram-imem`: complete, reviewed, and hardened green in CI (`gds` run 39014059324 on `4badf9e`: slow-corner setup +1.91 ns at 50 MHz, precheck and gl_test green). **Merged into `main` on 2026-10-17** (fast-forward to `658d152`, after the confirmation run 39022021518 on that head came back green on `gds`, `metrics_gate`, `precheck` and `gl_test`). Still open for the owner: re-enable GitHub Pages and the release label.**

## Paste this into the new session

> Continue the protocol-emulator ASIC project in this folder. Read `HANDOFF.md` first, then `PLAN.md`. Branch `sram-imem` (512 x 16 SRAM instruction memory) is reviewed and hardened green (run 39014059324, slow-corner setup +1.91 ns at 50 MHz, precheck and gl_test green). `sram-imem` is merged into `main` (658d152, 2026-10-17). Check "What is left" for the open owner items (re-enable GitHub Pages, release label), ask which have been answered, then apply the answers. Plan C (required protocols) is being worked in a separate session on branch `claude/agitated-hamilton-5fbcad` (not merged); check with the owner before starting it again here. Run at most two agents, only one of them committing, tell each to do the work itself in the foreground, and free memory on this Mac first (see "Environment").

## Where everything is

| What | Path |
|---|---|
| Competition plan, timeline, decision log, risks | `PLAN.md` |
| Approved architecture (v1) | `docs/superpowers/specs/2026-09-15-protocol-emulator-design.md` |
| Implementation plans executed | `docs/superpowers/plans/2026-09-16-core-v0.md` (core v0, 10 tasks), `docs/superpowers/plans/2026-10-15-sram-imem.md` (SRAM, 4 tasks; Task 4, the docs and results row, done 2026-10-17) |
| SRAM instruction-memory design | `docs/superpowers/specs/2026-10-15-sram-imem-design.md` |
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
| Firmware | `firmware/blink.s`, `firmware/uart_tx.s` |
| Tests | `tests/` (pytest), `test/` (cocotb: `Makefile` = host/top level, `Makefile.core`, `Makefile.blocks`, `Makefile.uartfw`) |
| Formal proofs and their honest scope | `formal/core.sby`, `formal/core_props.v`, `formal/timebase_props.v`, `formal/README.md` |
| Toolchain bootstrap | `scripts/setup_env.sh` (writes `env.sh`, git-ignored) |
| Per-task briefs, reports, review diffs, progress ledger (**local only, git-ignored**) | `.superpowers/sdd/` (SRAM: `sram-task-N-brief.md`, `sram-task-N-report.md`, `sram-final-review.md`, `sram-final-rereview.md`); CI logs and metrics are saved there when downloaded (`gds-ac0e555.log`, `gds-10a9583.log`, `gds-4badf9e.log`, `metrics-4badf9e.json`; the log of `714d81a` was not saved) |
| GitHub | https://github.com/Abagel-coder/protocol-emulator (**public since 2026-10-16**, so no artifact quota; GitHub Pages was unpublished by the change of visibility, `gh api repos/Abagel-coder/protocol-emulator/pages` returns 404, so the `gds` workflow's `viewer` job fails until the owner re-enables Pages) |

## State

- **Latest (2026-10-17):** branch `sram-imem` at `ad51c21` (tests and comments only over `4badf9e`; same netlist). The green hardening of record is `gds` run [39014059324](https://github.com/Abagel-coder/protocol-emulator/actions/runs/39014059324) on `4badf9e` (jobs `gds`, `metrics_gate`, `precheck`, `gl_test` success; `viewer` failed because Pages is unpublished). Numbers in "Core v1.0 (SRAM) hardening result" below and in the README results row. The bullets that follow describe the state at `41ac372`/`10a9583` and are kept as history.
- Branch `sram-imem`: the commit that carries this handoff update (`git log -1`) sits on `41ac372` (RTL, tools, tests and flow files are unchanged by it; it edits documents and one comment in `src/pdn_cfg.tcl`). `origin/sram-imem` was last pushed at `10a9583`; check `git status -sb` for what is still local. `main` is at `ac0e555` (core v0.1, merged 2026-10-15 by fast-forward; CI on it green on all four workflows).
- The SRAM work: design `docs/superpowers/specs/2026-10-15-sram-imem-design.md`, plan `docs/superpowers/plans/2026-10-15-sram-imem.md`. Tasks 1-3 (the `pe_imem` block, the chip integration with 512-word tools and tests and `READ_STATUS` bit 5, the flow configuration and metrics gate) are implemented, each reviewed with mutation checks; the whole-branch review and its fix wave are approved (reports `.superpowers/sdd/sram-*.md`, local only). Task 4 (this handoff and the README results row) was completed on 2026-10-17 from the green run 39014059324.
- Local suites at `41ac372` (2026-10-16): host 22, core 20 (19 directed + the 200-program differential fuzzer, each program tiled 8 times over the 512 words), blocks 7, UART firmware equivalence 1, pytest 50, Verilator lint clean, `formal/core.sby` five tasks pass (sby 5/5), `tools/gen_isa.py --check` clean.
- GitHub Actions on `sram-imem` (at `714d81a`): the `test` and `docs` workflows failed only at the artifact upload ("Artifact storage quota has been hit"; every test step was green); the repository was made public on 2026-10-16, which removed the quota. The `gds` workflow is the subject of the sections below. After the quota failure the controller deleted 42 artifacts (GDS_logs, gds_render, tt_submission; 1.68 GB) from 14 intermediate runs and later the bundle of the main-merge run 36945175253; the bundles of the runs of record 35402020440 (core v0) and 37027426422 (core v0.1) were kept.

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

### Core v1.0 (SRAM) hardening result (GitHub `gds` run [39014059324](https://github.com/Abagel-coder/protocol-emulator/actions/runs/39014059324), commit `4badf9e`, branch `sram-imem`, 2026-10-17)

Design at `4badf9e`: core v0.1 + 512x16 IHP SRAM instruction memory (`pe_imem`, macro `RM_IHPSG13_1P_512x16_c2_bm_bist`) + per-register precompute of the `WAITT` compare (`20edbfe`) + `SYNTH_STRATEGY` "DELAY 4" (`4badf9e`). Jobs: `gds`, `metrics_gate`, `precheck`, `gl_test` success; `viewer` failure (Pages unpublished). Sources: the `metrics_gate` job log, the `gds` job log (`.superpowers/sdd/gds-4badf9e.log`) and the run's `metrics.json` (`.superpowers/sdd/metrics-4badf9e.json`, local only); metric key in brackets.

| Metric | Value (core v0.1 in brackets) |
|---|---|
| Cells | 1 macro (45,309.31 µm²) + 6,797 standard cells (5,527 logic from the post-synthesis report, 1,270 added by place-and-route: 1,157 timing-repair buffers of which 745 hold buffers, 68 clock buffers, 25 clock inverters, 20 antenna cells) [12,561] |
| Standard-cell area | 94,717 µm² (`design__instance__area__stdcell`) [192,394 µm²] |
| Utilisation of the 6x4 core | 15.52 % (`design__instance__utilization`; std cells + macro over 902,417 µm²) [21.32 %] |
| Setup slack @ 50 MHz | slow corner +1.906 ns, typical +8.766 ns (`timing__setup__ws__corner:*`) [+4.848 ns slow] |
| Hold slack | +0.120 ns (`timing__hold__ws`, fast corner) [+0.123 ns] |
| Routing DRC / antenna violations / LVS | 0 / 0 / 0 (`route__drc_errors`, `antenna__violating__nets`, `design__lvs_error__count`) |
| Max slew / max cap / max fanout violations | 0 / 0 / 94 per corner |
| Routed wirelength | 323,585 µm over 6,777 nets (`route__wirelength`, `route__net`) |
| Magic DRC | 57,923 errors, non-fatal by configuration with the macro present; 5 Magic illegal overlaps (flow warning); KLayout DRC is the `precheck` job (passed) |
| Gate-level simulation | `gl_test` passed (22 of 22 tests) |

Timing history of the macro design (slow-corner setup at 50 MHz): `714d81a`/`a850747` default `AREA 0` synthesis -0.740 ns; experiment "DELAY 1" +0.655 ns (run 39007956049); "DELAY 4" +1.367 ns (run 39007956627); "DELAY 4" plus the RTL precompute of the `WAITT` compare +1.906 ns (this run). The 50 MHz clock stays: no `CLOCK_PERIOD`, `info.yaml` or firmware change.

### Earlier SRAM hardening runs (history): GitHub `gds` runs on `sram-imem`

Core v0.1 had 12,561 standard cells and no macro. The first two runs of the macro design (both stopped by the artifact quota, not by the flow):

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

The fix between the runs was `10a9583` (adopt Loom's pdngen wrapper in `src/pdn_cfg.tcl`; Apache-2.0, attributed): the first file was LibreLane's default minus the macro grid, which left the Metal4 stripes short of the macro. The standard-cell count is 5,535 plus the macro, against 12,561 cells for core v0.1 (the 64-word flip-flop memory is gone and the macro holds eight times the words). The timing cause is the macro's clock-to-output of about 6.3 ns inside the fetch loop (`A_DOUT` -> decode -> `next_pc` -> `A_ADDR`) at the 20 ns clock. These two runs are not in `README.md`'s Results table; the green run above is. Logs: `.superpowers/sdd/gds-10a9583.log` is saved; `gds-714d81a.log` is not.

## What is left (in order)

1. **Owner items** (the code documents the current choice):
   1. ~~Merge of `sram-imem`~~ **Done 2026-10-17**: fast-forward merge into `main` (`658d152`) after the owner's go-ahead and the green confirmation run 39022021518 (`gds`, `metrics_gate`, `precheck`, `gl_test`; `viewer` fails until Pages is re-enabled).
   2. **Re-enable GitHub Pages** (`gh api repos/Abagel-coder/protocol-emulator/pages` returns 404 since the repository went public on 2026-10-16); the `gds` workflow's `viewer` job fails until then.
   3. **Release label.** `src/project.v` calls the SRAM build "core v1", which collides with "spec v1"; the README row says "core v1.0", provisionally. The owner names the release.
   (Settled: the artifact quota, by making the repository public on 2026-10-16; the timing decision, by the green run at 50 MHz.)
2. **Plan C** (required protocols: UART RX, SPI master modes 0-3, I2C master with reference models; schedule in `PLAN.md` section 3, freeze Nov 8). Status: worked in a separate session on branch `claude/agitated-hamilton-5fbcad` (not merged; it is not part of `sram-imem` or `main`).

### Minor findings logged during task reviews (triaged in the whole-branch review)

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
- Generated files (`docs/isa.md`, `tools/isa_defs.py`, `src/isa_defs.vh`) change only via `isa/isa.yaml` + `.venv/bin/python tools/gen_isa.py`; CI fails on drift of those three. The field slices in `src/pe_core.v` are hand-typed and are checked only by the differential fuzzer.
- The instruction memory is 512 words, one IHP SRAM macro on the chip (the `FLOPS` build is simulation/FPGA only). Addresses and jump targets alias modulo 512 (`WRITE_IMEM` takes the low 9 bits of its 10-bit address field); the assembler refuses programs larger than 512 words; the macro has no reset, so load all 512 words (zero-fill) before RUN. Its single port is shared with the core's fetch: a `WRITE_IMEM` word that arrives while the core is active (running, including stalled in a wait) is **dropped**, not queued, and sets `READ_STATUS` bit 5 until the next `WRITE_CTRL` reset; pause (RUN low and `WRITE_CTRL` run=0) or halt the core before loading. Caveat, the RUN-pin race: a word accepted in the last inactive cycle (RUN rising during a load) leaves a stale word in `ir` for one cycle, and the word under a stalled `pc` can change; keep RUN low while loading (`formal/README.md` hypothesis H3 is narrowed to exactly this). `WAITT` is wrap-safe (core v0.1): it completes once bit 15 of `T - Rn` is 0 -- a deadline up to 32,768 ticks ahead releases exactly at `T == Rn`, one already passed (up to 32,767 behind) at once, flags untouched; keep deadlines under 32,768 ticks ahead. Timed waits keep the equality compare on the `T + timeout` they capture when they start, so a timeout that passes while RUN is low waits for `T` to come round again (`docs/info.md`).

## Environment on this Mac

```bash
source env.sh                      # every shell: OSS CAD Suite, venvs, PDK_ROOT, tt_tool
.venv/bin/pytest -q                # tools
make -C test -B                    # host/top-level cocotb
make -C test -B -f Makefile.core   # core directed tests + differential fuzzer (DIFF_PROGRAMS=25 to shorten)
make -C test -B -f Makefile.blocks
make -C test -B -f Makefile.uartfw # CI's test workflow runs all four (README "What CI runs")
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
- **GitHub artifact quota (private repository, 500 MB free).** Every `gds` run uploads `GDS_logs`, `gds_render` and `tt_submission` (about 130 MB per run); the `test` and `docs` jobs fail at their own upload once the quota is hit even though every test step passed, and a failed gds upload skips the metrics gate, precheck, `gl_test` and viewer. GitHub's usage figure lags deletions by hours. Delete superseded bundles as you go (`gh api repos/Abagel-coder/protocol-emulator/actions/artifacts` lists them, `gh api -X DELETE repos/Abagel-coder/protocol-emulator/actions/artifacts/<id>` removes one) and KEEP the artifacts of the runs of record: 35402020440 (core v0) and 37027426422 (core v0.1). The run of the main merge (36945175253) was identical RTL to core v0 and its bundle is already deleted. The repository was made public on 2026-10-16, which removes the quota; the advice is kept in case it goes private again.
- A push cancels the `gds` run in progress on the same branch (`cancel-in-progress`); do not push while a run you want is still going. A docs-only commit can carry `[skip ci]`.

## After the SRAM branch: next plans (not written yet)

1. **Lanes (pin engines)**: shift + fractional divider, NRZ → CRC-32 → NRZI/bit-stuffing (USB) → edge-timestamp FIFO → Manchester; start-at-deadline (`LARM`); contention monitors in the GPIO block. Decisions N2–N6 in `docs/research/novelty-synthesis.md`.
2. **Protocol firmware + reference models (plan C, required by the Nov 8 freeze: do this first)**: UART RX, SPI master/slave, I2C master/slave, then USB low speed and 10BASE-T.
3. **Verification depth**: MCY mutation score, EQY RTL-vs-netlist equivalence, cocotb-coverage crosses, microcotb replay on the FPGA board, measured AI-assisted property drafting.
4. **Generate field-slice macros** into `src/isa_defs.vh` (e.g. `ISA_BPIN_LEVEL_MSB/LSB`) and use them in `pe_core.v`, so `gen_isa.py --check` really pins the layout (today only the fuzzer does); also generate the class-count sentence in `docs/info.md`.
5. **Owner items carried over:** re-enable Pages, the release label (the merge of `sram-imem` was done 2026-10-17) (under "What is left"). (Decided 2026-10-01, branch `core-v0.1`: the wrap-safe `WAITT` deadline compare per spec §6, with the `t_in + tmo` adder moved off the `adv` critical path; the UART timing reference moved from `src/` to `test/uart_tx_ref.v`. Decided 2026-10-15: `core-v0` and `core-v0.1` merged into `main`.)

The README-as-evidence-ledger plan (plan A) and plan C are scheduled in `PLAN.md` section 3.

## Owner-side items

- Sign-up form: done. FPGA kit: ordered, owner will say when it arrives. Team (D2): deferred.
- Schedule: `PLAN.md` compressed timeline; required-protocol freeze re-planned to 2026-11-08 (hard stop 2026-11-23); submission deadline 2027-01-18 (aim for 2027-01-15).
