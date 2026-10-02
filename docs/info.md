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

The instruction set (`isa/isa.yaml`, the single source of truth) generates the assembler, the Python reference simulator's decode table, the Verilog decode constants (`src/isa_defs.vh`) and the generated reference below (`docs/isa.md`). `tools/gen_isa.py --check` (run in CI) pins the enumerations, the mnemonic table and the reference to that file; the instruction field positions in `src/pe_core.v` are hand-typed, and their agreement with the ISA is checked by the differential fuzzer (RTL against the Python model, `test/test_diff.py`, also run in CI). Sixteen instruction classes are encoded: fourteen implemented (miscellaneous, immediate loads, ALU, add-immediate, pin set/clear/toggle/output-enable, register-driven pin writes (`SETR`), pin/register reads, waits, timebase read/write, conditional branches, jump/call, pin-gated and flag-gated branches, host-FIFO push/pop) and two reserved. Waits target the timebase (exact tick), a pin level or edge, or a status flag, the latter two with a bounded 16-bit timeout. Every instruction is one cycle except the WAIT class; branches, `JMP`, `CALL` and `RET` have one delay slot. Full mnemonic table, field layouts, symbol tables and semantics: [docs/isa.md](isa.md). The lane class (`LCFG`/`LOUT`/`LIN`/`LARM`/`LCRC`/`LTS`, programmable pin engines for line coding, shifting and CRC) is reserved in the ISA but not yet implemented -- see `PLAN.md`'s decision log for the next plan.

Deadlines are wrap-safe: `WAITT Rn` completes in the first cycle in which bit 15 of the 16-bit difference `T - Rn` is 0. A deadline up to 32,768 ticks ahead of `T` stalls and completes exactly in the cycle `T == Rn`; one that has already passed (up to 32,767 ticks behind -- an overrun loop body, or RUN held low across it) completes at once, in its first cycle or in the first cycle after RUN returns; either way the flags are left untouched. Keep deadlines less than 32,768 ticks ahead of `T` and use the prescaler for longer intervals: a deadline 32,769 to 65,535 ticks ahead is indistinguishable from one that has passed and completes at once. The timed waits (`WAITP`, `WAITF`) keep an exact equality compare: they capture `T + timeout` when they start and time out in the cycle `T` equals it, which is what allows the full 65,535-tick timeout (`Rt = R0`).

The instruction memory is 64 x 16 bits (flip-flops in v0): `WRITE_IMEM` addresses and jump/call targets are taken modulo 64, so a program must fit in 64 words (`tools/asm.py` refuses larger ones). It has no reset -- a word the host never wrote holds a random value on silicon -- so load all 64 words (zero-filling the unused ones) before starting the core.

## Host loader protocol

Mode-0 SPI slave, MSB first, one command byte followed by its payload; CS_n must stay asserted through the SPI clock edge that samples a byte's last bit. SCK must run at clk/16 or slower.

| Cmd | Value | Payload (host -> chip) | Response (chip -> host, if any) |
|---|---|---|---|
| `WRITE_IMEM` | 0x01 | 10-bit start address (2 bytes, hi then lo, top 6 bits of the first ignored) then instruction words (2 bytes each, hi then lo); address auto-increments per word | -- |
| `WRITE_CTRL` | 0x02 | 1 byte: bit0 = run, bit1 = reset (restarts PC at 0) | -- |
| `READ_STATUS` | 0x03 | -- | 4 bytes: status (bit0 halted, bit1 running, bit2 h2c-FIFO valid/non-empty, bit3 c2h-FIFO empty, bit4 h2c-FIFO full), PC[9:8], PC[7:0], flags[2:0] (bit0 = Z, bit1 = C, bit2 = TO) |
| `PUSH_FIFO` | 0x04 | 2 bytes (hi, lo): word pushed to the host->core FIFO (dropped if full) | -- |
| `POP_FIFO` | 0x05 | -- | 2 bytes (hi, lo): word popped from the core->host FIFO (0 if empty) |
| `READ_GPIO` | 0x06 | -- | 5 bytes: `ui_in`, `uio_in`, `{1'b0,uo_out}`, `uio_out`, `uio_oe` (all synchronised snapshots) |
| `WRITE_PRESCALE` | 0x07 | 1 byte: timebase divider -- the timebase T ticks once every (value + 1) clock cycles, so 0 (the reset value) means a tick every clock cycle | -- |

Status bit4 (h2c-FIFO full) lets the host poll before a `PUSH_FIFO` instead of racing a silent drop; the FIFO is 4 entries deep.

