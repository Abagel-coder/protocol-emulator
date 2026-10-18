; I2C master, standard mode: SDA uio[0], SCL uio[1], open drain (uio_out bits stay 0; OE set pulls
; low, OE clear releases). Commands from the host FIFO: {READ[10], STOP[9], START[8], data[7:0]}
; (for a read, data bit 0 = 1 answers the byte with NACK). One result per command:
; {STRETCHED[10], TIMEOUT[9], NACK[8], data[7:0]}. Computed for 50 MHz; the quarter-period grid
; below gives tLOW = tHIGH = 2Q, tSU;STA = tHD;STA = tSU;STO = tBUF = 2Q, tHD;DAT = tSU;DAT = Q.
; Measured period 4Q + 11 = 523 cycles = 10.46 us (95.6 kHz), not 4Q: the grid re-anchors at the
; observed SCL rise, about 11 cycles after the release deadline (pin write, input synchroniser,
; WAITP), so tHIGH = 2Q + 9 and tLOW = 2Q + 2; a bus rise time adds to tLOW (period 573 cycles at
; the 1 us standard-mode maximum).
.equ PRESCALE 0       ; one tick = one cycle
.equ Q        128     ; quarter of the SCL period in ticks = ceil(50e6 / 100e3 / 4) + 3 (measured period 10.46 us, under 100 kHz)
.equ TRISE    53      ; ticks a released SCL may take to read back high before it counts as a stretch =
                      ; ceil(1000 ns * 50 MHz) = 50 (UM10204 standard-mode tr max, a 30 %-70 % figure; a released line
                      ; must read back high within 52 cycles = 1.04 us, TRISE 72 would cover the strict reading) + 3 (output
                      ; register and the two-flop input synchroniser)
main:
  WAITF RXV, R0
  BTO  main
  NOP
  POP  R2             ; command
  SETT R1, 0          ; the quarter-period grid starts now
  LDI  R3, 0xFF
  AND  R3, R2         ; R3 = the command's data byte, before anything can abort (an abort in START reports it)
  LDI  R6, 0          ; status bits
  LDI  R4, 0x00
  LDIH R4, 0x01       ; START
  BITT R2, R4
  BZ   nostart
  NOP
  CALL start
  NOP
