; 8N1 UART TX on uo[0], 434 cycles per bit (prescale 2 -> 217 ticks), byte in R2.
; Frame: start(0), d0..d7, stop(1). Deadline-driven: no drift.
.equ BIT 217
  LDI  R2, 0x55        ; test byte
  LDI  R3, 8           ; data bit counter
  SETT R1, 0           ; R1 = now
  ADDT R1, BIT         ; first deadline (start bit ends)
  CLR  UO, 0x01        ; start bit
  WAITT R1
  NOP                  ; pad to match the loop's BNZ+delay-slot overhead
  NOP                  ; so every bit boundary is the same distance past its WAITT release
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
