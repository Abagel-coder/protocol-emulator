; Toggle uo[0] every 10 cycles forever (period 20 cycles):
; TGL(1) + DELAY 6(7) + JMP(1) + delay-slot NOP(1) = 10 cycles per loop.
.equ HALF 6
top:
  TGL UO, 0x01        ; visible next cycle
  DELAY HALF          ; HALF+1 cycles
  JMP top             ; delay slot below executes
  NOP
