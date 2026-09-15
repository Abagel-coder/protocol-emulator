# Jane Street Protocol Emulator ASIC Competition — Project Plan

Drafted 2026-09-15 (Monday). Submission deadline **Monday 2027-01-18** — 18 weeks away.
Companion documents:

- [docs/research/competition-brief.md](docs/research/competition-brief.md) — every fact and link this plan relies on.
- [docs/superpowers/specs/2026-09-15-protocol-emulator-design.md](docs/superpowers/specs/2026-09-15-protocol-emulator-design.md) — proposed architecture and verification design (draft, needs your approval before RTL starts).
- [scripts/setup_env.sh](scripts/setup_env.sh) — one-shot toolchain bootstrap for this Mac.

## 0. Status, and what is needed from you

- Research is done, the plan and a proposed design are written. **No RTL exists yet, on purpose**: the design should be agreed first.
- Section 4 lists six decisions (D1–D6). Once they are answered, the next step is a detailed, task-level implementation plan and the week-1 work.

## 1. The brief, condensed

Source: [Jane Street blog post](https://blog.janestreet.com/protocol-emulator-asic-competition/).

- **Build** an open-source *protocol emulator*: "a tiny CPU with an instruction set designed for reading pins, writing pins, counting cycles, and hitting timing precisely enough that you can implement a real protocol in firmware rather than in fixed logic." Prior art they name: RP2040 PIO state machines and TI Sitara PRU cores — and they ask how to improve on them.
- **Required protocols:** UART, SPI, I2C. **Stretch:** low-speed USB, 10 Mbit Ethernet. Also of interest: JTAG, SWD, PS/2, CAN.
- **Process:** IHP 130 nm SG13CMOS5L through Tiny Tapeout, starting from the [cmos5l Verilog template](https://github.com/TinyTapeout/ttihp-verilog-template/tree/cmos5l). Maximum **6x4 tiles** (≈0.7 mm² nominal per the post; 0.916 mm² block outline), possibly **8x4** later pending foundry approval.
- **Judging:** projects with *unique functionality* and *novel approaches to design and verification* (formal methods, constrained random, AI-assisted verification are named). Multiple winners; Jane Street pays for tapeout on the **March 2027 CMOS5L shuttle**; winners get chips on dev boards.
- **Teams** strongly encouraged. Building in public is allowed.
- **Sign up:** [Google form](https://docs.google.com/forms/d/e/1FAIpQLSeF7fq756MegxZRQxotBwUJYZx-cL9MrGjxV0z4uD_J0sADxQ/viewform). Contact: asic-competition@janestreet.com.
- **Their advice:** start with a UART transmitter out of a pin, then make it programmable; run synthesis early and check mapped cell area; budget for clock-tree buffers and routing; run the full place-and-route flow to check timing at your chosen clock.

## 2. Hard numbers that shape the design

| Item | Value | Source |
|---|---|---|
| 6x4 tile block | 1289.28 × 710.64 µm = 0.916 mm² | tt-support-tools `ihp-sg13cmos5l` branch, `tech/ihp-sg13cmos5l/tile_sizes.yaml` |
| 1x1 tile | 202.08 × 154.98 µm = 0.031 mm² | same |
| 8x4 | not yet defined for cmos5l (exists for sg13g2: 1724.16 × 710.64 µm) | same |
| Logic budget | ~1K cells per tile → ~24K cells at 6x4, before routing/CTS overhead; default placement density 60 % | blog; template `src/config.json` |
| I/O | 8 inputs `ui_in`, 8 outputs `uo_out`, 8 bidirectional `uio` (+ `clk`, `rst_n`, `ena`) | template `src/project.v` |
| Clock | supplied by the demo board's RP2040: 1 Hz – 66.5 MHz; template default target 50 MHz (`CLOCK_PERIOD` 20 ns) | Tiny Tapeout clock spec; `config.json` |
| Pad speed | ~66 MHz input, ~33 MHz output (documented for sky130 pads; IHP pad figures not on the same page — verify) | Tiny Tapeout GPIO spec |
| SRAM macro | `RM_IHPSG13_1P_1024x8_c2_bm_bist`: 1024×8, single port, synchronous; 146.88 × 336.46 µm (≈1.6 tiles of area, taller than a tile row) | urish/ttihp-sram-test LEF; CMOS5L `sg13cmos5l_sram` is a symlink to the sg13g2 macros |
| Flow of record | GitHub Actions: `tt-gds-action@ihp-cmos5l`, LibreLane 3.1.0.dev3, PDK = IHP-Open-PDK `dev` @ `2bbec75` (2026-09-08) | action.yml |
| Local flow | `tt_tool.py --ihp --harden` (LibreLane in Docker), tests via cocotb 2.0.1 + Icarus | local-hardening guide; template |
| FPGA proxy | Tiny Tapeout FPGA breakout, Lattice iCE40 UP5K (5280 LUTs), €90 kit | tinytapeout.com/guides/fpga-breakout, store |

## 3. Timeline (18 weeks)

Assumes a quarter-system academic calendar (Thanksgiving week Nov 23–27, finals around Dec 7–12, winter break to early January). Shift rows if your calendar differs. Each row has an exit criterion so slippage is visible early.

| Wk | Dates | Theme | Exit criteria |
|---|---|---|---|
| 1 | Sep 15–21 | Sign-up, tools, flow proof | Form submitted; joined Tiny Tapeout Discord; `scripts/setup_env.sh` run; template cocotb test passes locally; a GitHub repo created from the cmos5l template hardens green in Actions; the urish SRAM example re-targeted to the cmos5l action hardens (proves macro viability); FPGA kit ordered; D1–D6 decided |
| 2 | Sep 22–28 | Warm-up + ISA v0 | Hand-written UART TX RTL with a cocotb test (the post's suggested first step); ISA v0 written as one machine-readable file; Python ISA simulator + assembler run "blink" and "UART TX" programs |
| 3–4 | Sep 29–Oct 12 | Core v0 RTL | Fetch/execute, registers, GPIO, WAIT/DELAY/deadline instructions, host load port; differential tests (RTL vs simulator) on random programs; yosys cell count; **first full 6x4 harden** with area and timing numbers |
| 5–6 | Oct 13–26 | UART + SPI in firmware; formal v0 | UART TX/RX and SPI master programs pass against Python protocol models; SymbiYosys proofs for reset safety, static instruction timing, glitch-free pins; instruction-memory decision (SRAM macro vs flip-flops) made from measured area |
| 7–8 | Oct 27–Nov 9 | Pin engines + I2C | Lanes (shift + line coding + CRC) v0; I2C master and slave incl. clock stretching; SPI slave; constrained-random protocol tests; FPGA bring-up; second harden |
| 9–10 | Nov 10–23 | **Required-protocol freeze** | UART, SPI, I2C demonstrated on FPGA against real counterpart devices; coverage report; datasheet (`docs/info.md`) draft; gate-level simulation passes |
| 11–12 | Nov 24–Dec 7 | Low intensity | Bug fixes, docs, CI hygiene, verification write-up skeleton |
| 13 | Dec 8–14 | Finals buffer | Nothing scheduled |
| 14–16 | Dec 15–Jan 4 | Stretch + optimisation | Low-speed USB device enumerates on a PC (fallback: JTAG/SWD); 10BASE-T TX frame captured on a PC; area/timing tuned; move to 8x4 only if approved and useful |
| 17 | Jan 5–11 | Final hardening + docs | Final GDS with timing margin; precheck green; `docs/info.md` complete; README with results table and demo video; methodology write-up |
| 18 | Jan 12–16 | Submit | Tag v1.0; submit by **Fri Jan 15**; Mon Jan 18 is buffer only |

Rule of thumb: whatever exists on **Nov 23** is what gets submitted if the stretch work fails. Everything after that must be additive and reversible.

### Compressed schedule (requested 2026-09-15: "timeline asap")

The 18-week table above is the safe schedule. This is the front-loaded one: everything from weeks 1–4 is pulled into the next 14 days, which moves the required-protocol freeze from Nov 23 to **Nov 2** and leaves all of November and December for stretch protocols, verification depth and the write-up.

| Day | Date | Work | Done when |
|---|---|---|---|
| 1 | Mon Sep 15 | **Done:** toolchain installed and verified; repo scaffolded from the cmos5l template; fixed UART TX + cycle-exact cocotb tests (3/3 pass); Verilator lint clean; three research reports + novelty synthesis; design spec v1. **In progress:** local harden baseline and SRAM-macro trial | `make -B` in `test/` passes; reports in `docs/research/` |
| 2 | Tue Sep 16 | **You:** sign-up form, create the GitHub repo, push. **Me:** local harden of the scaffold on cmos5l (needs Docker), record cells/utilisation/slack baseline; SRAM-macro trial (urish example on the cmos5l action) | `gds`, `test`, `docs` workflows green; baseline numbers in README; macro verdict recorded |
| 3–4 | Wed–Thu Sep 17–18 | Read the three research reports; revise the design spec (novelty choices); ISA v0 as one YAML file; generator → assembler + Python simulator; "blink" and "UART TX" programs run in the simulator | spec v1 approved by you; `asm` and `sim` tools pass their own tests |
| 5–7 | Fri–Sun Sep 19–21 | Core v0 RTL: fetch/execute, registers, ALU, pin ops, `DELAY`/`WAITT`/`WAITP`, instruction memory (flip-flop version first); differential harness RTL vs simulator | UART TX firmware on the core matches the fixed UART TX cycle for cycle |
| 8–10 | Mon–Wed Sep 22–24 | Host SPI port + loader script; UART RX firmware; first **full harden of the core** at 6x4; yosys cell count per block | core hardens; area table in README |
| 11–12 | Thu–Fri Sep 25–26 | SPI master firmware + Python SPI model; first SymbiYosys properties (reset safety, static timing) | proofs pass in CI |
| 13–14 | Sat–Sun Sep 27–28 | Pin engine v0 (shift + divider, NRZ only); I2C master firmware start | lane drives SPI at 12.5 MHz in sim |
| — | Sep 29 – Oct 12 | I2C master + slave, SPI slave, protocol models, constrained-random suite, second harden, FPGA kit arrives → bring-up | |
| — | Oct 13 – Nov 2 | Line coding + CRC in lanes; USB-LS device attempt; gate-level sim; **required-protocol freeze Nov 2** | |
| — | Nov 3 – Dec 14 | 10BASE-T TX, JTAG/SWD, verification depth (mutation, coverage, HIL), docs; light load during finals | |
| — | Dec 15 – Jan 11 | Polish, final hardens, write-up, demo video | |
| — | Jan 12–16 | Submit | |

Dependencies on you in this schedule: the sign-up form and the GitHub repo (day 2), the FPGA kit order (this week), and approving the revised spec (day 4).

## 4. Decisions needed (answer these first)

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | Design language | (a) Verilog/SystemVerilog subset that Yosys accepts; (b) Hardcaml (OCaml) generating Verilog; (c) Amaranth/Chisel | **(a)** by default: mature open tooling (Yosys, Icarus, Verilator, SymbiYosys, cocotb) and the template is Verilog. Consider **(b)** if you or a teammate know OCaml or want the Jane Street tooling story — spend one evening on the Hardcaml tutorial in week 1, then commit. Hardcaml output still drops into the template, and cocotb still tests the generated Verilog. |
| D2 | Team | solo / 2–4 people | **Find at least one collaborator.** Natural split: (1) ISA + RTL, (2) verification (formal + cocotb + models), (3) firmware, assembler and demos, (4) physical flow, FPGA and docs. |
| D3 | Host/firmware-load interface | (a) SPI slave register port; (b) parallel byte load on `ui_in` with a strobe; (c) UART bootloader | **(a)**: any MCU can drive it, including the demo board's RP2040; keeps 20 pins free for protocols. |
| D4 | Buy the FPGA dev kit (€90, ships from the EU) | now / later / never | **Now.** Hardware-in-the-loop with real devices is the most convincing demo and de-risks pin behaviour. Note the UP5K has only 5280 LUTs, so the FPGA build may need a reduced configuration (fewer lanes). |
| D5 | Tile target | 6x4 firm / plan for 8x4 | **6x4 firm.** Treat 8x4 as bonus capacity only if the organisers confirm it. |
| D6 | Headline novelty | (a) time-triggered ISA with formally proven timing; (b) programmable line-coding pin engines making USB and 10BASE-T feasible; (c) device emulation (be an I2C EEPROM / SPI flash / USB keyboard); (d) all three | **(d)** in this order: (a) is the core, (b) is what makes stretch protocols possible, (c) is the demo story. Cut (b)'s scope before touching (a). |

### Decision log

| # | Outcome (2026-09-15) |
|---|---|
| D1 | **Decided: Verilog.** Yosys-compatible Verilog-2005/SystemVerilog subset; Python for models, assembler and generators. |
| D2 | Deferred by you. Plan assumes solo until told otherwise; the Nov 23 freeze is sized for that. |
| D3 | Not discussed; the SPI-slave host port stands as the default. |
| D4 | You will order the FPGA kit. It is not required for submission (see the FPGA note below). Order by mid-October so it arrives before the hardware weeks (7–10). |
| D5 | **Decided: 6x4.** 8x4 is unconfirmed for cmos5l (no 8x4 entry in the cmos5l tile table yet) and the draft design uses roughly a third of 6x4, so extra area would not change the outcome. |
| D6 | Research done (2026-09-15 evening): `docs/research/prior-art-academic.md`, `prior-art-industry.md`, `verification-novelty.md`, distilled into `docs/research/novelty-synthesis.md` with decisions N1–N10. The design spec is now v1 and incorporates them; **N1–N10 and the v1 spec await your approval.** Headline: the timing contract is a machine-checked theorem; lanes carry line coding, bit-stuffing and CRC; contention monitor and edge-timestamp capture; every wait is bounded. |

**FPGA note.** Submission needs only the GDS flow, RTL simulation and gate-level simulation, all of which run without hardware. The kit buys three things: proof against real devices (a PC's USB host or NIC cannot be faked convincingly in simulation), early detection of pin-direction and reset mistakes, and demo footage for the write-up. Its iCE40 UP5K has 5280 LUTs, so the full design may need a reduced configuration (2 lanes, smaller instruction memory in block RAM) to fit; any iCE40 HX8K or ECP5 board with jumper wires is a workable substitute.

## 5. Workstreams

**A. ISA and toolchain.** One machine-readable ISA description (YAML) generates the assembler, the Python simulator's decode table, the Verilog decode constants and the ISA chapter of the docs. This "single source of truth" is both a productivity tool and a verification argument (spec and implementation cannot drift).

**B. RTL.** Core, timebase, pin engines, host port, Tiny Tapeout wrapper. Synthesize with Yosys weekly; harden monthly at minimum.

**C. Verification** (this is a judged category, so it gets a write-up of its own):
1. Differential testing: RTL vs Python ISA simulator on constrained-random programs, with functional coverage.
2. Formal (SymbiYosys): reset safety (all `uio` are inputs until firmware says otherwise), static timing (every non-wait instruction advances the PC every cycle), glitch-free pins (pin outputs change only at instruction boundaries), deadline exactness, FIFO/handshake invariants.
3. Protocol reference models in Python (UART, SPI, I2C, USB-LS, 10BASE-T) checking timing tolerances, not just values.
4. Gate-level simulation of the hardened netlist (the template's `GATES=yes` flow).
5. FPGA hardware-in-the-loop with real parts (I2C sensor/EEPROM, SPI flash, PC serial port, PC USB host, PC NIC).
6. AI-assisted: LLM-generated adversarial programs and property suggestions, with every generated artifact checked in and reproducible. Document the method honestly, including what it found and what it missed.

**D. Physical flow.** GitHub Actions is the flow of record; local `tt_tool.py --harden` for iteration. Track cell count, utilisation, worst slack, and DRC/precheck status per harden in a table in the README.

**E. Firmware and demos.** Assembler, example programs per protocol, a loader script for the demo board's RP2040 (MicroPython SDK), demo scripts and recordings.

**F. Documentation and submission.** `docs/info.md` datasheet, README, architecture doc, verification report, results table, license (Apache-2.0 as in the template).

## 6. Submission checklist

- [ ] Sign-up form submitted (do this in week 1, it is cheap).
- [ ] Public GitHub repo created from `TinyTapeout/ttihp-verilog-template` branch `cmos5l`, Apache-2.0 license kept.
- [ ] `info.yaml`: title, author(s), description, `clock_hz`, `tiles: "6x4"`, unique `tt_um_<github-user>_...` top module, all source files listed, full pinout table.
- [ ] `gds` workflow green: GDS build, precheck, gate-level test, viewer.
- [ ] `test` workflow green; `docs` workflow green; FPGA workflow enabled and green.
- [ ] `docs/info.md`: how it works, how to test, external hardware.
- [ ] README: results table (cells, utilisation, fmax, protocols demonstrated), demo media, verification summary, how to build/run everything.
- [ ] Tagged release; repo link sent via the form (and by email to asic-competition@janestreet.com if the form asks for it).
- [ ] Submitted by Fri 2027-01-15.

## 7. Risks and mitigations

| Risk | Why it matters | Mitigation |
|---|---|---|
| CMOS5L flow is brand new | The GDS action pins a PDK revision; an install-script issue was opened 2026-09-11 (tt-gds-action #52) | Harden in week 1 and every month; watch the Tiny Tapeout Discord; keep the last green GDS run archived |
| SRAM macro on CMOS5L unproven | Instruction memory strategy depends on it | Week 1: re-run the urish SRAM example through the cmos5l action; fallback is a 64–128 word flip-flop instruction memory |
| Docker/LibreLane on Apple Silicon | Local hardening may be slow or fragile; Docker Desktop is currently not running | Treat GitHub Actions as the flow of record; local runs only for iteration; give Docker ≥10 GB RAM |
| Pad speed vs 10BASE-T | 20 MHz Manchester toggling is near the documented ~33 MHz output limit | Keep Ethernet as stretch; measure on FPGA first; USB-LS (1.5 MHz) is the safer stretch goal |
| FPGA too small | UP5K has 5280 LUTs; a full 6x4 design may not fit | Parameterise lanes and memory so a reduced build fits; use FPGA for protocol behaviour, simulation for the full design |
| Scope creep | Stretch goals eat the required ones | Hard freeze on Nov 23; stretch work only on a branch after that |
| Solo bandwidth | 18 weeks across ISA, RTL, verification, flow, firmware, docs | Recruit (D2); if solo, drop lanes to 2 and USB/Ethernet to "designed but not demonstrated" |
| Judging emphasis | "Novel" is subjective | Over-invest in the write-up: explain the timing model, show the formal properties, show real hardware working |

## 8. Environment on this Mac (as of 2026-09-15)

Present: Python 3.10 (system), `uv` 0.12.5 with Python 3.12 available, Homebrew 6.0, Docker 29.6 (daemon not running), git, clang, node 22. Missing: every HDL tool (yosys, iverilog, verilator, sby, gtkwave/surfer), LibreLane, the PDK, opam/OCaml.

What exists now: a project-local `.venv` (Python 3.12) with `cocotb==2.0.1` and `pytest==8.4.2` — the exact versions the template pins.

`scripts/setup_env.sh` installs the rest into `~/ttsetup` (override with `TT_TOOLS_DIR`): OSS CAD Suite 2026-09-15 for arm64 (≈520 MB download), tt-support-tools on the `ihp-sg13cmos5l` branch with its own venv + LibreLane 3.1.0.dev3, and the pinned IHP PDK checkout. Add `--with-hardcaml` for opam + Hardcaml. It writes `env.sh` to source in each shell.

## 9. Week-1 actions, in order

1. Submit the sign-up form; join the Tiny Tapeout Discord (channel for IHP/cmos5l) and the Jane Street contact list.
2. Run the toolchain bootstrap and start Docker Desktop:

   ```bash
   scripts/setup_env.sh
   ```

3. Create the GitHub repo from the template (`cmos5l` branch, "Use this template"), clone it into this folder (or move these docs into it), push, and confirm the `gds`, `test`, `docs` workflows go green on the unmodified example.
4. Fork `urish/ttihp-sram-test`, switch its workflows to `@ihp-cmos5l` with `pdk: ihp-sg13cmos5l`, and see whether the SRAM macro hardens. Record the outcome in the research brief.
5. Order the FPGA dev kit.
6. Read: RP2040 datasheet chapter 3 (PIO), TI PRU-ICSS reference, the BitLoom README (a competitor's PIO-with-deadlines design) — then decide D1–D6 and approve or amend the design spec.
