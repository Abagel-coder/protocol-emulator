<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

## How it works

Status (2026-09-18): core v0, hardened. The chip is a small deterministic CPU (`pe_core`) built for reading pins, writing pins, counting cycles and hitting exact timing, plus a timebase counter, a GPIO block, two host/core data FIFOs and an instruction memory, all wired together and loaded/controlled over a host SPI port (`pe_host_spi`). Data flow at reset: the host writes a program into the instruction memory over the SPI port, then starts the core; each cycle the core fetches from the instruction memory, executes (ALU, branches, pin reads/writes, waits keyed off the free-running timebase, or a push/pop of a host FIFO), and any pin writes go out through the GPIO block, which also synchronises pin reads. The host can read back status, GPIO and popped FIFO words at any time over the same SPI port, whether or not the core is running.

```
host (SPI) --> pe_host_spi --> pe_imem_ff (program)          pe_timebase (T, free-running)
                    |                |                               |
                    |                v                               v
                    +----------> pe_core  <---- h2c/c2h pe_fifo ---- (host data queues)
                                     |
                                     v
                                 pe_gpio ---> uo_out[6:0], uio_out/uio_oe[7:0]
                                     ^
                                     | (synchronised)
                          ui_in[3:0], uio_in[7:0]
```

The instruction set (`isa/isa.yaml`, the single source of truth) generates the assembler, the Python reference simulator's decode table, the Verilog decode constants (`src/isa_defs.vh`) and the generated reference below (`docs/isa.md`), so the four can never drift out of sync (`tools/gen_isa.py --check` enforces it in CI). Thirteen instruction classes cover: ALU ops and immediate loads; pin set/clear/toggle/output-enable and register-driven pin writes (`SETR`); pin/register reads; exact-cycle waits on the timebase, a pin level, or a status flag, all with a bounded 16-bit timeout; timebase read/write; conditional and pin/flag-gated branches; absolute jump/call/return; and host-FIFO push/pop. Every instruction is one cycle except the WAIT class; branches, `JMP`, `CALL` and `RET` have one delay slot. Full mnemonic table, field layouts and semantics: [docs/isa.md](isa.md). The lane class (`LCFG`/`LOUT`/`LIN`/`LARM`/`LCRC`/`LTS`, programmable pin engines for line coding, shifting and CRC) is reserved in the ISA but not yet implemented -- see `PLAN.md`'s decision log for the next plan.

## Host loader protocol

Mode-0 SPI slave, MSB first, one command byte followed by its payload; CS_n must stay asserted through the SPI clock edge that samples a byte's last bit. SCK must run at clk/16 or slower.

| Cmd | Value | Payload (host -> chip) | Response (chip -> host, if any) |
|---|---|---|---|
| `WRITE_IMEM` | 0x01 | 10-bit start address (2 bytes, hi then lo, top 6 bits of the first ignored) then instruction words (2 bytes each, hi then lo); address auto-increments per word | -- |
| `WRITE_CTRL` | 0x02 | 1 byte: bit0 = run, bit1 = reset (restarts PC at 0) | -- |
| `READ_STATUS` | 0x03 | -- | 4 bytes: status (bit0 halted, bit1 running, bit2 h2c-FIFO valid/non-empty, bit3 c2h-FIFO empty, bit4 h2c-FIFO full), PC[9:8], PC[7:0], flags[2:0] |
| `PUSH_FIFO` | 0x04 | 2 bytes (hi, lo): word pushed to the host->core FIFO (dropped if full) | -- |
| `POP_FIFO` | 0x05 | -- | 2 bytes (hi, lo): word popped from the core->host FIFO (0 if empty) |
| `READ_GPIO` | 0x06 | -- | 5 bytes: `ui_in`, `uio_in`, `{1'b0,uo_out}`, `uio_out`, `uio_oe` (all synchronised snapshots) |
| `WRITE_PRESCALE` | 0x07 | 1 byte: timebase divider | -- |

Status bit4 (h2c-FIFO full) lets the host poll before a `PUSH_FIFO` instead of racing a silent drop; the FIFO is 4 entries deep.

`ui[7]` (RUN) is also a direct, asynchronous top-level input: asserting it starts the core exactly like `WRITE_CTRL`'s run bit, and either one holds the core active until deasserted. Because `ui[7]` is asynchronous, it passes through the GPIO block's two-flop input synchroniser before reaching the core's own registered RUN sample -- three clock cycles total from a RUN pin transition to the first instruction executing (2 sync flops + 1 core RUN register). `WRITE_CTRL`'s run bit is already a register in the clock domain and takes effect one cycle sooner. `tools/host.py` provides Python encoders (`encode_write_imem`, `encode_write_ctrl`, `encode_write_prescale`) for all of this plus a cocotb `SpiMaster`, both used throughout `test/test_host.py`.

## How to test

1. Apply the clock and release reset with `ui[7]` (RUN) held low and CS_n high. After reset the core is halted, `uio_oe == 0`, and all outputs are 0.
2. Load a program with `WRITE_IMEM`, then start it with `WRITE_CTRL` (run=1) or by raising `ui[7]`.
3. Observe the protocol pins (`ui[3:0]`, `uo[6:0]`, `uio[7:0]`) driven by the loaded program, and optionally poll `READ_STATUS` / `READ_GPIO` or exchange words with `PUSH_FIFO` / `POP_FIFO`.

Worked example -- `firmware/blink.s` (toggles `uo[0]` every 8 cycles forever):

```
; Toggle uo[0] every 8 cycles forever (period 16 cycles).
.equ HALF 6
top:
  TGL UO, 0x01        ; visible next cycle
  DELAY HALF          ; HALF+1 cycles
  JMP top             ; delay slot below executes
  NOP
```

Assemble it to get the instruction words: `.venv/bin/python tools/asm.py firmware/blink.s` prints `4801 7206 a000 0000` (four 16-bit words, PC 0-3).

The exact SPI byte sequence to load and run it (`tools/host.py`'s `encode_write_imem(0, [0x4801, 0x7206, 0xa000, 0x0000])` and `encode_write_ctrl(run=True)`), each row one CS_n-framed transaction, MSB first:

| Step | CS_n | Bytes (hex) | Meaning |
|---|---|---|---|
| 1 | low..high | `01 00 00 48 01 72 06 A0 00 00 00` | `WRITE_IMEM`, start address 0x000, then the 4 program words |
| 2 | low..high | `02 01` | `WRITE_CTRL`, run=1, reset=0 -- the core starts at PC 0 |

After step 2, `uo[0]` toggles every 8 core clocks (16-clock period) indefinitely. `test/test_host.py::load_program_and_run` exercises this exact sequence end to end in cocotb.

## External hardware

None. Loading and control is entirely over the host SPI port on the dedicated pins; any SPI-capable host (including the demo board's RP2040) can drive it. The protocol pins (`ui[3:0]`, `uo[6:0]`, `uio[7:0]`) are free for whatever protocol the loaded firmware implements -- no fixed external hardware is required for the core itself.