nostart:
  LDI  R4, 0x00       ; (R4's low byte is not known here: scl_hi loads TRISE)
  LDIH R4, 0x04       ; READ
  BITT R2, R4
  BZ   write
  NOP
  CALL rbyte          ; R3 = byte read, then the ACK bit from command bit 0
  NOP
  JMP  stopq
  NOP
write:
  CALL wbyte          ; writes command[7:0]; R3 = echo; R6 |= NACK
  NOP
stopq:
  LDI  R4, 0x00
  LDIH R4, 0x02       ; STOP
  BITT R2, R4
  BZ   result
  NOP
  CALL stop
  NOP
result:
  OR   R3, R6
txe:                  ; wait for room in the core->host FIFO for as long as it takes (a PUSH
  WAITF TXE, R0       ; into a full FIFO would drop the result)
  BTO  txe
  NOP
  PUSH R3
  JMP  main
  NOP
abort:                ; SCL held low past the timeout: release both lines, report, drop the command
  OE   0, 0x03
  LDI  R4, 0x00
  LDIH R4, 0x01       ; NACK is kept; STRETCHED (set by scl_hi before it waited) is dropped:
  AND  R6, R4         ; it means "a stretch that ended before the timeout"
  LDIH R4, 0x02       ; TIMEOUT
  OR   R6, R4
  JMP  result
  NOP
scl_hi:               ; release SCL, flag a stretch, wait for SCL high, R1 = the rise
  OE   0, 0x02
  LDI  R4, TRISE      ; a bus with the slowest legal rise reads back high within TRISE ticks:
  WAITP UIO, 1, HIGH, R4  ; SCL still low after that is a slave stretching
  BNTO sclok
  NOP
  LDI  R4, 0x00
  LDIH R4, 0x04       ; STRETCHED
  OR   R6, R4
sclok:
  WAITP UIO, 1, HIGH, R0
  BTO  abort
  SETT R1, 0          ; delay slot: the high period counts from the observed rise
  RET
  NOP
wbit:                 ; SDA from Z (Z: pull low; else release), one SCL pulse; R1 = last SCL fall
  ADDT R1, Q
  WAITT R1
  BZ   sda0
  NOP
  OE   0, 0x01        ; SDA released (1)
  JMP  wbit2
  NOP
sda0:
  OE   1, 0x01        ; SDA low (0)
wbit2:
  ADDT R1, Q
  WAITT R1
  CALL scl_hi
  NOP
  ADDT R1, Q
  ADDT R1, Q
  WAITT R1
  OE   1, 0x02        ; SCL low
  RET
  NOP
rbit:                 ; release SDA, one SCL pulse, C = SDA in the middle of the high period
  ADDT R1, Q
  WAITT R1
  OE   0, 0x01
  ADDT R1, Q
  WAITT R1
  CALL scl_hi
  NOP
  ADDT R1, Q
  WAITT R1
  IN   R4, UIO
  SHR  R4             ; C = SDA
  ADDT R1, Q
  WAITT R1
  OE   1, 0x02        ; SCL low (flags untouched from here to the RET)
  RET
  NOP
wbyte:                ; write command[7:0] MSB first, read the ACK
  LDI  R3, 0xFF
  AND  R3, R2         ; R3 = data (the echo)
  MOV  R7, R3         ; shifting copy
  LDI  R5, 8
wloop:
  LDI  R4, 0x80
  BITT R7, R4         ; Z: bit 7 clear -> SDA low
  CALL wbit
  NOP                 ; (the slot must not touch the flags wbit reads)
  SHL  R7
  ADDI R5, -1
  BNZ  wloop
  NOP
  CALL rbit           ; ACK bit -> C
  NOP
  BNC  wret
  NOP
  LDI  R4, 0x00
  LDIH R4, 0x01       ; NACK
  OR   R6, R4
wret:
  RET
  NOP
rbyte:                ; R3 = byte read MSB first; then the ACK bit from command bit 0 (1 = NACK)
  LDI  R3, 0
  LDI  R5, 8
rloop:
  CALL rbit
  NOP
  BC   rone
  SHL  R3             ; delay slot: shift either way (the branch decided on rbit's C)
  JMP  rnext
  NOP
rone:
  ADDI R3, 1
rnext:
  ADDI R5, -1
  BNZ  rloop
  NOP
  LDI  R4, 0x01
  BITT R2, R4         ; Z: ACK requested -> wbit pulls SDA low
  CALL wbit
  NOP
  RET
  NOP
start:                ; (repeated) START: SDA high, SCL high, SDA low after 2Q, SCL low after 2Q
  ADDT R1, Q
  WAITT R1
  OE   0, 0x01
  ADDT R1, Q
  WAITT R1
  CALL scl_hi
  NOP
  ADDT R1, Q
  ADDT R1, Q
  WAITT R1
  OE   1, 0x01        ; SDA falls while SCL is high
  ADDT R1, Q
  ADDT R1, Q
  WAITT R1
  OE   1, 0x02
  RET
  NOP
stop:                 ; STOP: SDA low, SCL high, SDA released after 2Q, then tBUF
  ADDT R1, Q
  WAITT R1
  OE   1, 0x01
  ADDT R1, Q
  WAITT R1
  CALL scl_hi
  NOP
  ADDT R1, Q
  ADDT R1, Q
  WAITT R1
  OE   0, 0x01        ; SDA rises while SCL is high
  ADDT R1, Q
  ADDT R1, Q
  WAITT R1
  RET
  NOP
