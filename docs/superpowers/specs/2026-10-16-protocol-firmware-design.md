# Plan C: required-protocol firmware with independent reference models — design

Date: 2026-10-16. Status: **drafted by the controller from the owner's 2026-10-01 decision** (plan C = the three required protocols, each with an independent timing-checking reference model); not yet reviewed by the owner. Branch: `protocol-fw`, off `sram-imem` at `a850747`. Nothing in this plan changes the RTL, the ISA or the oracle's semantics.

## 1. Goal

Three firmware programs for the core, each with a reference model that was written from the protocol's own specification (not from the firmware), and a cocotb suite per protocol that runs the firmware on the full chip RTL against that model, cycle by cycle:

| Protocol | Firmware | Reference model | Suite |
|---|---|---|---|
| UART receiver, 115200 baud, 8N1 | `firmware/uart_rx.s` | `tools/refmodels/uart_rx_ref.py` (line stimulus generator + frame-timing checker) | `test/Makefile.uartrx`, `test/test_uart_rx_fw.py` |
| SPI master, modes 0–3, 1 MHz | `firmware/spi_master.s` | `tools/refmodels/spi_slave_ref.py` (slave + edge/phase/setup checker) | `test/Makefile.spifw`, `test/test_spi_fw.py` |
| I2C master, 7-bit address, standard mode 100 kHz | `firmware/i2c_master.s` | `tools/refmodels/i2c_slave_ref.py` (slave + standard-mode timing checker; it also computes the wired-AND bus levels, so the suite needs no testbench of its own) | `test/Makefile.i2cfw`, `test/test_i2c_fw.py` |

Done means: all three suites green in CI; each reference model is shown — by a test that stays in the suite — to reject a timing mutant of its firmware; a datasheet section per protocol in `docs/info.md`; `HANDOFF.md` and `PLAN.md` record the state.

## 2. Decisions that apply to all three

**Pin map.** Protocol pins are `ui[3:0]` (inputs), `uo[6:0]` (outputs) and `uio[7:0]` (bidirectional); `ui[7:4]` and `uo[7]` are the host port.

| Signal | Pin | Direction |
|---|---|---|
| UART TX (existing `firmware/uart_tx.s`) | `uo[0]` | out |
| UART RX | `ui[0]` | in |
| SPI SCK / MOSI / CS_n | `uo[1]` / `uo[2]` / `uo[3]` | out |
| SPI MISO | `ui[1]` | in |
| I2C SDA / SCL | `uio[0]` / `uio[1]` | open-drain: `uio_out` bit stays 0, `OE` set = pull low, `OE` clear = released |

**Timing constants in one place.** Each firmware starts with a header comment stating the clock it was computed for (50 MHz) and one `.equ` block holding every timing constant, with the formula in a comment. The block also holds `.equ PRESCALE n`, the `WRITE_PRESCALE` register value (tick = n+1 cycles) the constants assume. A 50 → 40 MHz change edits that block and nothing else in the file. The tests read `PRESCALE` from the firmware source (a new `tools.asm.constants(text)` helper returns the `.equ` table) and program it over the host port, so the host side cannot drift from the firmware's assumption. Nothing else from the `.equ` block is used by a test: the reference models take their timing from the protocol parameters and the clock frequency, declared once per test module (`CLK_HZ = 50_000_000`), never from the firmware.

**Deadlines.** All waits use `SETT`/`ADDT` relative deadlines (`T` free-runs; its value at start is unspecified). No deadline is ever more than a few hundred ticks ahead. Where the host paces the firmware (SPI and I2C take their commands from the host→core FIFO), the firmware re-anchors with `SETT` after every `POP`, so a slow host can never leave a deadline more than 32,767 ticks behind (which would read as "ahead" and stall).

**Host interface.** Host → core words (`PUSH_FIFO`) carry a command; core → host words (`PUSH`, read by `POP_FIFO`) carry a result. Formats are per protocol below. The FIFOs are 4 entries deep: SPI and I2C wait on `TXE` before pushing a result (the host is driving them, so nothing is lost); UART RX pushes without waiting (a byte that arrives while the FIFO is full is dropped — the host must drain faster than 11,520 bytes/s).

**Reference-model architecture.** Each model is a plain-Python, cycle-stepped object with one method, `step(outputs) -> inputs`: it is given the levels the chip drives in the current cycle and returns the levels it drives for the next one, recording events and timing violations as it goes. The same class runs in two harnesses:

