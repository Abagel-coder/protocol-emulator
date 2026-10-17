# Fetch-loop timing with the SRAM macro: design (2026-10-16)

Owner decision 2026-10-16: keep 50 MHz (`CLOCK_PERIOD` 20 ns) and shorten the core's critical path instead of relaxing the clock.

## 1. The measured problem

Run 38988882606 (branch `sram-imem`, commit a850747), slow corner `nom_slow_1p08V_125C`, post-route: worst setup slack **-0.740 ns**, TNS -26.75 ns, 310 violating paths, every one starting at the macro output `u_imem.g_macro.u_sram/A_DOUT[*]`. The 30 worst all have the same shape (`runs/wokwi/55-openroad-stapostpnr/nom_slow_1p08V_125C/max.rpt`, saved copy of the artifact in the session scratchpad; metrics in `.superpowers/sdd/metrics-a850747.json`):

| Segment | Delay (ns) | What it is |
|---|---|---|
| clock tree to `A_CLK` | 0.77 | |
| `A_CLK` -> `A_DOUT` | 6.72 | macro clock-to-output, slow lib |
| 3 levels of `buf_1` | 1.77 | the instruction word's fan-out |
| `ir[8:6]` decode -> one-hot AND-OR mux of `regs[w_rt]` | 1.3 + **2.05** | `rt_v = regs[w_rt]`; the 2.05 ns is a `nor4_1` driving 0.097 pF with a 2.5 ns slew (poor sizing) |
| `a221oi/o21ai/a21oi ... xnor2` chain | 1.5 | the 16-bit subtract `t_in - rt_v`, bit 15 |
| `adv` and its fan-out (`fanout81/80/79`, `nand3`, `fanout50/49/32/19/18`) | 5.2 | `adv` gates every state update; the register-file write enables are the deepest leaves |
| setup at `regs[k][b]` | 0.18 | |

Core v0.1 had +4.85 ns on this path with the flip-flop memory (about 1.5 ns from clock to `rdata`); the macro adds about 5.6 ns, which is the whole regression. The ALU paths (`ir` -> `rd_v`/`rs_v` -> adder -> `regs`) are not among the 30 worst.

## 2. The change (cycle-exact; no ISA, oracle or firmware change)

Move everything that does not depend on the instruction word off the `ir` path, so that after `ir` arrives the wait unit only selects a precomputed bit:

```verilog
// Deadline compare for every register, from registered values only (t_in, regs): no ir on this path.
wire [7:0] waitt_ok;   // waitt_ok[k] == !((t_in - Rk)[15]), R0 reads as 0
assign waitt_ok[0] = !t_in[15];
genvar k;
generate for (k = 1; k < 8; k = k + 1) begin : g_wok
  wire [15:0] d = t_in - regs[k];
  assign waitt_ok[k] = !d[15];
end endgenerate
wire waitt_done = waitt_ok[w_rt];                 // 8:1 select after decode

// Zero test for every register, for the first-cycle timeout rule tmo == 0 (R0 means 65535, never 0).
wire [7:0] reg_zero;
assign reg_zero[0] = 1'b0;
generate for (k = 1; k < 8; k = k + 1) begin : g_rz
  assign reg_zero[k] = (regs[k] == 16'd0);
end endgenerate
wire timed_to = wait_active ? (t_in == wdead) : reg_zero[w_rt];
```

`rt_v`/`tmo` stay for the `wdead <= t_in + tmo` capture (not on the `adv` path). `waitt_diff` goes away (and its `_unused` entry). Nothing else in `pe_core.v` changes. Behaviour is identical by construction: `waitt_ok[w_rt]` is `!((t_in - rt_v)[15])` and `reg_zero[w_rt]` is `(tmo == 0)` for every `w_rt`.

