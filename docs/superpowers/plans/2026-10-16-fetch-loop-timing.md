# Fetch-Loop Timing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover positive slow-corner setup slack at 50 MHz with the SRAM macro by taking the register mux and the 16-bit subtract of the `WAITT` compare off the instruction-word path.

**Architecture:** `pe_core.v` computes the deadline-compare bit and the zero test for all eight registers from registered values every cycle and selects by `ir[8:6]` after decode; nothing else changes. Design: `docs/superpowers/specs/2026-10-16-fetch-loop-timing-design.md` -- read it first.

**Tech Stack:** Verilog-2005, cocotb 2.0.1 via `source env.sh`, SymbiYosys, Tiny Tapeout `gds` flow in CI.

## Global Constraints

- Branch `sram-imem` (owner asks before any merge). One commit per task.
- Cycle-exact: no change to `isa/`, `src/isa_defs.vh`, `firmware/`, `tools/sim.py`, `pe_core.v`'s state update block, or any port. `git diff HEAD~1 -- isa src/isa_defs.vh firmware tools` empty after Task 1.
- All suites warning-free; lint clean; `gen_isa.py --check` 0; `formal/core.sby` five tasks pass.
- Mutants M1-M5 of the design doc §4 run on scratch copies and each killed by a named test or property.

---

### Task 1: Precomputed `WAITT` compare and zero test

**Files:**
- Modify: `src/pe_core.v:81-106` (wait unit), `src/pe_core.v:166` (`_unused`), comments at `:220-221`, `:264`; `formal/README.md:53` and the W2/W3 mutant rows (`:433-434`) which name `waitt_diff`.
- Test: existing `test/test_core.py` (`waitt_*`, `zero_timeout_*`), `tests/test_sim.py`, `test/test_diff.py`, `formal/core.sby`.

**Interfaces:**
- Consumes: `regs[0:7]` (`:42`), `t_in`, `wait_active`, `wdead`, `w_rt`, `w_sub`.
- Produces: `wire waitt_done` and `wire timed_to` with identical values to today for every `w_rt`; the names `waitt_ok`, `reg_zero`, generate blocks `g_wok`, `g_rz`.

- [ ] **Step 1 (baseline):** `source env.sh`; `make -C test -B -f Makefile.core` -> 20/20; `cd formal && sby -f core.sby` -> 5 tasks pass; record both.
- [ ] **Step 2 (RTL):** replace lines 95-96 and 103 of `src/pe_core.v` with:

```verilog
  // WAITT: wrap-safe deadline (isa.yaml semantics.waits). Done once bit 15 of T - Rn (mod 2^16) is 0,
  // i.e. Rn is not ahead of T: a deadline up to 32,768 ticks ahead releases exactly at T == Rn (T
  // moves at most one tick per cycle and Rn cannot change while stalled), one already passed (up to
  // 32,767 ticks behind) releases at once.
  // Timing: the compare is computed for every register from registered values (t_in, regs) and only
  // SELECTED by the instruction's rt field, so the 16-bit subtract is not on the A_DOUT -> adv path
  // (docs/superpowers/specs/2026-10-16-fetch-loop-timing-design.md). R0 reads as 0.
  wire [7:0] waitt_ok;
  assign waitt_ok[0] = !t_in[15];
  genvar gk;
  generate for (gk = 1; gk < 8; gk = gk + 1) begin : g_wok
    wire [15:0] d = t_in - regs[gk];
    assign waitt_ok[gk] = !d[15];
    wire _unused_d = &{d[14:0], 1'b0};
  end endgenerate
  wire        waitt_done = waitt_ok[w_rt];
  // Zero test per register for the first-cycle timeout rule (tmo == 0; R0 means 65535, never 0).
  wire [7:0] reg_zero;
  assign reg_zero[0] = 1'b0;
  generate for (gk = 1; gk < 8; gk = gk + 1) begin : g_rz
    assign reg_zero[gk] = (regs[gk] == 16'd0);
  end endgenerate
```

and `wire timed_to = wait_active ? (t_in == wdead) : reg_zero[w_rt];` (keep the comment above it; `tmo` stays for the `wdead` capture at `:201`). Line 166: drop `waitt_diff[14:0]` from `_unused`. Update the comments at `:220-221` and `:264` to name `waitt_ok`/`waitt_done` instead of `waitt_diff`. Verilator may need `/* verilator lint_off GENUNNAMED */` nowhere: both blocks are named.

- [ ] **Step 3 (verify equivalence):** `make -C test -B -f Makefile.core` -> 20/20, 0 warnings; `.venv/bin/pytest -q` -> 50; `make -C test -B` -> 22/22; `cd formal && sby -f core.sby` -> 5/5 (if `prove` needs more induction depth, report; do not weaken a property); lint with the README command -> clean; `.venv/bin/python tools/gen_isa.py --check` -> 0; `git diff -- isa src/isa_defs.vh firmware tools` empty.
- [ ] **Step 4 (mutants, scratch copies, record kills):** M1 `assign waitt_ok[0] = t_in[15];`; M2 `wire [15:0] d = regs[gk] - t_in;`; M3 `assign reg_zero[0] = 1'b1;`; M4 `wire waitt_done = waitt_ok[f_rd];`; M5 `assign reg_zero[gk] = (regs[gk] == 16'd1);`. Expected killers: M1/M2/M4 by T1/T1b-e in `sby` (`bmc`) and by `waitt_*` directed tests / the fuzzer; M3/M5 by `zero_timeout_completes_in_first_cycle` and T4c. Each must die by at least one net.
- [ ] **Step 5 (synthesis sanity):** `yosys -q -p "read_verilog -Isrc src/pe_core.v src/pe_timebase.v src/pe_gpio.v src/pe_fifo.v src/pe_host_spi.v src/pe_imem.v src/RM_IHPSG13_1P_512x16_c2_bm_bist.v src/project.v; synth -top tt_um_abagel_coder_protocol_emulator; stat"` before and after; report the cell delta (expect a few hundred cells more) and that the macro instance is still a black box.
- [ ] **Step 6 (docs):** `formal/README.md:53`, `:433-434` wording (`waitt_ok`), one sentence in `docs/info.md`'s timing description is NOT needed (behaviour unchanged). `HANDOFF.md` contracts: no change.
- [ ] **Step 7: Commit:** `git commit -am "perf(core): precompute the WAITT deadline compare and zero test per register; select after decode (slow-corner setup was -0.74 ns with the macro)"`.

---

### Task 2: Harden, read the gate, record the baseline (controller)

- [ ] **Step 1:** Push `sram-imem`; the four workflows plus the `metrics_gate`, `precheck`, `gl_test` jobs run. Compare the slow-corner setup slack with the two `SYNTH_STRATEGY` experiment runs (`exp-synth-delay1`, `exp-synth-delay4`); adopt the better strategy on `sram-imem` if it adds margin, in its own commit, and harden once more.
- [ ] **Step 2:** When green: README results row (cells, area, utilisation, slack slow/typ, hold, DRC, antenna, LVS, run link), HANDOFF state and hardening table, PLAN decision log; commit `docs: core v1.0 hardening baseline with the SRAM macro`.

## Self-review against the design doc

- §2 code -> Task 1 Step 2 verbatim (names `waitt_ok`, `reg_zero`, `g_wok`, `g_rz`); `rt_v`/`tmo` kept for `wdead`.
- §3 experiments -> Task 2 Step 1. §4 verification -> Task 1 Steps 3-5. §5 out of scope respected: no state-update or port change.