`ui[7]` (RUN) is also a direct, asynchronous top-level input: asserting it starts the core exactly like `WRITE_CTRL`'s run bit, and either one holds the core active until deasserted. Because `ui[7]` is asynchronous, it passes through the GPIO block's two-flop input synchroniser before reaching the core's own registered RUN sample -- three clock cycles total from a RUN pin transition to the first instruction executing (2 sync flops + 1 core RUN register). `WRITE_CTRL`'s run bit is already a register in the clock domain and takes effect one cycle sooner (both latencies are pinned by `test/test_host.py::run_latency_pin_three_cycles_ctrl_two`). Deasserting RUN (or `WRITE_CTRL` run=0) pauses the core where it is -- registers, PC and any wait in progress are kept -- and reasserting it resumes; `WRITE_CTRL` bit1 restarts at PC 0 and is the only way to restart a core that has executed `HALT` (RUN alone does not). `tools/host.py` provides Python encoders for `WRITE_IMEM`, `WRITE_CTRL` and `WRITE_PRESCALE` (`encode_write_imem`, `encode_write_ctrl`, `encode_write_prescale`; the read and FIFO commands are sent as plain byte strings) plus a cocotb `SpiMaster`, both used throughout `test/test_host.py`.

Caveats worth knowing when driving the port:

- `READ_STATUS` returns the PC in two bytes read 16 SCK edges apart; while the core is running the two halves can come from different cycles, so the PC is only coherent when the status byte says halted (or the core is paused).
- The timebase `T` free-runs from reset, whatever the core does. While RUN is low (or the core is halted) a wait in progress keeps its deadline but `T` keeps counting. A `WAITT` whose deadline passes meanwhile completes in the first cycle after RUN returns (`test/test_host.py::run_low_across_deadline_resumes_immediately`); a timed wait (`WAITP`/`WAITF`) whose captured timeout passes meanwhile times out only when `T` comes round to it again, up to 65,536 ticks later, so do not pause a core across a timeout it needs.
- `WRITE_PRESCALE` takes effect on the next clock. If the new value is below the prescaler's current count, that one tick interval stretches to as many as 256 clocks (the 8-bit counter runs on to 255 and wraps before matching the new value); later ticks are exact.

## v0 limitations

- No lanes (pin engines) and a 64-word flip-flop instruction memory instead of the SRAM macro (`docs/superpowers/specs/2026-09-15-protocol-emulator-design.md`, implementation-status note).

## How to test

1. Apply the clock and release reset with `ui[7]` (RUN) held low and CS_n high. After reset the core is halted, `uio_oe == 0`, and all outputs are 0 (`test/test_host.py::post_reset_state_and_running_bit` checks this on the pins).
2. Load a program with `WRITE_IMEM` (all 64 words, see above), then start it with `WRITE_CTRL` (run=1) or by raising `ui[7]`. After a `HALT`, restart with `WRITE_CTRL` run=1, reset=1.
3. Observe the protocol pins (`ui[3:0]`, `uo[6:0]`, `uio[7:0]`) driven by the loaded program, and optionally poll `READ_STATUS` / `READ_GPIO` or exchange words with `PUSH_FIFO` / `POP_FIFO`.

Worked example -- `firmware/blink.s` (toggles `uo[0]` every 10 cycles forever):

```
; Toggle uo[0] every 10 cycles forever (period 20 cycles):
; TGL(1) + DELAY 6(7) + JMP(1) + delay-slot NOP(1) = 10 cycles per loop.
.equ HALF 6
top:
  TGL UO, 0x01        ; visible next cycle
  DELAY HALF          ; HALF+1 cycles
  JMP top             ; delay slot below executes
  NOP
```

Assemble it to get the instruction words: `.venv/bin/python tools/asm.py firmware/blink.s` prints the four 16-bit words for PC 0-3, one per line: `4801`, `7206`, `a000`, `0000`.

The exact SPI byte sequence to load and run it (`tools/host.py`'s `encode_write_imem(0, [0x4801, 0x7206, 0xa000, 0x0000])` and `encode_write_ctrl(run=True)`), each row one CS_n-framed transaction, MSB first:

| Step | CS_n | Bytes (hex) | Meaning |
|---|---|---|---|
| 1 | low..high | `01 00 00 48 01 72 06 A0 00 00 00` | `WRITE_IMEM`, start address 0x000, then the 4 program words |
| 2 | low..high | `02 01` | `WRITE_CTRL`, run=1, reset=0 -- the core starts at PC 0 |

After step 2, `uo[0]` toggles every 10 core clocks (20-clock period) indefinitely. `test/test_host.py::datasheet_blink_sequence` exercises this exact sequence end to end in cocotb: it checks the two byte strings above against what `tools/asm.py` and `tools/host.py` produce from `firmware/blink.s`, sends those literal bytes over the SPI pins, and measures the toggle interval on the `uo[0]` pin itself.

## External hardware

None. Loading and control is entirely over the host SPI port on the dedicated pins; any SPI-capable host (including the demo board's RP2040) can drive it. The protocol pins (`ui[3:0]`, `uo[6:0]`, `uio[7:0]`) are free for whatever protocol the loaded firmware implements -- no fixed external hardware is required for the core itself.
