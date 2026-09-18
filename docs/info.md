<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

## How it works

Status (2026-09-17): core v0 wired to the pins. The chip is the protocol-emulator core (`pe_core`) plus a timebase, GPIO block, host FIFOs and instruction memory, all loaded and controlled over a host SPI port (`pe_host_spi`). The warm-up fixed UART transmitter (`uart_tx.v`) is no longer on the pins; it stays in `src/` unreferenced until a fixed-firmware UART test (Task 8) exercises it as a loaded program instead.

Final design (in development): a small deterministic CPU whose instruction set is built for reading pins, writing pins, counting cycles and hitting exact timing, plus programmable pin engines for shifting, line coding and CRC. UART, SPI and I2C run as firmware loaded over a host SPI port; low-speed USB and 10BASE-T Ethernet are stretch goals. See the repository's PLAN.md and design spec.

## How to test

The core is programmed and controlled entirely over a mode-0 SPI slave port on the dedicated pins: `ui[4]` SCK, `ui[5]` MOSI, `ui[6]` CS_n (active low), `uo[7]` MISO. SCK must run at clk/16 or slower. `ui[7]` is a direct RUN input (asserting it also starts the core); `ui[3:0]` and `uo[6:0]` are the protocol pins the loaded program drives and reads, and `uio[7:0]` is the bidirectional bank.

RUN pin synchronisation: `ui[7]` is an asynchronous top-level input. On chip it passes through the GPIO block's two-flop input synchroniser before reaching the core's own registered RUN sample, so it takes three clock cycles total from a RUN pin transition to the first instruction executing (2 sync flops + 1 core RUN register). `WRITE_CTRL`'s run bit does not need this synchroniser (it is already a register in the clock domain) and takes effect one cycle sooner.

1. Apply the clock and release reset with `ui[7]` (RUN) held low and CS_n high. After reset the core is halted, `uio_oe == 0`, and all outputs are 0.
2. Load a program: with CS_n low, clock out `WRITE_IMEM` (0x01), the 10-bit start address as two bytes, then the instruction words two bytes each (big-endian); the on-chip address counter auto-increments after each word.
3. Start the core either by sending `WRITE_CTRL` (0x02) with the run bit set, or by raising `ui[7]` directly; either one keeps the core active until deasserted. Send `WRITE_CTRL` with the reset bit set to restart the program from PC 0.
4. Optionally set the timebase divider with `WRITE_PRESCALE` (0x07), push/pop the host FIFOs with `PUSH_FIFO` (0x04) / `POP_FIFO` (0x05), and poll `READ_STATUS` (0x03, returns a status byte -- bit0 halted, bit1 running, bit2 host->core FIFO valid, bit3 core->host FIFO empty, bit4 host->core FIFO full -- followed by PC and ALU flags) or `READ_GPIO` (0x06, returns a synchronised snapshot of `ui`, `uio_in`, `uo_out`, `uio_out`, `uio_oe`).
5. Observe the protocol pins (`ui[3:0]`, `uo[6:0]`, `uio[7:0]`) driven by the loaded program according to its own timing.

`tools/host.py` provides Python encoders for these commands and a cocotb `SpiMaster` used by `test/test_host.py`, which demonstrates the full load-run-read cycle.

## External hardware

None for the warm-up build. The final design uses standard Pmods (UART, SPI, I2C) and, for stretch goals, a USB breakout and a 10BASE-T magnetics module.
