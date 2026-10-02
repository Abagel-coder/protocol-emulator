# Wrap-safe `WAITT` deadline and wait-path timing simplification — design

Date: 2026-10-01. Status: **approved by the owner on 2026-10-01** (late `WAITT` continues with flags untouched; the timing simplification is folded into the same change; `src/uart_tx.v` moves to `test/`). Branch: `core-v0.1`, off `main` at `778e8c0`.

## 1. Problem

Core v0 releases `WAITT Rn` only in a cycle where `T == Rn`. The architecture spec (§6) asks for a wrap-safe signed compare. The difference matters when the deadline has already passed when `WAITT` executes — a loop body that overran, or RUN held low across the deadline while `T` free-runs: v0 then stalls until `T` wraps round to `Rn` again, up to 65,535 ticks. The whole-branch review recorded this as a deviation from the spec and the datasheet lists it under "v0 limitations".

## 2. Decision

**`WAITT Rn` completes in the first cycle in which bit 15 of `(T − Rn) mod 2^16` is 0.**

| Deadline relative to `T` when `WAITT` first executes | Behaviour |
|---|---|
| equal to `T` | completes in that cycle (unchanged) |
| 1 … 32,768 ticks ahead | stalls and completes exactly in the first cycle where `T == Rn` (unchanged) |
| 1 … 32,767 ticks behind | completes in that cycle (was: stalls until `T` wraps to `Rn`) |

- `Rn` cannot change while the core is stalled and `T` advances by at most one per cycle, so a `WAITT` that stalls still releases at `T == Rn` exactly: the timing contract for on-time deadlines is unchanged.
- **Flags are untouched.** A late `WAITT` just continues; `TO`, `Z`, `C` keep their values ("`WAITT` and `DELAY` leave `TO` unchanged" stays true). A miss flag was considered and declined.
- `WAITT R0` uses deadline 0, as before.
- Firmware guidance: keep deadlines less than 32,768 ticks ahead of `T` (use the prescaler for longer intervals). A deadline 32,769 … 65,535 ticks ahead is indistinguishable from one that has passed and completes immediately.

**Timed waits are unchanged.** `WAITP` / `WAITF` capture `deadline = T + timeout` when the wait starts and compare for equality every cycle while stalled, so the deadline cannot be missed, and equality is what allows the full 65,535-tick timeout (`Rt = R0`). A signed window would cut that range in half.

**Timing simplification (same change).** Today the completion path computes `t_in == (wait_active ? wdead : t_in + tmo)`, putting a 16-bit adder in front of the compare on the `adv → next_pc → instruction-memory` path. It is replaced by the logically equal `wait_active ? (t_in == wdead) : (tmo == 0)`; the adder remains only on the `wdead` capture path. The reviewer identified this on the +2.58 ns critical path; folding it in offsets the magnitude comparator the new `WAITT` rule adds.

**`src/uart_tx.v` moves to `test/uart_tx_ref.v`** (module renamed `uart_tx_ref`). It is the fixed-function transmitter used only as the timing reference for the firmware-equivalence test and was never part of the hardened design.

## 3. What changes

| Area | Change |
|---|---|
| `isa/isa.yaml` (`semantics.waits`) → regenerated `docs/isa.md`, `tools/isa_defs.py` | new `WAITT` rule, the three-row table above in words, the 32,768-tick guidance |
| `tools/sim.py` | `WAITT` completes when `((T − Rn) & 0xFFFF) < 0x8000` |
| `src/pe_core.v` | `waitt_done` = sign bit of `t_in − rt_v` clear; `timed_to` simplified; `wdead` capture keeps `t_in + tmo` |
| formal (`pe_core.v` `ifdef FORMAL`, `formal/README.md`) | deadline theorem restated on the new rule; exactness-when-stalled lemma; late-release lemma; `WAITT` leaves flags unchanged; equivalence lemma for the simplified `timed_to` |
| tests | directed cocotb + pytest for late, on-time and boundary deadlines; a top-level test for RUN held low across a deadline; the differential fuzzer generates `WAITT` (it was excluded only because a random deadline could stall 65k ticks) |
| docs | datasheet "v0 limitations" entry replaced by the new rule; architecture spec status note; README; HANDOFF |
| `test/uart_tx_ref.v`, `test/Makefile.uartfw`, `test/tb_uartfw.v`, docs | file move and references |

`src/isa_defs.vh` does not change (no encoding change).

## 4. Verification

- Every new test and property is proven decisive by mutation in a scratch copy. Mutants that must die: the old equality rule; inverted sign; window off by one bit (bit 14 instead of bit 15); `timed_to` using `tmo == 1`; `wdead` captured without the timeout.
- All suites, all five formal tasks, lint and the generator drift check stay green; no warnings.
- The RTL changes, so the hardening baseline (12,757 cells, +2.58 ns) no longer describes the netlist: a new CI hardening run is recorded in the README after review.

## 5. Out of scope

A deadline-miss flag (declined), lanes, instruction-memory size, any other RTL change.
