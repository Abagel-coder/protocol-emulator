# Handoff — protocol-emulator ASIC (Jane Street / Tiny Tapeout CMOS5L)

Written 2026-09-18 for continuing in a new session. **Nothing is merged: all implementation work is on branch `core-v0`; `main` is untouched since the plan commit (`3546bcf`). Do not merge without the owner's say-so.**

## Paste this into the new session

> Continue the protocol-emulator ASIC project in this folder. Read `HANDOFF.md` first, then `PLAN.md`. We are on branch `core-v0` (pushed, not merged). Pick up at "What is left" in the handoff: run the Task 10 review, then the whole-branch review, and stop before merging. Use subagents where useful, and tell every subagent to do the work itself rather than delegating or waiting on monitors.

## Where everything is

| What | Path |
|---|---|
| Competition plan, timeline, decision log, risks | `PLAN.md` |
| Approved architecture (v1) | `docs/superpowers/specs/2026-09-15-protocol-emulator-design.md` |
| Implementation plan being executed (10 tasks) | `docs/superpowers/plans/2026-09-16-core-v0.md` |
| Research: brief, prior art, verification, novelty decisions N1–N10 | `docs/research/` |
| ISA source of truth and generated reference | `isa/isa.yaml`, `docs/isa.md` |
| Tools: generator, assembler, cycle-accurate oracle, host encoders | `tools/gen_isa.py`, `tools/asm.py`, `tools/sim.py`, `tools/host.py` |
| RTL | `src/project.v` (top), `src/pe_core.v`, `pe_gpio.v`, `pe_timebase.v`, `pe_imem_ff.v`, `pe_fifo.v`, `pe_host_spi.v`; `src/uart_tx.v` is only a timing reference |
| Firmware | `firmware/blink.s`, `firmware/uart_tx.s` |
| Tests | `tests/` (pytest), `test/` (cocotb: `Makefile` = host/top level, `Makefile.core`, `Makefile.blocks`, `Makefile.uartfw`) |
| Formal proofs and their honest scope | `formal/core.sby`, `formal/core_props.v`, `formal/timebase_props.v`, `formal/README.md` |
| Toolchain bootstrap | `scripts/setup_env.sh` (writes `env.sh`, git-ignored) |
| Per-task briefs, reports, review diffs, progress ledger (**local only, git-ignored**) | `.superpowers/sdd/` |
| GitHub | https://github.com/Abagel-coder/protocol-emulator (public, Pages enabled) |

## State

- Branch `core-v0` at the final fix wave's sixth commit (`docs: state what is proved and what CI runs, datasheet limits and caveats, project status`), 31 commits ahead of `main`, working tree clean. Pushed up to `721cc2a`; `65e5894` (Task 10 fix round) and the six fix-wave commits `a84a0ee`, `eebe68b`, `8b83e4b`, `dbbe9ea`, `0e4ec5c` + the docs commit are **local, not pushed**.
- All ten plan tasks are implemented and each passed a spec-and-quality review (Task 10 approved on re-review 2026-09-21 after one fix round). The whole-branch review (three lenses, 2026-09-21: `.superpowers/sdd/final-review-{rtl,verif,tools}.md`) returned "ready with fixes" -- no Critical finding, no functional RTL bug -- and its fix wave (six commits, `.superpowers/sdd/final-fix-report.md`) is done; **re-review of the fix wave is pending**. The RTL logic is unchanged since `f743131` (comment-only edits and formal-block properties only, verified by a preprocessed diff in the fix report).
- GitHub Actions on `a76f968`: `test`, `docs`, `tools` (pytest + generator drift check + formal) and `gds` (hardening, precheck, gate-level test, viewer) are all green. Run: https://github.com/Abagel-coder/protocol-emulator/actions/runs/35410806312. Nothing later has run in CI (not pushed); the `test` workflow now also runs the core/fuzzer, blocks and UART suites and `tools` pins OSS CAD Suite 2026-09-15 (README "What CI runs"), so the first push will be the first CI run of those.
- Local suites (2026-09-22): pytest 39; cocotb host 18, core 14 directed + the 200-program differential fuzzer, blocks 3, UART equivalence 1, all warning-free; Verilator lint clean; `formal/core.sby` five tasks pass (`bmc`, `prove`, `cover`, `timebase_bmc`, `timebase_prove`) with properties T1, T1b (port-bit form), T2a, T2b (successor-address form), P1 reset state, P3 wait persistence, P4 deadline capture, T3/T3b/T3c, T4 parts 1-2, T5a-d, RUN_LINK, and 5 cover goals (`formal/README.md`).

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

