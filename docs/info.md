<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

## How it works

Status (2026-10-15): core v0.1 plus the 512x16 SRAM instruction memory (branch `sram-imem`, hardening in CI). The chip is a small deterministic CPU (`pe_core`) built for reading pins, writing pins, counting cycles and hitting exact timing, plus a timebase counter, a GPIO block, two host/core data FIFOs and an instruction memory, all wired together and loaded/controlled over a host SPI port (`pe_host_spi`). Data flow at reset: the host writes a program into the instruction memory over the SPI port, then starts the core; each cycle the core fetches from the instruction memory, executes (ALU, branches, pin reads/writes, waits keyed off the free-running timebase, or a push/pop of a host FIFO), and any pin writes go out through the GPIO block, which also synchronises pin reads. The host can read back status, GPIO and popped FIFO words at any time over the same SPI port, whether or not the core is running.

```
host (SPI) --> pe_host_spi --> pe_imem (512x16 SRAM)         pe_timebase (T, free-running)
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

The instruction memory is 512 x 16 bits, one IHP single-port SRAM macro (`RM_IHPSG13_1P_512x16_c2_bm_bist`): `WRITE_IMEM` addresses and jump/call targets are taken modulo 512, so a program must fit in 512 words (`tools/asm.py` refuses larger ones). It has no reset -- a word the host never wrote holds a random value on silicon -- so load all 512 words (zero-filling the unused ones) before starting the core. The macro has one port, shared between the core's fetch and the host's writes: a `WRITE_IMEM` word that arrives while the core is active (running, including stalled in a wait) is dropped and recorded in `READ_STATUS` bit 5 until the next `WRITE_CTRL` reset; pause the core (RUN low and `WRITE_CTRL` run=0: either one holds it active) or let it `HALT` before loading.

## Host loader protocol

Mode-0 SPI slave, MSB first, one command byte followed by its payload; CS_n must stay asserted through the SPI clock edge that samples a byte's last bit. SCK must run at clk/16 or slower.

| Cmd | Value | Payload (host -> chip) | Response (chip -> host, if any) |
|---|---|---|---|
| `WRITE_IMEM` | 0x01 | start address (2 bytes, hi then lo; the memory uses the low 9 bits, so addresses alias modulo 512) then instruction words (2 bytes each, hi then lo); address auto-increments per word | -- |
| `WRITE_CTRL` | 0x02 | 1 byte: bit0 = run, bit1 = reset (restarts PC at 0) | -- |
| `READ_STATUS` | 0x03 | -- | 4 bytes: status (bit0 halted, bit1 running, bit2 h2c-FIFO valid/non-empty, bit3 c2h-FIFO empty, bit4 h2c-FIFO full, bit5 imem write dropped), PC[9:8], PC[7:0], flags[2:0] (bit0 = Z, bit1 = C, bit2 = TO) |
| `PUSH_FIFO` | 0x04 | 2 bytes (hi, lo): word pushed to the host->core FIFO (dropped if full) | -- |
| `POP_FIFO` | 0x05 | -- | 2 bytes (hi, lo): word popped from the core->host FIFO (0 if empty) |
| `READ_GPIO` | 0x06 | -- | 5 bytes: `ui_in`, `uio_in`, `{1'b0,uo_out}`, `uio_out`, `uio_oe` (all synchronised snapshots) |
| `WRITE_PRESCALE` | 0x07 | 1 byte: timebase divider -- the timebase T ticks once every (value + 1) clock cycles, so 0 (the reset value) means a tick every clock cycle | -- |

Status bit4 (h2c-FIFO full) lets the host poll before a `PUSH_FIFO` instead of racing a silent drop; the FIFO is 4 entries deep.

`ui[7]` (RUN) is also a direct, asynchronous top-level input: asserting it starts the core exactly like `WRITE_CTRL`'s run bit, and either one holds the core active until deasserted. Because `ui[7]` is asynchronous, it passes through the GPIO block's two-flop input synchroniser before reaching the core's own registered RUN sample -- three clock cycles total from a RUN pin transition to the first instruction executing (2 sync flops + 1 core RUN register). `WRITE_CTRL`'s run bit is already a register in the clock domain and takes effect one cycle sooner (both latencies are pinned by `test/test_host.py::run_latency_pin_three_cycles_ctrl_two`). Deasserting RUN (or `WRITE_CTRL` run=0) pauses the core where it is -- registers, PC and any wait in progress are kept -- and reasserting it resumes; `WRITE_CTRL` bit1 restarts at PC 0 and is the only way to restart a core that has executed `HALT` (RUN alone does not). `tools/host.py` provides Python encoders for `WRITE_IMEM`, `WRITE_CTRL` and `WRITE_PRESCALE` (`encode_write_imem`, `encode_write_ctrl`, `encode_write_prescale`; the read and FIFO commands are sent as plain byte strings) plus a cocotb `SpiMaster`, both used throughout `test/test_host.py`.

Caveats worth knowing when driving the port:

- `READ_STATUS` returns the PC in two bytes read 16 SCK edges apart; while the core is running the two halves can come from different cycles, so the PC is only coherent when the status byte says halted (or the core is paused).
- The timebase `T` free-runs from reset, whatever the core does. While RUN is low (or the core is halted) a wait in progress keeps its deadline but `T` keeps counting. A `WAITT` whose deadline passes meanwhile completes in the first cycle after RUN returns, provided `T` is then at most 32,767 ticks past the deadline (`test/test_host.py::run_low_across_deadline_resumes_immediately`); after a longer pause the deadline can count as ahead again -- only the 16-bit difference `T - Rn` is compared -- and the `WAITT` then waits up to 32,768 ticks for `T` to reach it (32,768 ticks is about 655 us at 50 MHz with prescale 0, about 168 ms with prescale 255). A timed wait (`WAITP`/`WAITF`) whose captured timeout passes meanwhile times out only when `T` comes round to it again, up to 65,536 ticks later, so do not pause a core across a timeout it needs.
- `WRITE_PRESCALE` takes effect on the next clock. If the new value is below the prescaler's current count, that one tick interval stretches to as many as 256 clocks (the 8-bit counter runs on to 255 and wraps before matching the new value); later ticks are exact.

## Protocol firmware

Protocols are implemented in firmware: the core reads and writes the protocol pins against exact timebase deadlines, and each firmware program is tested on the chip RTL against a reference model written from the protocol's own definition (not from the firmware). Protocol pins are `ui[3:0]` (inputs), `uo[6:0]` (outputs) and `uio[7:0]` (bidirectional); `ui[7:4]` and `uo[7]` belong to the host port.

| Signal | Pin | Direction |
|---|---|---|
| UART TX (`firmware/uart_tx.s`) | `uo[0]` | out |
| UART RX (`firmware/uart_rx.s`) | `ui[0]` | in |
| SPI SCK / MOSI / CS_n | `uo[1]` / `uo[2]` / `uo[3]` | out |
| SPI MISO | `ui[1]` | in |
| I2C SDA / SCL | `uio[0]` / `uio[1]` | open-drain: `uio_out` bit stays 0, `OE` set = pull low, `OE` clear = released |

**Timing constants.** Each firmware file states the clock it was computed for (50 MHz) in its header comment and keeps every timing constant in one `.equ` block at the top, each with its formula; no timing number appears anywhere else in the file. The block also holds `.equ PRESCALE n`, the `WRITE_PRESCALE` value (one tick = n+1 cycles) the constants assume. The tests read `PRESCALE` from the firmware source (`tools.asm.constants()`) and program it over the host port, so the host side cannot drift from the firmware; nothing else in the block is used by a test: the reference models take their timing from the protocol parameters and `CLK_HZ = 50_000_000`, declared at the top of each test module. Retargeting a firmware to another clock (e.g. 40 MHz) is one edit to its `.equ` block (and `CLK_HZ` in its tests). All waits are `SETT`/`ADDT` relative deadlines, since `T`'s value at start is unspecified.

### UART receiver (firmware/uart_rx.s)

8N1 at 115200 baud on `ui[0]`, 36 instruction words. Constants: `PRESCALE 1` (tick = 2 cycles), `BIT 217` (ticks per bit = 50e6 / 115200 / 2), `HALF 108` (ticks from the detected start edge to the middle of the start bit: 108.5 truncated, and the two-cycle edge-detection latency recentres the sample). The firmware waits for the line to be high (idle), then for it to be low (the start bit), as two level waits (`WAITP ... HIGH` then `WAITP ... LOW`, each with the 65,535-tick timeout that simply rearms it): a level wait that rearms still sees a start bit that arrived meanwhile, where an edge wait would miss it, and the idle wait also waits out a break after a framing error. It then samples the middle of the start bit and goes back to waiting if the line is high again (false-start rejection), then samples the eight data bits (LSB first) and the stop bit at the detected edge plus 1.5, 2.5, ... 9.5 bits. Each frame is pushed to the core->host FIFO as one word: `{frame_error[8], data[7:0]}`, bit 8 set when the stop bit read low; read it with `POP_FIFO`. The push does not wait for room: a frame that arrives while the 4-entry FIFO is full is dropped, so the host must drain faster than 11,520 words/s. The push comes 6 to 9 cycles after the ideal stop-bit sample instant (start edge + 9.5 bits) in the test cases (oracle and RTL).

The reference model (`tools/refmodels/uart_rx_ref.py`) generates the line and checks the pushed words. A frame passes when exactly the expected words are pushed, in order, each within [ideal stop sample - bit/8, ideal stop sample + bit/8 + 32 cycles] (the stop sample measured at the nominal baud rate, so this pins the sample instant on every frame). The cases: nominal bytes (0x55, 0x00, 0xFF, 0xAA, 0xA3, back to back); a whole frame at 115200 x (1 - 4 %) and x (1 + 4 %); probe frames, whose data bits and stop bit carry their value only within +-bit/8 of the ideal sample instant and the complement elsewhere (so sampling outside the middle quarter of a bit reads a wrong byte or a false framing error; the stop bit's low tail is a deliberate glitch the receiver must reject, so the model requires at least a quarter bit of idle after a probe frame); a framing error (stop bit low, bit 8 set) followed by a good frame; a 100-cycle glitch (nothing may be pushed) followed by a good frame; a 140,000-cycle idle gap (the idle wait times out once and rearms). On the oracle only, a scan of gaps around 130,871 cycles, where the earlier falling-edge design missed the start bit while its timed-out wait rearmed, checks the level waits do not.

Suite: `test/Makefile.uartrx` (`test/test_uart_rx_fw.py`: `uart_rx_nominal`, `uart_rx_slow_4pct`, `uart_rx_fast_4pct`, `uart_rx_probe`, `uart_rx_framing`, `uart_rx_glitch`, `uart_rx_long_idle`, and `uart_rx_sentinel_mutant_is_rejected`, which assembles the firmware with `BIT 210` (3 % fast) and requires the model to reject it). Every case also reads the words back over `POP_FIFO` while it runs and checks them against the monitored pushes. The same cases run on the Python oracle in `tests/test_fw_uart_rx.py`.

### SPI master (firmware/spi_master.s)

SPI master, modes 0-3, SCK 1 MHz at 50 MHz, MSB first, 8 bits per byte; 69 instruction words. Pins: SCK `uo[1]`, MOSI `uo[2]`, CS_n `uo[3]` (active low), MISO `ui[1]`. Constants: `PRESCALE 0` (tick = 1 cycle), `HALF 25` (ticks per SCK half period = 50e6 / 1e6 / 2), `CSLEAD 25` (CS_n low to the first half-step), `CSLAG 25` (last SCK edge to CS_n high), `CSIDLE 25` (minimum CS_n high between transactions).

| Mode | CPOL (idle SCK) | CPHA | MOSI changes on | MISO/MOSI sampled on |
|---|---|---|---|---|
| 0 | 0 | 0 | falling (trailing) edge; first bit set up before the first edge | rising (leading) edge |
| 1 | 0 | 1 | rising (leading) edge | falling (trailing) edge |
| 2 | 1 | 0 | rising (trailing) edge; first bit set up before the first edge | falling (leading) edge |
| 3 | 1 | 1 | falling (leading) edge | rising (trailing) edge |

The host drives it byte by byte through the FIFOs. Command word (`PUSH_FIFO`): bits 7:0 the byte to send, bit 8 LAST (raise CS_n after this byte), bits 10:9 the mode {CPOL, CPHA}. CPOL is applied when a transaction starts (CS_n high when the word is popped), CPHA is read from every word, so keep the mode constant within a transaction. Result word (`POP_FIFO`): bits 7:0 the byte read on MISO during that byte, one per command, pushed after the byte's last edge (the firmware waits for room, so nothing is dropped). On the first command of a transaction the firmware sets SCK to the CPOL level, lowers CS_n and anchors its deadlines there; every SCK edge is a `WAITT` deadline, so within a byte the edges are exactly `HALF` ticks apart in every mode. Between bytes SCK stays idle until the next command arrives (the firmware re-anchors after each `POP`, so a slow host only lengthens the gap). MISO is read with `IN`, i.e. the pin as it was about two cycles before the sampling edge. Measured on the oracle and the RTL: the first edge comes 52 cycles after CS_n falls in modes 0/2 (MOSI set up 25 cycles before it) and 27 cycles in modes 1/3; CS_n rises 25 (modes 0/2) or 50 (modes 1/3) cycles after the last edge.

The reference model (`tools/refmodels/spi_slave_ref.py`) is an SPI slave written from the mode definitions that also judges the master; its tolerances come from the nominal period P = 50 cycles (H = 25), never from the firmware: SCK at CPOL when CS_n falls, between bytes and when it rises, and at most one SCK change (the CPOL switch) while CS_n is high; first edge at least H - 2 after CS_n falls, last edge at least H - 2 before it rises; every edge-to-edge interval within a byte H +- 1, between bytes at least H - 1; MOSI stable from P/4 before to P/4 after every sampling edge; a whole number of bytes (16 edges each) per transaction. It drives MISO MSB first, each bit valid 5 cycles after its shifting edge; in the window tests a bit is valid only within +-P/8 = 6 cycles of its predicted sampling edge and the complement elsewhere, so a master that samples on the wrong edge reads a wrong byte (a CPHA=0 byte's first bit, whose sampling edge follows a host-paced gap, is driven plainly).

Suite: `test/Makefile.spifw` (`test/test_spi_fw.py`: `spi_mode0` .. `spi_mode3` (bytes 0x83, 0x1C, 0xA6 out and 0xC1, 0x0F, 0x9A back in one transaction, none of them the same bit-reversed, MISO window on), `spi_mode_change` (a mode-0 transaction then a two-byte mode-3 one), `spi_single_byte` (mode 2), `spi_late_words` (3,000 cycles between commands), and `spi_sentinel_mutant_is_rejected`, which assembles the firmware with `HALF 27` (an 8 % slow SCK) and requires the model to reject it). Each case pushes its commands over `PUSH_FIFO`, reads the results back over `POP_FIFO` while it runs and checks them against the monitored pushes, and checks that every edge interval within a byte is exactly `HALF`. The same cases run on the Python oracle in `tests/test_fw_spi.py`, which also tests the model itself on synthetic master traces.

## How to test

1. Apply the clock and release reset with `ui[7]` (RUN) held low and CS_n high. After reset the core is halted, `uio_oe == 0`, and all outputs are 0 (`test/test_host.py::post_reset_state_and_running_bit` checks this on the pins).
2. Load a program with `WRITE_IMEM` (all 512 words, see above), then start it with `WRITE_CTRL` (run=1) or by raising `ui[7]`. After a `HALT`, restart with `WRITE_CTRL` run=1, reset=1.
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
