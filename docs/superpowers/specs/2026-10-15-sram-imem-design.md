# SRAM instruction memory: design (2026-10-15)

Status: owner decision of 2026-10-01 ("plan B": one 512x16 single-port macro, `WRITE_IMEM` ignored and reported while the core runs, flip-flop build kept as fallback), written up here as the design the plan `docs/superpowers/plans/2026-10-15-sram-imem.md` implements. Research behind every flow choice: `.superpowers/research/sram-recipe-2026-10-02.md` (local, git-ignored) and `docs/research/competition-brief.md`.

## 1. Why

Core v0/v0.1 spends most of its 12,757 cells on the 64-word flip-flop instruction memory (1,604 flip-flops total in the design, the memory's 1,024 among them, plus the 64:1 read mux). 64 words cannot hold real SPI or I2C firmware. The IHP `RM_IHPSG13_1P_512x16_c2_bm_bist` macro is 236.8 x 191.34 um = 45,309 um2 (lib `area`), about a quarter of today's 193,038 um2 of standard cells, and gives eight times the words. The announcement recommends SRAM and six strong entries already harden one in CI on this PDK.

## 2. The macro and how it is driven

Single port, 512 x 16, registered output (one-cycle read latency, same as `pe_imem_ff`). Ports and tie-offs (PDK model `libs.ref/sg13cmos5l_sram/verilog/RM_IHPSG13_1P_512x16_c2_bm_bist.v`):

| Port | Drive | Why |
|---|---|---|
| `A_CLK` | `clk` | |
| `A_MEN` | `1'b1` | always enabled |
| `A_WEN` | `wr_ok` | accepted host write |
| `A_REN` | `!wr_ok` | read every cycle except an accepted write; with `A_REN` low during the write the output register **holds**, so no write-through |
| `A_ADDR[8:0]` | `wr_ok ? waddr[8:0] : raddr[8:0]` | one address bus |
| `A_DIN` | `wdata` | |
| `A_BM` | `16'hFFFF` | whole-word writes |
| `A_DLY` | `1'b1` | the model `$stop`s otherwise; datasheet requirement |
| `A_BIST_*` | all `0` | BIST unused |
| `A_DOUT` | `rdata` | |

Behavioural model (`RM_IHPSG13_1P_core_behavioral_bm_bist.v`): `MEN && WEN` writes, and updates the output register only if `REN`; `MEN && REN && !WEN` reads. Contents are undefined at power-up (X in simulation): the host loads before `RUN`, as today.

## 3. Port sharing rule (the owner's decision)

- A host write (`imem_wr` from `pe_host_spi`) is **accepted only while the core is not active** (`active = run_q && !halted && !core_reset`, the core's existing output). Halted or paused cores accept writes; a running core, including one stalled in a wait, does not.
- A write that arrives while the core is active is **dropped** and **reported**: `pe_imem.wr_dropped` pulses for that cycle; `pe_host_spi` keeps a sticky flag `imem_dropped`, returned as **`READ_STATUS` byte 1 bit 5**, cleared by `WRITE_CTRL` with the reset bit (and by `rst_n`).
- Because the output register holds during an accepted write, the instruction word of a paused core is unchanged when `RUN` returns, and the cycle after the write reads `raddr` (= the stalled `pc`) again. No extra stall or refetch logic is needed.

## 4. Module shape

`src/pe_imem.v`, module `pe_imem #(parameter IMPL = "MACRO")`, ports `clk, active, raddr[9:0], rdata[15:0], wr_en, waddr[9:0], wdata[15:0], wr_dropped`. Two `generate` branches with identical cycle behaviour:

- `g_macro`: instance `u_sram` of `RM_IHPSG13_1P_512x16_c2_bm_bist` (section 2). Flattened instance path for the flow: `u_imem.g_macro.u_sram`.
- `g_flops`: a 512 x 16 register array with the same rule (write OR read per cycle, output holds on a write). This is the fallback for a flow failure and for the FPGA build (the FPGA workflow is disabled; flipping `IMPL` in `src/project.v` is the documented switch). `src/pe_imem_ff.v` is deleted; its behaviour lives in `g_flops`.

Address bit 9 of `raddr`/`waddr` is ignored: addresses alias modulo 512 (was 64).

`src/RM_IHPSG13_1P_512x16_c2_bm_bist.v`: a **port-only blackbox** for synthesis, referenced by the flow's `MACROS.nl` and **not** in `info.yaml` `source_files` nor in any `PROJECT_SOURCES` (the simulation models define that module). If it ever gets a body, LibreLane synthesises 8,192 flops instead of placing the macro.

## 5. Simulation

The two PDK models are vendored to `test/models/` (Apache-2.0, `test/models/README.md` names the source path and PDK commit; CI's test job has no PDK checkout). Every cocotb Makefile adds both models and `-DFUNCTIONAL` (the macro wrapper instantiates the behavioural core only under `FUNCTIONAL`). The gate-level netlist keeps the macro as a blackbox, so `GATES=yes` needs the models too. Tests deposit programs through `test/imem_load.py` (one helper that knows the model's `memory` array path) instead of `dut.u_imem.mem[i]`.

## 6. Flow (Loom recipe, one macro, 6x4)

`src/config.json` gains: `MACROS` (instance `u_imem.g_macro.u_sram` at `[12, 40]` orientation `FS`; `gds`/`lef`/`lib`/`spice` from `pdk_dir::libs.ref/sg13cmos5l_sram/...`, `nl` = the blackbox), `PDN_MACRO_CONNECTIONS` for `VDD!`/`VSS!` and `VDDARRAY!`/`VSS!`, `PDN_CFG: dir::pdn_cfg.tcl`, which is Loom's `src/pdn_cfg.tcl` (Apache-2.0, commit `87524912`): LibreLane's default with its per-macro grid removed (with `FP_PDN_MULTILAYER 0` that grid has nothing to connect and GeneratePDN errors PDN-0232/0233) plus Loom's wrapper around `pdngen`. Removing the grid alone is not enough: pdngen treats a FIXED macro as an obstruction and cuts every core stripe short of it, so the macro's `VDD!`/`VSS!` were left unconnected (PSM-0069 at `OpenROAD.IRDropReport` in the first harden, CI run 38838496042). The wrapper marks hard macros PLACED only while pdngen builds its shapes, so the aligned Metal4 stripes run full height through the macro's supply columns, then restores FIXED; it then fails the step unless every stripe-layer shape over a macro lies inside same-net supply pins (gaps of at most 7 um between two such pins, for the `VDD!`/`VDDARRAY!` split) and every macro supply pin has a stripe through it, and runs `check_power_grid` on every supply net with errors stopping the step. `FP_PDN_VPITCH 67.44`, `FP_PDN_VSPACING 3.52`, `FP_PDN_VOFFSET 26.36` (tile Metal4 stripes land on the macro's Metal4 supply columns for a macro at x = 12), `MAGIC_MACRO_STD_CELL_SOURCE: PDK`, `MAGIC_EXT_ABSTRACT_CELLS: ["RM_IHPSG13_.*"]`, `ERROR_ON_MAGIC_DRC: false`, `ERROR_ON_ILLEGAL_OVERLAPS: false` (Magic flags the stripes crossing the LEF's Metal4 OBS bar at the `VDD!`/`VDDARRAY!` split; the GDS has no metal there; KLayout DRC and LVS stay the gate). Everything else is the template.

`.github/workflows/gds.yaml` gains a **metrics gate** after the action (`test/check_metrics.py runs/wokwi/final/metrics.json`): worst setup slack in the slow corner >= 0, worst hold >= 0, route DRC = 0, antenna violating nets = 0, LVS errors = 0. The template flow goes green on negative slack; this is the only timing check we have.

Timing risk: the fetch path is now `A_DOUT` (macro clock-to-Q) -> decode -> `next_pc` -> `A_ADDR` setup inside 20 ns. Core v0.1 had +2.58 ns at 50 MHz with the flip-flop memory. If the slack goes negative, the options are (owner's call): relax `CLOCK_PERIOD` (and `clock_hz`, and the UART firmware's bit constant), or add an instruction register (changes the cycle model, out of scope here).

## 7. Software and docs

`tools/asm.py` `IMEM_WORDS = 512`; `tools/sim.py` default `imem_words=512`; `tools/host.py` docstring; `test/test_diff.py` keeps generating 64-word programs (its jump fields are 6 bits) and zero-fills the other 448 words, stating so; `docs/info.md` (memory size, load rule, status bit 5, dropped-write rule, the v0 limitation removed), `README.md` (results row after CI, lint command), `HANDOFF.md`, `PLAN.md` decision log, the v1 spec's implementation-status note (SRAM deviation resolved), `test/README.md`.

## 8. Out of scope

Lanes, data memory, a second macro, FPGA wiring, the `pull_request` trigger, generated field-slice macros.
