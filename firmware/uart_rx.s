; 8N1 UART receiver at 115200 baud on ui[0]; each frame is pushed to the host as
; {frame_error[8], data[7:0]} through the core->host FIFO (PUSH; dropped if the host lets it fill).
; The start bit is found with level waits (line high, then line low), not an edge wait, so a start
; bit that lands while a timed-out wait rearms is still seen.
; Computed for a 50 MHz clock. All timing lives in the .equ block below (retargeting the clock: see docs/info.md, "Protocol firmware").
.equ PRESCALE 1       ; WRITE_PRESCALE value the constants assume: one tick = PRESCALE+1 = 2 cycles
.equ BIT      217     ; ticks per bit  = 50e6 / 115200 / 2 = 217.0
.equ HALF     108     ; ticks to the middle of the start bit: BIT / 2 = 108.5 truncated; the ~2-cycle edge-detection latency recentres the sample
  LDI  R5, 0x01       ; RX pin mask (ui[0])
  LDI  R6, 0x80       ; a received bit enters at bit 7; SHR moves earlier bits down (LSB first)
frame:
  WAITP UI, 0, HIGH, R0   ; idle line first (also waits out a break after a framing error); timeout rearms
  BTO  frame
  NOP
start:
  WAITP UI, 0, LOW, R0    ; the start bit: a level wait, so an edge that lands while the timed-out wait rearms is still caught
  BTO  start
  SETT R1, HALF           ; delay slot: R1 = middle of the start bit (harmless when rearming)
  WAITT R1
  IN   R4, UI
  AND  R4, R5             ; Z: still low -> a real start bit
  BNZ  frame              ; high again: a glitch
  LDI  R3, 8              ; delay slot: data bit counter (the branch already decided on AND's Z)
  LDI  R2, 0
bit:
  ADDT R1, BIT            ; next sample instant: edge + 1.5, 2.5, ... 8.5 bits
  WAITT R1
  IN   R4, UI
  AND  R4, R5             ; R4 = 0 or 1
  LDI  R7, 0
  SUB  R7, R4             ; R7 = 0x0000 or 0xFFFF
  AND  R7, R6             ; R7 = 0x00 or 0x80
  SHR  R2
  OR   R2, R7
  ADDI R3, -1
  BNZ  bit
  NOP
  ADDT R1, BIT            ; middle of the stop bit
  WAITT R1
  IN   R4, UI
  AND  R4, R5             ; Z: stop bit low -> framing error
  BNZ  push
  NOP
  LDIH R2, 0x01           ; result bit 8
push:
  PUSH R2
  JMP  frame
  NOP