## What is left on this branch (in order)

1. **Task 10 review** -- done (approved on re-review 2026-09-21; fix commit `65e5894`).
2. **Whole-branch review** -- done 2026-09-21 (three lenses, reports in `.superpowers/sdd/final-review-*.md`); the single fix wave for everything raised is done (`.superpowers/sdd/final-fix-report.md`, commits `a84a0ee`..the docs commit). **Re-review of the fix wave: pending.**
3. **Owner decision**: merge `core-v0` to `main`, or open a pull request. Not before asked.

### Minor findings logged during task reviews (triaged in the whole-branch review)

Status after the fix wave (2026-09-22): fixed -- unused `importlib`; assembler dead code / `max_pc` / `.equ`-`.org`-`.word` error wrapping; `reserved_alu_fn_is_noop` (now rs != rd, checks C); stale HALT comment; post-reset assertion and `running` bit; `sim.py` prescale docstring; `w_rt` decode pinned formally; `IN`/PUSH/POP/CALL/RET/IRQ/WAITL/zero-timeout semantics documented. Deferred to the next plan (owner decisions): `pull_request` trigger (all workflows are push-only by convention); `pe_gpio` OE-clear / pin 7 / `tick` block tests; `alu_valid` comment; `pe_imem_ff` `WORDS = 1 << AW`; `h2c_full` gate; `imem_waddr` increment placement; CS_n hold wording; `cs_start` wire; fuzzer `pc` compare; `uart_tx.s` idle-segment check; the `t_in + tmo` adder on the critical path.

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
- The instruction memory is 64 words (addresses and jump targets alias modulo 64; the assembler refuses larger programs; zero-fill before RUN). v0 compares deadlines for equality only: a deadline that `T` has already passed waits for a full wrap (`docs/info.md`, "v0 limitations").

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
- **Local hardening is unreliable**: Docker Desktop's file sharing stalls and kills the engine during heavy I/O (VM memory was raised to 12 GB; a backup of Docker's settings file sits beside it). Treat the GitHub `gds` workflow as the flow of record.
- Libraries go into virtual environments or `~/ttsetup`, never system-wide (owner's standing preference).

## Lessons from this session about running subagents

- Several agents died when they handed work to a background worker or ended their turn "waiting for a monitor". Tell every agent: do all the work yourself, run long commands in the foreground with a time limit, never wait on notifications.
- Interrupted agents leave uncommitted partial work. On resume, check `git status` and the ledger before re-dispatching, and tell the next agent to treat the working tree as unverified.
- Reviews with mutation testing found real gaps every time (inert tests, surviving mutants in the formal properties). Keep asking reviewers to prove a test or property fails when the fix is reverted.

## After this branch: next plans (not written yet)

1. **Lanes (pin engines)**: shift + fractional divider, NRZ → CRC-32 → NRZI/bit-stuffing (USB) → edge-timestamp FIFO → Manchester; start-at-deadline (`LARM`); contention monitors in the GPIO block. Decisions N2–N6 in `docs/research/novelty-synthesis.md`.
2. **SRAM instruction memory** on CMOS5L: the foundry macro fails at power-grid generation because the tile's vertical stripes and the macro's power pins are both on Metal4; the PRISM entry's stripe-alignment plugin is the known fix (notes in `docs/research/competition-brief.md`).
3. **Protocol firmware + reference models**: UART RX, SPI master/slave, I2C master/slave, then USB low speed and 10BASE-T.
4. **Verification depth**: MCY mutation score, EQY RTL-vs-netlist equivalence, cocotb-coverage crosses, microcotb replay on the FPGA board, measured AI-assisted property drafting.
5. **Generate field-slice macros** into `src/isa_defs.vh` (e.g. `ISA_BPIN_LEVEL_MSB/LSB`) and use them in `pe_core.v`, so `gen_isa.py --check` really pins the layout (today only the fuzzer does); also generate the class-count sentence in `docs/info.md`.
6. **Owner decisions carried over from the whole-branch review**: wrap-safe (signed) deadline compare per spec §6 vs. keeping equality-only (documented as a v0 limitation); moving the `t_in + tmo` adder off the `adv` critical path; keeping `src/uart_tx.v` in `src/` as a documented exception vs. moving it to `test/`; merge `core-v0` vs. pull request.

## Owner-side items

- Sign-up form: done. FPGA kit: ordered, owner will say when it arrives. Team (D2): deferred.
- Schedule: `PLAN.md` compressed timeline; required-protocol freeze targeted for 2026-11-02; submission deadline 2027-01-18 (aim for 2027-01-15).
