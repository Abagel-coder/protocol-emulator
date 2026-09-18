; 8N1 UART TX on uo[0], 434 cycles per bit (prescale 2 -> 217 ticks), byte in R2.
; Frame: idle(1), start(0), d0..d7, stop(1). Deadline-driven: no drift.
;
; uo resets to 0 (see pe_gpio.v), which is the same level as the start bit, so without an
; explicit idle-high period the pin would never show a real edge going into the start bit --
; a receiver (or a test comparing against uart_tx.v's fixed transmitter, which idles high out
; of reset) would have nothing to synchronise on, and an all-zero data byte would produce no
; edge at all before the stop bit. So the very first thing this firmware does is raise the
; line and hold it for one full bit-time before asserting the start bit, exactly like every
; other bit boundary below: deadline (ADDT), then the pin write, then wait for the deadline.
.equ BIT 217
  LDI  R2, 0x55        ; test byte
  LDI  R3, 8            ; data bit counter
  SETT R1, 0            ; R1 = now
  ADDT R1, BIT           ; deadline: idle period ends / start bit begins
  NOP                     ; pad so this SETT-anchored bit takes as many cycles to its edge as
  NOP                     ; every WAITT-anchored one below (matches the BNZ+delay-slot latency)
  SET  UO, 0x01            ; idle high, for exactly one bit-time
  WAITT R1
  NOP                       ; pad to match the loop's BNZ+delay-slot overhead
  NOP                       ; so every later bit boundary is the same distance past its WAITT release
  ADDT R1, BIT
  CLR  UO, 0x01              ; start bit
  WAITT R1
  NOP
  NOP
bits:
  ADDT R1, BIT
  SETR UO, 0, R2, 0    ; uo[0] = R2 bit 0
  SHR  R2              ; next bit
  ADDI R3, -1
  WAITT R1
  BNZ  bits
  NOP
  ADDT R1, BIT
  SET  UO, 0x01        ; stop bit
  WAITT R1
  HALT
  NOP
