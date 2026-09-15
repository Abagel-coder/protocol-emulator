![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/fpga/badge.svg)

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
| 2026-09-15 | Repo scaffolded from the `cmos5l` template; fixed 8N1 UART transmitter (`src/uart_tx.v`) with cycle-exact cocotb tests (3/3 passing locally on Icarus) as the warm-up block; local toolchain installed and verified |

Results table (cells, utilisation, worst slack, protocols demonstrated) will be filled from the first hardening run.

## Layout

```
src/        Verilog sources (list every file in info.yaml and test/Makefile)
test/       cocotb testbench (tb.v) and tests (test.py)
docs/       datasheet text, research, design specs
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

RTL simulation:

```bash
cd test && make -B
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

## License

Apache-2.0, see [LICENSE](LICENSE).
