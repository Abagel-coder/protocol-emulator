"""Cycle-accurate reference model of the protocol-emulator core v0.

One call to step() is one clock cycle. The instruction at self.pc executes during the
cycle; registered outputs (uo, uio_out, uio_oe) change at the end of the cycle. Waits
re-execute the same instruction every cycle until they complete. There is one branch
delay slot. This model is the oracle for test/test_diff.py, so keep it simple and literal.
"""
from collections import deque
from tools import isa_defs as D

MASK16 = 0xFFFF

def _f(word, cls, field):
    msb, lsb = D.LAYOUTS[cls][field]; return (word >> lsb) & ((1 << (msb - lsb + 1)) - 1)

def _s(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v

class Sim:
    def __init__(self, words, prescale=1, imem_words=64):
        self.imem = [0] * imem_words
        for i, w in enumerate(words): self.imem[i] = w & MASK16
        self.prescale = prescale; self.presc_cnt = 0
        self.pc = 0; self.next_pc = 1; self.regs = [0] * 8; self.T = 0
        self.flags = {"Z": 0, "C": 0, "TO": 0}; self.stack = []
        self.uo = 0; self.uio_out = 0; self.uio_oe = 0; self.ui = 0; self.uio_in = 0
        self.prev_ui = 0; self.prev_uio_in = 0
        self.halted = False; self.cycle = 0
        self.host_to_core = deque(); self.core_to_host = deque()
        self.wait_state = None          # per-instruction wait bookkeeping (deadline / counter)
        self.pending = []               # output updates applied at end of cycle

    # ---- helpers -------------------------------------------------------------
    def set_inputs(self, ui=None, uio_in=None):
        if ui is not None: self.ui = ui & 0xF
        if uio_in is not None: self.uio_in = uio_in & 0xFF

    def _in_bank(self, bank):
        return {0: self.ui, 1: self.uio_in, 2: self.uo, 3: self.uio_out}[bank]

    def _pin_level(self, bank, pin):
        return ((self.uio_in if bank else self.ui) >> pin) & 1

    def _prev_pin_level(self, bank, pin):
        return ((self.prev_uio_in if bank else self.prev_ui) >> pin) & 1

    def _flag(self, fid):
        # fid 0/1/2 = RXV/TXE/TO; reserved ids (3+) always read as 0 (see isa.yaml semantics.flag_ids).
        return {0: 1 if self.host_to_core else 0, 1: 1 if len(self.core_to_host) < 4 else 0, 2: self.flags["TO"]}.get(fid, 0)

    def _setz(self, v): self.flags["Z"] = 1 if (v & MASK16) == 0 else 0

    def _write(self, rd, v):
        if rd != 0: self.regs[rd] = v & MASK16

    def _tick_T(self):
        self.presc_cnt += 1
        if self.presc_cnt >= self.prescale:
            self.presc_cnt = 0; self.T = (self.T + 1) & MASK16

    def _deadline(self, rt):
        n = self.regs[rt] if rt else 0xFFFF
        return (self.T + n) & MASK16

    # ---- one cycle -----------------------------------------------------------
    def step(self):
        trace = (self.cycle, self.uo, self.uio_out, self.uio_oe)
        if not self.halted:
            self._execute(self.imem[self.pc % len(self.imem)])
        for fn in self.pending: fn()
        self.pending = []
        self.prev_ui, self.prev_uio_in = self.ui, self.uio_in
        self._tick_T(); self.cycle += 1
        return trace

    def run(self, cycles):
        return [self.step() for _ in range(cycles)]

    def _advance(self, target=None):
        """Finish the instruction at pc: pc <- next_pc, next_pc <- target or pc+1."""
        self.wait_state = None
        self.pc, self.next_pc = self.next_pc, (target if target is not None else (self.next_pc + 1) & ((1 << D.PC_BITS) - 1))

    def _execute(self, w):
        cls = w >> 12; C = D.CLASSES
        if cls == C["MISC"]:
            sub = _f(w, "MISC", "sub")
            if sub == D.MISC_SUB["HALT"]: self.halted = True; return
            if sub == D.MISC_SUB["RET"]:
                tgt = self.stack.pop() if self.stack else 0; self._advance(tgt); return
            self._advance(); return                                  # NOP, IRQ (no-op in v0)
        if cls == C["LDI"]:
            rd, hi, imm = _f(w, "LDI", "rd"), _f(w, "LDI", "hi"), _f(w, "LDI", "imm8")
            v = ((imm << 8) | (self.regs[rd] & 0xFF)) if hi else imm
            self._write(rd, v); self._setz(v); self._advance(); return
        if cls == C["ALU"]:
            rd, rs, fn = _f(w, "ALU", "rd"), _f(w, "ALU", "rs"), _f(w, "ALU", "fn")
            a, b = self.regs[rd], self.regs[rs]; F = D.ALU_FN
            if fn == F["MOV"]: v = b; self._write(rd, v); self._setz(v)
            elif fn == F["ADD"]: v = a + b; self.flags["C"] = v >> 16; self._write(rd, v); self._setz(v)
            elif fn in (F["SUB"], F["CMP"]):
                v = a + ((~b) & MASK16) + 1; self.flags["C"] = v >> 16; self._setz(v)
                if fn == F["SUB"]: self._write(rd, v)
            elif fn == F["AND"]: v = a & b; self._write(rd, v); self._setz(v)
            elif fn == F["OR"]: v = a | b; self._write(rd, v); self._setz(v)
            elif fn == F["XOR"]: v = a ^ b; self._write(rd, v); self._setz(v)
            elif fn == F["SHL"]: self.flags["C"] = a >> 15; v = a << 1; self._write(rd, v); self._setz(v)
            elif fn == F["SHR"]: self.flags["C"] = a & 1; v = a >> 1; self._write(rd, v); self._setz(v)
            elif fn == F["ROR"]: self.flags["C"] = a & 1; v = (a >> 1) | ((a & 1) << 15); self._write(rd, v); self._setz(v)
            elif fn == F["BITT"]: self._setz(a & b)
            self._advance(); return
        if cls == C["ADDI"]:
            rd = _f(w, "ADDI", "rd"); v = self.regs[rd] + (_s(_f(w, "ADDI", "simm9"), 9) & MASK16)
            self.flags["C"] = v >> 16; self._write(rd, v); self._setz(v); self._advance(); return
        if cls == C["PIN"]:
            op, bank, mask = _f(w, "PIN", "op"), _f(w, "PIN", "bank"), _f(w, "PIN", "mask"); P = D.PIN_OP
            def apply():
                if op == P["OE"]: self.uio_oe = (self.uio_oe | mask) if bank else (self.uio_oe & ~mask & 0xFF); return
                cur = self.uio_out if bank else self.uo
                new = {P["SET"]: cur | mask, P["CLR"]: cur & ~mask & 0xFF, P["TGL"]: cur ^ mask}[op]
                if bank: self.uio_out = new & 0xFF
                else: self.uo = new & 0x7F
            self.pending.append(apply); self._advance(); return
        if cls == C["SETR"]:
            rn, bank, pin, bit = (_f(w, "SETR", f) for f in ("rn", "bank", "pin", "bit"))
            lvl = (self.regs[rn] >> bit) & 1
            def apply():
                if bank: self.uio_out = (self.uio_out & ~(1 << pin) & 0xFF) | (lvl << pin)
                # uo pin 7 is reserved (routed to the host SPI MISO line, see docs/info.md /
                # isa.yaml semantics.pins): matches pe_gpio.v's `pin_idx != 3'd7` guard. PIN
                # SET/CLR/TGL never hit this because uo is masked to 7 bits on every write;
                # SETR needs the same guard since it targets a single bit directly.
                elif pin != 7: self.uo = (self.uo & ~(1 << pin) & 0x7F) | (lvl << pin)
            self.pending.append(apply); self._advance(); return
        if cls == C["IN"]:
            rd, bank = _f(w, "IN", "rd"), _f(w, "IN", "bank"); v = self._in_bank(bank)
            self._write(rd, v); self._setz(v); self._advance(); return
        if cls == C["WAIT"]:
            sub = _f(w, "WAIT", "sub"); W = D.WAIT_SUB
            if sub == W["WAITT"]:
                if self.T == self.regs[_f(w, "WAIT", "rn")]: self._advance()
                return
            if sub == W["DELAY"]:
                if self.wait_state is None: self.wait_state = _f(w, "WAIT", "imm9")
                if self.wait_state == 0: self._advance()
                else: self.wait_state -= 1
                return
            rt = _f(w, "WAIT", "rt")
            if self.wait_state is None: self.wait_state = self._deadline(rt)
            if sub == W["WAITP"]:
                bank, pin, cond = _f(w, "WAIT", "bank"), _f(w, "WAIT", "pin"), _f(w, "WAIT", "cond"); K = D.WAITP_COND
                lvl, prev = self._pin_level(bank, pin), self._prev_pin_level(bank, pin)
                done = {K["LOW"]: lvl == 0, K["HIGH"]: lvl == 1, K["RISE"]: lvl == 1 and prev == 0, K["FALL"]: lvl == 0 and prev == 1}[cond]
            elif sub == W["WAITF"]:
                done = self._flag(_f(w, "WAIT", "flag")) == 1
            else:
                done = True                                              # WAITL: lanes not in v0
            if done: self.flags["TO"] = 0; self._advance()
            elif self.T == self.wait_state: self.flags["TO"] = 1; self._advance()
            return
        if cls == C["TIME"]:
            rd, op, imm = _f(w, "TIME", "rd"), _f(w, "TIME", "op"), _f(w, "TIME", "imm8")
            base = self.T if op == D.TIME_OP["SETT"] else self.regs[rd]
            self._write(rd, base + imm); self._advance(); return
        if cls == C["BR"]:
            cond, off = _f(w, "BR", "cond"), _s(_f(w, "BR", "simm9"), 9); B = D.BR_COND; Z, Cf, TO = self.flags["Z"], self.flags["C"], self.flags["TO"]
            # cond 6/7 are reserved (3-bit field, 6 mnemonics defined): never taken, matching
            # pe_core.v's br_take default (isa.yaml semantics.branches).
            take = {B["BZ"]: Z, B["BNZ"]: not Z, B["BC"]: Cf, B["BNC"]: not Cf, B["BTO"]: TO, B["BNTO"]: not TO}.get(cond, False)
            self._advance((self.pc + 1 + off) & 0x3FF if take else None); return
        if cls == C["JMP"]:
            call, tgt = _f(w, "JMP", "call"), _f(w, "JMP", "target")
            if call:
                self.stack.append((self.pc + 2) & 0x3FF); self.stack = self.stack[-4:]
            self._advance(tgt); return
        if cls == C["BPIN"]:
            level, bank, pin, off = (_f(w, "BPIN", f) for f in ("level", "bank", "pin", "simm7"))
            self._advance((self.pc + 1 + _s(off, 7)) & 0x3FF if self._pin_level(bank, pin) == level else None); return
        if cls == C["BFLAG"]:
            level, flag, off = (_f(w, "BFLAG", f) for f in ("level", "flag", "simm6"))
            self._advance((self.pc + 1 + _s(off, 6)) & 0x3FF if self._flag(flag) == level else None); return
        if cls == C["HOST"]:
            r, pop = _f(w, "HOST", "r"), _f(w, "HOST", "pop")
            if pop:
                if self.host_to_core: self._write(r, self.host_to_core.popleft())
                else: self._write(r, 0)
            elif len(self.core_to_host) < 4: self.core_to_host.append(self.regs[r])
            self._advance(); return
        self._advance()                                                  # LANE / RSV = NOP
