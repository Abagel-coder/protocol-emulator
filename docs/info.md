<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

## How it works

Status (2026-09-15): warm-up build. The chip currently contains a fixed-function 8N1 UART transmitter at 115200 baud from a 50 MHz clock (434 clock cycles per bit). It exists to validate the design, test and hardening flow before the programmable protocol-emulator core replaces it.

Final design (in development): a small deterministic CPU whose instruction set is built for reading pins, writing pins, counting cycles and hitting exact timing, plus programmable pin engines for shifting, line coding and CRC. UART, SPI and I2C run as firmware loaded over a host SPI port; low-speed USB and 10BASE-T Ethernet are stretch goals. See the repository's PLAN.md and design spec.

## How to test

Warm-up build:

1. Apply a 50 MHz clock and release reset. TX (`uo[0]`) idles high, BUSY (`uo[1]`) is low.
2. Put the byte to send on `ui[7:0]`.
3. Raise START (`uio[0]`) and hold it until BUSY goes high, then release it.
4. Observe one 8N1 frame at 115200 baud on TX: start bit, eight data bits LSB first, stop bit. BUSY is high for the whole frame (4340 cycles) and falls after the stop bit.

On the Tiny Tapeout demo board, TX on `uo[0]` matches the "UART to USB" option 2 wiring, so a serial terminal on the board's USB port shows the bytes.

## External hardware

None for the warm-up build. The final design uses standard Pmods (UART, SPI, I2C) and, for stretch goals, a USB breakout and a 10BASE-T magnetics module.