- the **oracle harness** (pytest, `tests/test_fw_*.py`): `tools/sim.py` executes the firmware; the harness feeds the model's levels to `Sim.set_inputs()` two cycles late (the chip's two-flop input synchroniser, the convention of `test/test_diff.py`) and drains `sim.core_to_host` every cycle, timestamping each pushed word. Fast (about a second per test), run by the `tools` workflow;
- the **RTL harness** (cocotb, `test/fw_harness.py`): the full chip through its Tiny Tapeout pins, firmware loaded and prescale set over the host SPI port, one model step per falling clock edge, a monitor on the core→host FIFO push (`user_project.u_core.c2h_push`/`c2h_data`, RTL only) for exact push cycles, and a host-side drain task that keeps reading words back through `POP_FIFO` while the model runs (the FIFO is four entries deep, so without it the core's later pushes would be dropped); every test checks that the drained words equal the monitored ones, which covers the real host path end to end.

A test passes when the model records no violation and the firmware's pushed words (value and cycle window) equal the model's expectation. Both harnesses start `T` away from zero (the RTL by construction; the oracle with `t0 = 0xFF00`, so deadlines cross the 16-bit wrap early).

**Mutant sentinels.** Each suite contains one test that assembles a deliberately broken copy of the firmware (a timing constant changed in the source text, the way `test/test_uart_fw.py` parameterises `LDI R2`) and asserts that the reference model *rejects* it. This keeps "the model is not vacuous" a CI-checked property rather than a review-time claim. The per-task mutants that reviewers must also kill in scratch copies are listed in the plan.

**Tolerances.** The models check against the protocol specification with explicit tolerances stated in the model's docstring: none of them is tuned to a firmware constant. The tolerances leave room for the chip's fixed latencies (pin writes visible the cycle after the instruction; inputs read two cycles late) and the prescaler phase (±1 tick), which together are under 1 % of a UART bit, 4 % of an SPI half period and 1 % of an I2C quarter period.

**What does not change.** `src/`, `isa/`, `tools/sim.py` semantics, `tools/host.py`, the formal proofs. `tools/asm.py` gains only the `constants()` helper.

## 3. UART receiver

**Protocol.** 115200 baud, 8 data bits LSB first, no parity, one stop bit; idle high; the start bit is a falling edge. At 50 MHz one bit is 434.03 cycles. Firmware constants: `PRESCALE 1` (tick = 2 cycles), `BIT 217` (ticks per bit), `HALF 108` (ticks from the detected start edge to the middle of the start bit).

**Firmware behaviour.**
1. Wait for the line to be idle (`WAITP UI, 0, HIGH, R0`), then for the start bit (`WAITP UI, 0, LOW, R0`); both are level waits whose 65,535-tick timeout just rearms them. (A falling-edge wait was the first design: its rearm after a timeout leaves a two-cycle window in which a start edge is missed and the frame is corrupted, found in the Task 1 review; a level wait that rearms still sees the line low.) After a framing error the line is still low, so the idle wait also waits out a break.
2. Arm `R1 = T + HALF` and wait; read the line: if it is high the edge was a glitch — back to 1 (false-start rejection).
3. Eight times: `R1 += BIT`, wait, read the line, shift the bit into the byte LSB first (branch-free: `R7 = 0 - bit`, masked to `0x80`, OR'd into the byte after `SHR`).
4. `R1 += BIT`, wait, read the stop bit. Result word = `{frame_error, data[7:0]}` with bit 8 set when the stop bit read low.
5. `PUSH` the word; back to 1. (After a framing error the line is still low, so the next frame starts at the next real falling edge.)

The sample instants are the detected edge plus 0.5, 1.5, …, 9.5 bits; the only fixed error is the edge-detection latency (synchroniser plus two instructions, about 4 cycles, under 1 % of a bit) and the ±1-tick prescaler phase.

**Reference model** (`UartRxRef(clk_hz, baud)`): a stimulus generator and checker written from the 8N1 definition. `schedule(frames)` takes a list of frames, each a byte plus options, and produces the per-cycle line level and the expected result words:

- a plain frame: start, data LSB first, stop, each exactly `clk_hz / baud` cycles (fractional accumulation, no rounding drift);
- `baud_error=±0.04`: the whole frame at 115200 × (1 ± 4 %) — the receiver must still decode it (the classic 8N1 tolerance budget);
- `probe=True`: every data bit, and the stop bit, carries its value only in the middle quarter of the bit cell (±12.5 % of a bit around the ideal sample point) and its complement elsewhere — a receiver that samples outside that window reads a wrong byte or a false framing error. This is the mid-bit-sampling check. The stop bit's low tail is a deliberate glitch that only a receiver with a false-start check survives, so a probe frame must be followed by at least a quarter bit of idle (the model refuses a shorter gap);
- `stop_low=True`: the stop bit is driven low — expected word has bit 8 set;
- `glitch=n`: a low pulse of `n` cycles (shorter than half a bit) with no frame — nothing may be pushed;
- `gap=n` idle cycles before the frame (0 allowed: back-to-back frames).

The checker (`check(pushes)`) requires exactly the expected words, in order, each pushed within [ideal stop-bit sample − 12.5 % bit, ideal stop-bit sample + 12.5 % bit + 32 cycles], where the ideal sample instant is the start edge plus 9.5 bits at the *nominal* baud rate (a receiver samples on its own clock, so for a frame with a baud error this still lies inside the transmitted stop bit): this pins the stop-bit sample instant for every frame, not only probe frames. The 32 cycles are the push latency after the sample (the firmware's stop-bit handling is under 10 instructions; the bound is loose on purpose and stated in the docstring).

**Tests** (same cases in `tests/test_fw_uart_rx.py` on the oracle and `test/test_uart_rx_fw.py` on the RTL): nominal bytes incl. 0x00, 0xFF, 0x55, 0xAA, back-to-back frames; baud −4 % and +4 %; probe frames; framing error followed by a good frame; a glitch; a long idle gap; one RTL test reads the words back through `POP_FIFO`. Sentinel: `BIT 210` (3 % fast) must be rejected by the probe frames.

## 4. SPI master, modes 0–3

**Protocol.** Mode = {CPOL, CPHA}. CPOL is the idle SCK level. The leading edge of each bit is the edge away from idle; CPHA=0 samples on the leading edge and shifts (changes MOSI) on the trailing one with the first bit set up before the first edge, CPHA=1 shifts on the leading edge and samples on the trailing one. MSB first, 8 bits per byte, CS_n active low for a whole transaction of one or more bytes. Nominal SCK 1 MHz at 50 MHz: firmware constants `PRESCALE 0`, `HALF 25` (ticks per half period), `CSLEAD 25` (CS_n assert → first edge), `CSLAG 25` (last edge → CS_n deassert), `CSIDLE 25` (minimum CS_n high between transactions).

**Host words.** Command (host → core): bits 7:0 = byte to transmit; bit 8 = LAST (deassert CS_n after this byte); bits 10:9 = mode = {CPOL, CPHA}. Every word carries the mode; CPOL (the idle level) is applied when a transaction starts (CS_n high when the word is popped) and CPHA is read from each word, so the host must keep the mode constant within a transaction. Result (core → host): bits 7:0 = the byte received on MISO during that byte; one result per command, pushed after the byte's last edge.

**Firmware behaviour.** `uo` resets to 0, so the first instruction raises CS_n. Then forever: wait for a command (`WAITF RXV`), pop it, re-anchor `SETT R1`. If CS_n is high (new transaction): set SCK to the CPOL idle level, lower CS_n, `R1 = T + CSLEAD`. Per byte, with `R1` the time of the first half-step:

- half-step X at `R1`: for CPHA=1 (and for every bit after the first in both modes) toggle SCK; set MOSI to the next bit (`SETR` from bit 7, then `SHL`);
- half-step Y at `R1 + HALF`: toggle SCK (the sampling edge); read MISO (`IN`, which returns the synchronised pin, i.e. its level about two cycles before the edge — within any slave's hold time) and shift it into the result MSB first; `R1 += HALF`.

So for CPHA=0 the first bit enters the loop at the MOSI step (no toggle: SCK is idle and MOSI is set up a half period before the first edge) and the byte ends with one more toggle at `R1` to return SCK to idle; for CPHA=1 the byte enters at the toggle and ends on its sampling edge with SCK already idle. Then `PUSH` the result after a `WAITF TXE` in a retry loop (a single timed wait would give up after 65,535 ticks and the push would drop the word). If LAST: wait `CSLAG`, raise CS_n, wait `CSIDLE`. Otherwise wait for the next word (SCK stays idle between bytes; the gap is at least one period and otherwise set by the host).

**Reference model** (`SpiSlaveRef(clk_hz, sck_hz, mode, miso_bytes, miso_window=None)`): an SPI slave written from the mode definitions, which also judges the master:

- SCK must sit at the transaction's CPOL at CS_n's falling edge, between its bytes and at its rising edge; while CS_n is high (checked from the first time it is seen high after reset — `uo` resets low) SCK may change level at most once, the switch to the next transaction's CPOL;
- the first edge after CS_n falls must be the leading edge for the mode and come at least `CSLEAD_MIN = clk_hz / sck_hz / 2 − 2` cycles after it; the last edge must precede CS_n's rise by at least the same; every edge-to-edge interval within a byte is `clk_hz / sck_hz / 2 ± 1` cycles (the master is deadline-driven, so the tolerance is the prescaler phase only); between bytes the gap may be longer but SCK must stay idle;
- MOSI is sampled at the sampling edge of each bit and must be stable from `P/4` cycles before it to `P/4` after (setup/hold, `P` = the nominal period); the byte is assembled MSB first;
- MISO is driven MSB first from `miso_bytes`: each bit becomes valid `t_co = 5` cycles after the shifting edge (for CPHA=0 the first bit `t_co` after CS_n falls) and holds until the next shifting edge. With `miso_window = w`, the bit is valid only within ±`w` cycles of the sampling edge and its complement elsewhere (default off; the tests use `w = P/8`): the sampling-edge check;
- a transaction must contain a multiple of 16 edges; the model records the MOSI bytes it received and the CS_n assert/deassert cycles. With the window on, the first bit of every CPHA=0 byte (whose sampling edge follows a host-paced gap and cannot be predicted from an earlier edge) is windowed on one side only: valid from its shifting event until the actual sampling edge plus `w`, then the complement. CS_n must also stay high at least `CSLEAD_MIN` cycles between transactions, and a transaction still open at the end of a run, or one with no SCK edges, is a violation (`finish()`).

**Tests** (oracle `tests/test_fw_spi.py`, RTL `test/test_spi_fw.py`): for each of the four modes, a three-byte transaction with asymmetric data (0x81, 0x3C, 0xA5 out; 0xC3, 0x0F, 0x96 back) with the MISO window on; two consecutive transactions with a mode change between them; a single-byte transaction; a transaction whose words arrive late (gap between bytes); one RTL test reads the results back through `POP_FIFO`. Sentinel: `HALF 27` (an 8 % slow clock) must be rejected in every mode by the edge-interval check. (A swapped CPHA mask is a review mutant: it changes modes 1 and 2 only, and the MISO window and MOSI stability checks must catch it there.)

## 5. I2C master

**Protocol.** Standard mode (I2C-bus specification, UM10204), 7-bit addressing, single master. Standard-mode limits the model checks, converted to cycles from `CLK_HZ`: fSCL ≤ 100 kHz (period ≥ 10 µs), tLOW ≥ 4.7 µs, tHIGH ≥ 4.0 µs, tSU;STA ≥ 4.7 µs, tHD;STA ≥ 4.0 µs, tSU;DAT ≥ 250 ns, tHD;DAT ≤ 3.45 µs, tSU;STO ≥ 4.0 µs, tBUF ≥ 4.7 µs, and SDA may change while SCL is high only as a START or STOP. Firmware constants: `PRESCALE 0`, `Q 128` (quarter of the SCL period, 2.56 µs; period 10.24 µs, low and high 5.12 µs each). Clock stretching is supported up to a timeout and reported; it is detected by reading SCL a few cycles after releasing it.

**Host words.** Command: bits 7:0 = data byte to write, or for a read the ACK control (bit 0 = 1 → answer the byte with NACK, 0 → ACK); bit 8 = START (send a START, or a repeated START, before the byte); bit 9 = STOP (send a STOP after the byte); bit 10 = READ (receive a byte instead of writing one). The address byte is an ordinary write of `addr << 1 | R/W` with START set. Result, one per command: bits 7:0 = the byte written (echo) or read; bit 8 = NACK (the written byte was not acknowledged); bit 9 = TIMEOUT (SCL stayed low for 65,535 ticks after the master released it — 1.3 ms at 50 MHz; the master released both lines and abandoned the rest of the command, including a requested STOP); bit 10 = STRETCHED (a slave held SCL low after the master released it, but it rose before the timeout; the transfer completed with the high period re-timed from the observed rise).

**Firmware behaviour.** State between commands: SCL held low in the middle of a transaction, or both lines released when idle. Forever: wait for a command, pop, `SETT R1` (re-anchor), clear the status bits. Then, on a grid of quarter periods counted from `R1`:

- START (if bit 8): release SDA at +Q; release SCL at +2Q and wait for it to be high (`scl_hi`, below); pull SDA low 2Q after the rise (tSU;STA); pull SCL low 2Q later (tHD;STA). From idle the first two steps are no-ops that only space the START.
- Write bit (SDA level in the carry flag, from `SHL` of the data register): at +Q set SDA (pull low for 0, release for 1: tHD;DAT = Q, tSU;DAT = Q); at +2Q `scl_hi`; 2Q after the rise pull SCL low.
- Read bit: at +Q release SDA; at +2Q `scl_hi`; Q after the rise read SDA (`IN`); 2Q after the rise pull SCL low.
- A write byte is eight write bits then a read bit (the ACK; its value becomes result bit 8). A read byte is eight read bits then a write bit (the ACK control from command bit 0).
- STOP (if bit 9): at +Q pull SDA low; at +2Q `scl_hi`; 2Q after the rise release SDA (tSU;STO); wait 2Q more (tBUF) before the next command is processed.
- `scl_hi`: release SCL; after five cycles (the pull-up is immediate in the model, the released level is on the pin the cycle after the instruction and the synchroniser needs two more) read SCL — if it is still low set STRETCHED; `WAITP UIO, 1, HIGH, R0`; on timeout jump to the abort path (release both lines, set TIMEOUT, push the result, back to the command loop — return addresses left on the call stack by the abandoned routines are harmless: the stack keeps the four most recent and later calls overwrite them); otherwise `SETT R1` at the rise.
- `WAITF TXE`, `PUSH` the result.

The SCL high time is measured from the observed rise (minus the five-cycle detection latency, 100 ns) so the standard-mode minimums hold with and without stretching; the period is 10.24 µs so fSCL stays under 100 kHz.

**Reference model** (`I2cSlaveRef(clk_hz, address, read_data, ...)`): a slave written from the bus definition, which also judges the master. It watches the wired-AND bus levels and drives its own two pull-downs:

- bus decoding: START/repeated START (SDA falls while SCL high), STOP (SDA rises while SCL high), bits sampled on SCL rising edges, nine-bit bytes; any other SDA change while SCL is high is a violation;
- timing: every interval of the standard-mode table above, measured on the bus (so a stretched low still satisfies tLOW), reported with the violating cycle;
- slave behaviour: ACKs its own address (either R/W), NACKs any other; stores written bytes; serves `read_data` on reads and stops driving after a NACK from the master; options `nack_data_after=n` (NACK the n-th written byte), `stretch_after_byte=(k, cycles)` (hold SCL low for `cycles` after the ACK bit of byte `k`; longer than the master's 65,535-tick timeout is the timeout case), and the wired-AND of the master's and its own pull-downs, which is what the chip's `uio_in` is driven with;
- records every byte with its direction and ACK, and the START/STOP cycles.

**Tests** (oracle `tests/test_fw_i2c.py`, RTL `test/test_i2c_fw.py`): write 2 bytes to address 0x50 with STOP; read 2 bytes (ACK, then NACK + STOP); write-then-repeated-START-read (the EEPROM pattern); address NACK (0x51) reported in bit 8; data NACK reported; stretch of 20 µs after the address ACK — transfer correct, STRETCHED set on that command only; stretch forever — TIMEOUT set, lines released, and the next command (a START) succeeds once the slave lets go; one RTL test reads results back through `POP_FIFO`. Sentinel: `Q 96` (tLOW 3.84 µs) must be rejected by the timing checker.

## 6. Documentation and CI

- `docs/info.md`: a "Protocol firmware" section with the pin map, one subsection per protocol (constants and the prescale, host word formats, what the reference model checks, the suite and test names, the measured firmware size in words), and the clock-change note (the `.equ` block per file, plus `CLK_HZ` in the tests).
- `.github/workflows/test.yaml`: three new steps after the UART equivalence step, each with its own `COCOTB_RESULTS_FILE` and `grep failure` guard; the `tools` workflow's pytest step already runs the oracle tests. `README.md` "What CI runs" and `test/README.md` list the new suites.
- `HANDOFF.md`, `PLAN.md`: state, suite counts, decision log entry for plan C.

## 7. Out of scope

SPI slave, I2C slave, multi-master arbitration, I2C general call / 10-bit addressing, SMBus timeouts, UART parity or other frame formats, FPGA bring-up, lanes, any RTL change. A clock change to 40 MHz is applied by editing the `.equ` blocks and `CLK_HZ` once the owner decides; the design makes that a one-place edit but does not pre-compute the values.