Cost: seven 16-bit subtract-sign circuits (only the sign is kept, so synthesis reduces each to a 16-bit magnitude comparator) and seven 16-input zero detectors, roughly 250-350 cells on a design of 5,539 (utilisation 13.9 %). Expected gain on the worst path: the register mux (about 3.3 ns including the mis-sized `nor4`) and the subtract chain (1.5 ns) are replaced by an 8:1 mux (about 0.5 ns): roughly +4 ns, so the slow-corner slack should land near +3 ns, with the next-worst paths (ALU, `next_pc`) then setting the margin.

## 3. Flow experiments run alongside (no RTL change)

Branches `exp-synth-delay1` and `exp-synth-delay4` add `SYNTH_STRATEGY` "DELAY 1" / "DELAY 4" to `src/config.json` on top of `sram-imem` and run the `gds` workflow. If either recovers a substantial part of the 0.74 ns on its own, the better value is adopted on `sram-imem` together with the RTL change (belt and braces: the strategy also helps the ALU paths that will become the worst ones). The slack numbers come from each run's `metrics.json` (`GDS_logs` artifact).

## 4. Verification

- The differential fuzzer and the directed WAITT tests (`test/test_core.py`, `tests/test_sim.py`) are unchanged and must stay green: the oracle is untouched, so any behavioural drift fails them.
- Formal (`formal/core.sby`, all five tasks): T1, T1b-T1f, T4c, P4 state the deadline rule on port bits and `regs`, not on `waitt_diff`, so they must still prove; `src/pe_core.v`'s FORMAL block references `waitt_diff` nowhere except possibly comments (check and update).
- Mutants (scratch copies, each must be killed by a named test or property): M1 `waitt_ok[0] = t_in[15]` (sign inverted for R0); M2 `g_wok` uses `regs[k] - t_in`; M3 `reg_zero[0] = 1'b1` (R0 timeout immediate); M4 `waitt_done = waitt_ok[f_rd]` (wrong field); M5 `reg_zero[k] = (regs[k] == 16'd1)`.
- Lint clean; `gen_isa.py --check`; `git diff -- isa src/isa_defs.vh firmware tools/sim.py` empty.
- The harden on CI: metrics gate green (slow-corner setup >= 0), precheck and gl_test green; record the new row.

## 5. Out of scope

An instruction register (changes the one-cycle model and the proofs), relaxing the clock (owner declined), lanes.

## Result (2026-10-17)

`gds` run [39014059324](https://github.com/Abagel-coder/protocol-emulator/actions/runs/39014059324) on commit `4badf9e` (the RTL precompute of `20edbfe` plus `SYNTH_STRATEGY` "DELAY 4"), slow-corner setup slack at the 20 ns clock (`timing__setup__ws__corner:nom_slow_1p08V_125C`):

| Build | Slow-corner setup slack |
|---|---|
| default synthesis (`AREA 0`), before the change (`714d81a`/`a850747`) | -0.740 ns |
| flow experiment "DELAY 1" (run 39007956049) | +0.655 ns |
| flow experiment "DELAY 4" (run 39007956627) | +1.367 ns |
| "DELAY 4" with the RTL precompute (run 39014059324, this design) | +1.906 ns |

Typical-corner setup is +8.766 ns and worst hold +0.120 ns; the metrics gate, precheck and gate-level simulation pass, so the clock stays at 50 MHz and the plan's "out of scope: relaxing the clock" held. Cell delta against the design before the change (`a850747`, `AREA 0`; saved `metrics-a850747.json`): standard cells 5,539 -> 6,797 (+1,258), standard-cell area 79,839 -> 94,717 µm² (+14,878 µm², +18.6 %), utilisation 13.87 % -> 15.52 % (core 902,417 µm², macro included), routed wirelength 209,170 -> 323,585 µm. The delta is the precompute and the "DELAY 4" strategy together: this run does not separate them, and the 250-350 cell estimate for the precompute above was an estimate; the cell count of the "DELAY" experiment runs was not compared. The 6,797 standard cells are 5,527 logic cells after synthesis plus 1,270 added by place-and-route (1,157 timing-repair buffers, 68 clock buffers, 25 clock inverters, 20 antenna cells).
