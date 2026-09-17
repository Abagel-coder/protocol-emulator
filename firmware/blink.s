; Toggle uo[0] every 8 cycles forever (period 16 cycles).
.equ HALF 6
top:
  TGL UO, 0x01        ; visible next cycle
  DELAY HALF          ; HALF+1 cycles
  JMP top             ; delay slot below executes
  NOP
