; SPI master, modes 0-3: SCK uo[1], MOSI uo[2], CS_n uo[3], MISO ui[1]. Bytes come from the host
; FIFO: command {CPOL[10], CPHA[9], LAST[8], byte[7:0]}; one result {miso[7:0]} per command.
; CPOL is applied when a transaction starts; CPHA is read from every word. Computed for 50 MHz.
.equ PRESCALE 0       ; one tick = one cycle
.equ HALF     25      ; ticks per SCK half period = 50e6 / 1e6 / 2
.equ CSLEAD   25      ; CS_n low -> first half-step (>= HALF): CPHA=1's first edge; CPHA=0 sets MOSI up there, first edge HALF later
.equ CSLAG    25      ; last SCK edge -> CS_n high for CPHA=0; CPHA=1 adds a half period (the byte's deadline is already past its last edge); >= HALF
.equ CSIDLE   25      ; CS_n high between transactions
  SET  UO, 0x08       ; CS_n idle high (uo resets to 0)
  LDI  R6, 0x02       ; MISO mask (ui[1])
idle:
  WAITF RXV, R0
  BTO  idle
  NOP
  POP  R2             ; first command of a transaction
  LDI  R4, 0x00
  LDIH R4, 0x04       ; CPOL mask
  BITT R2, R4
  BNZ  cpol1
  NOP
  CLR  UO, 0x02       ; CPOL = 0: SCK idle low
  JMP  cs
  NOP
cpol1:
  SET  UO, 0x02       ; CPOL = 1: SCK idle high (one level change while CS_n is high, no glitch)
cs:
  CLR  UO, 0x08       ; CS_n low: transaction starts
  SETT R1, CSLEAD     ; re-anchor at CS_n's fall: first half-step CSLEAD after it
byte:                 ; R2 = command, R1 = this byte's first half-step
  LDI  R7, 0x00
  LDIH R7, 0x03
  AND  R7, R2         ; R7 = command & {CPHA, LAST}
  LDI  R4, 0x00
  LDIH R4, 0x02       ; CPHA mask
  LDI  R5, 8          ; bit counter
  LDI  R3, 0          ; MISO accumulator
  BITT R7, R4         ; Z: CPHA = 0
  BZ   mosi           ; CPHA = 0: the first bit is set up with no edge
bitloop:              ; (the loop re-enters at the delay slot: one WAITT, then the edge)
  WAITT R1            ; delay slot: wait for the first half-step either way
  TGL  UO, 0x02       ; shifting edge (CPHA = 1: leading; CPHA = 0: the previous bit's trailing edge)
mosi:
  SETR UO, 2, R2, 7   ; MOSI = bit 7
  SHL  R2
  ADDT R1, HALF
  WAITT R1
  TGL  UO, 0x02       ; sampling edge
  IN   R4, UI         ; synchronised MISO (its level about two cycles before the edge)
  AND  R4, R6
  SHR  R4             ; -> bit 0
  SHL  R3
  OR   R3, R4
  ADDT R1, HALF
  ADDI R5, -1
  BNZ  bitloop
  NOP
  LDI  R4, 0x00
  LDIH R4, 0x02
  BITT R7, R4         ; Z: CPHA = 0
  BNZ  pushr          ; CPHA = 1: SCK is idle after the last sampling edge
  NOP
  WAITT R1
  TGL  UO, 0x02       ; CPHA = 0: trailing edge of the last bit, back to idle
pushr:
  WAITF TXE, R0       ; retry on timeout: a full FIFO never drops the result
  BTO  pushr
  NOP
  PUSH R3
  LDIH R4, 0x01       ; LAST mask (low byte of R4 is 0)
  BITT R7, R4
  BNZ  last
  NOP
next:
  WAITF RXV, R0       ; next byte of the transaction, SCK idle meanwhile
  BTO  next
  NOP
  POP  R2
  SETT R1, HALF       ; re-anchor: a slow host never leaves a deadline far behind
  JMP  byte
  NOP
last:
  ADDT R1, CSLAG
  WAITT R1
  SET  UO, 0x08       ; CS_n high
  ADDT R1, CSIDLE
  WAITT R1
  JMP  idle
  NOP
