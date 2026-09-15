# Competition Research Brief (collected 2026-09-15)

Everything below was read from primary sources on 2026-09-15. Re-verify dates and tool versions before submission; the CMOS5L flow is moving weekly.

## Competition

- Announcement: https://blog.janestreet.com/protocol-emulator-asic-competition/
- Sign-up form: https://docs.google.com/forms/d/e/1FAIpQLSeF7fq756MegxZRQxotBwUJYZx-cL9MrGjxV0z4uD_J0sADxQ/viewform
- Contact: asic-competition@janestreet.com
- Deadline: 2027-01-18. Fabrication: March 2027 CMOS5L Tiny Tapeout shuttle (subject to foundry schedule), paid by Jane Street. Winners receive chips on dev boards.
- Required: UART, SPI, I2C. Stretch: low-speed USB, 10 Mbit Ethernet. Also mentioned: JTAG, SWD, PS/2, CAN.
- Selection: "unique functionality" and "novel approaches to design and verification methodologies" (formal, constrained random, AI-assisted named).
- Teams strongly encouraged; open development allowed; all submissions must be open source.
- Prior art they cite: RP2040 PIO state machines, TI Sitara PRU cores.
- Jane Street recommends Hardcaml (https://hardcaml.org, docs at https://docs.hardcaml.org) but requires the Verilog template as the submission format.
- Related earlier puzzle: https://blog.janestreet.com/can-you-reverse-engineer-an-asic/
- Hiring links from the post: https://www.janestreet.com/technology/

## Tiny Tapeout / IHP CMOS5L platform

- Template (branch `cmos5l`): https://github.com/TinyTapeout/ttihp-verilog-template/tree/cmos5l
  - `info.yaml` (yaml_version 6): title, author, `tiles`, `top_module` (must start with `tt_um_`), `source_files`, full pinout table.
  - `src/project.v`: ports `ui_in[7:0]`, `uo_out[7:0]`, `uio_in/uio_out/uio_oe[7:0]`, `ena`, `clk`, `rst_n`.
  - `src/config.json`: `CLOCK_PERIOD` 20 ns, `PL_TARGET_DENSITY_PCT` 60, hold margins, linter on.
  - `test/`: cocotb 2.0.1 + pytest 8.4.2, Icarus, `make -B` (RTL) and `make -B GATES=yes` (gate level, needs `PDK_ROOT/ihp-sg13cmos5l/libs.ref/...`).
  - Workflows: `gds` (build + precheck + gl_test + viewer) via `TinyTapeout/tt-gds-action@ihp-cmos5l` with `pdk: ihp-sg13cmos5l`; `test`; `docs`; `fpga` (ICE40UP5K bitstream, disabled by default).
  - Devcontainer: Ubuntu 24.04, iverilog, verilator, gtkwave, LibreLane, 10 GB RAM hint.
- GDS action (`ihp-cmos5l` branch): tt-support-tools ref `ihp-sg13cmos5l`, LibreLane `3.1.0.dev3`, PDK installed by `install_sg13cmos5l.sh` from IHP-Open-PDK `dev` at commit `2bbec755dc67ca3db0261c3d6163e15735d66710` (2026-09-08). Open issue about newer PDK layout: https://github.com/TinyTapeout/tt-gds-action/issues/52 (opened 2026-09-11).
- tt-support-tools `ihp-sg13cmos5l` branch, `tech/ihp-sg13cmos5l/tile_sizes.yaml` (µm, "x0 y0 x1 y1"):

  | tiles | size |
  |---|---|
  | 1x1 | 202.08 × 154.98 |
  | 2x2 | 419.52 × 313.74 |
  | 4x4 | 854.40 × 710.64 |
  | 6x4 | 1289.28 × 710.64 |
  | 8x2 | 1724.16 × 313.74 |
  | 8x4 | (not defined for cmos5l yet; sg13g2 has 1724.16 × 710.64) |

  Useful `tt_tool.py` flags: `--ihp`, `--create-user-config`, `--harden`, `--no-docker`, `--print-stats`, `--print-cell-summary`, `--print-warnings`, `--create-png`, `--open-in-openroad`, `--open-in-klayout`, `--create-tt-submission`.
- Local hardening guide: https://tinytapeout.com/guides/local-hardening/ (Python ≥3.11, Docker running, macOS: `brew install libpng qhull cairo`, `PDK=ihp-...`, `pip install librelane==$LIBRELANE_TAG`, `./tt/tt_tool.py --ihp --create-user-config` then `--harden`).
- Specs: clock https://tinytapeout.com/specs/clock/ (RP2040-generated, 1 Hz–66.5 MHz, ≤10 ns insertion delay); GPIO https://tinytapeout.com/specs/gpio/ (26 pins per project; ~66 MHz in / ~33 MHz out documented for sky130 pads; ~20 ns worst-case mux latency; 3.3 V, not 5 V tolerant); memory https://tinytapeout.com/specs/memory/ (≈320 DFF per tile; latch RAM 64 B/tile; IHP SRAM options 1024x8, 512x32, 1024x32 single-port; dual-port 1024x16/1024x32); pinouts https://tinytapeout.com/specs/pinouts/ (UART to USB: `ui_in[3]` RX / `uo_out[4]` TX; Pmod SPI on `uio[0..3]`; I2C `uio[2]` SCL / `uio[3]` SDA).
- SRAM example: https://github.com/urish/ttihp-sram-test (sg13g2, 2x2 tiles). Macro `RM_IHPSG13_1P_1024x8_c2_bm_bist`, LEF size 146.88 × 336.46 µm; config needs `MACROS` block, `PDN_MACRO_CONNECTIONS`, custom `pdn_cfg.tcl` (Metal4↔TopMetal1), `MAGIC_MACRO_STD_CELL_SOURCE: PDK`, `ERROR_ON_MAGIC_DRC: false`, `MAGIC_EXT_ABSTRACT_CELLS`. Behavioural model in `test/models/`. In the CMOS5L PDK, `libs.ref/sg13cmos5l_sram` is a symlink to `../../ihp-sg13g2/libs.ref/sg13g2_sram`, so the same macros are what is offered.
- PDK repos: https://github.com/IHP-GmbH/IHP-Open-PDK (branch `dev` has `ihp-sg13cmos5l/libs.ref/{sg13cmos5l_io, sg13cmos5l_sram, sg13cmos5l_stdcell}`), https://github.com/IHP-GmbH/ihp-sg13cmos5l (standalone copy).
- FPGA: https://tinytapeout.com/guides/fpga-breakout/ (iCE40 UP5K breakout, pin-compatible with the demo board; `tt_fpga.py harden` / `configure --upload`; bitstreams selected from the RP2040 SDK). Kit: https://store.tinytapeout.com/products/FPGA-Development-Kit-p813805747 (€90, two PCBs, preliminary firmware needs an update on arrival).
- FAQ: https://tinytapeout.com/faq/ (≈1000 gates per tile; chips take 6–9 months plus assembly; demo board + breakout arrive assembled).
- Discord: https://tinytapeout.com/discord

## Tools (versions seen on 2026-09-15)

- OSS CAD Suite release 2026-09-15: `oss-cad-suite-darwin-arm64-20260915.tgz` (521 MB) — yosys, iverilog, verilator, nextpnr, sby, surfer, gtkwave. https://github.com/YosysHQ/oss-cad-suite-build/releases
- Homebrew alternatives: icarus-verilog 13.0, yosys 0.69, verilator 5.052, opam 2.5.2.
- Hardcaml install (from docs): `opam install hardcaml hardcaml_waveterm ppx_hardcaml core utop dune`; dune library needs `(preprocess (pps ppx_jane ppx_hardcaml))`. Extra packages of interest: `hardcaml_verilator`, `hardcaml_step_testbench`.
- LibreLane docs: https://librelane.readthedocs.io/en/latest/reference/configuration.html

## Competitor landscape (public repos found 2026-09-15)

| Repo | Approach | Status / notes |
|---|---|---|
| https://github.com/sheehanmunim/bitloom | 4 PIO-style state machines with an absolute-time "deadline" register, 8 opcodes, SPI host port, 64-word flip-flop IMEM, Python reference models, small Yosys SAT proofs; written with an AI pair programmer | Most complete found; UART/SPI/I2C/WS2812/Manchester firmware shipped; USB/Ethernet not done |
| https://github.com/kdp1965/ihp-um-janestreet-prism | PRISM programmable state machines + TinyQV RISC-V, SRAM FIFO macros, custom PDN scripts, 8x4 target | Active; heavy on physical-design work |
| https://github.com/Vedant817/ProtocolGremlin | Small CPU, 19 opcodes, 4 registers, differential-tested against a Python model | v0 bootstrap; no protocols yet |
| https://github.com/derek-suwho/protocol-emulator-asic | 8-bit accumulator CPU, 64×16 IMEM, 12-bit WAIT counter, shift-register config loading | Early |
| https://github.com/2AMLogic/sg13cmos5l-protocol-emulator | Spec-first, "agent-native" development, klt/Yosys/OpenROAD vs LibreLane decision pending | Nothing designed yet |
| https://github.com/mtanneer/janestreet.asic.protocol-emulator, https://github.com/Tfloow/JaneStreet-chip | Templates | Empty |

Takeaways: deadline-based timing already exists in one entry (BitLoom), so the differentiators must be the *provable* timing model, the programmable line-coding lanes (nobody has USB or Ethernet working), device-emulation demos on real hardware, and the quality of the verification story.
