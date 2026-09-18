"""Random-program differential test: RTL (tb_core) vs tools.sim.Sim, cycle by cycle.

Inputs driven in cycle k reach the core's synchronised inputs in cycle k+2, so the model is
fed the RTL's input history delayed by two cycles. ui_in is driven with the full 8-bit raw
value (not masked to 4 bits) on both sides: the oracle's set_inputs() masks to ui[3:0] itself
(matching pe_core.v's `ui_eff = {4'b0, ui_sync[3:0]}` -- ui[7:4] are host lines, never protocol
pins), so this exercises that masking on both sides instead of assuming it away by never
setting the high bits.

The instruction mix below is deliberately wide: reserved/undefined field encodings are
generated on purpose, not avoided, because every RTL/model divergence found by earlier rounds
of this fuzzer was in a reserved encoding (see tests/test_sim.py and the task-7 report) --
ALU fn now covers the full 4-bit field (0-15, 11-15 reserved), PIN bank the full 2-bit field
(0-3, 2-3 reserved), WAIT sub the full defined-plus-reserved range (1-7), BFLAG flag the full
5-bit field (0-31, 3-31 reserved), and class RSV (fully reserved, all-NOP) is generated too.

Three encodings are still excluded entirely -- each because it can make a random program stall
for very long (or forever) rather than because it's untested; directed tests in test_core.py /
tests/test_sim.py cover them individually:
  - LDIH: never generated (LDI's `hi` field is fixed 0), so every register only ever holds
    small LDI-derived values (0-255, or arithmetic on those). This keeps WAITP/WAITF/WAITL's
    `rt` *register content* (the actual tick count used as a timeout, as opposed to the `rt`
    field below, which only selects which register) from occasionally landing near 65535.
  - WAITT (WAIT sub=0): excluded from the sub choices below. WAITT stalls until T == Rn
    *exactly*; since T is free-running and monotonic, an unlucky Rn makes a random program
    hang for the rest of the run.
  - HALT (MISC sub=1): excluded from the MISC sub choices below, so programs keep running for
    the full N_CYCLES budget instead of parking early and wasting fuzz coverage. `halted` is
    still compared every cycle alongside the pin trace (see the `got`/`exp` tuples below) --
    cheap, and it means a spurious HALT decode reachable from any reserved encoding would
    still be caught immediately, even though HALT itself is never intentionally generated.

WAIT timeouts are also biased to keep the run from being dominated by pointless stalls: `rt`
(the register selected as the timeout, bits [8:6]) is drawn from 1-7, never R0 (R0 reads as
zero, which WAIT's own convention treats as "no timeout register" -> a 65535-tick wait); and
for WAITF specifically, the flag id is drawn with a 70% bias toward the three defined ids
(RXV/TXE/TO), since a WAITF on an undefined id can otherwise dominate a program's cycle budget
stalled on a flag that can never become true (see the task-7 report's before/after coverage
numbers).
"""
import os, random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from tools import isa_defs as D
from tools.sim import Sim

N_PROGRAMS = int(os.environ.get("DIFF_PROGRAMS", "25"))
N_CYCLES   = int(os.environ.get("DIFF_CYCLES", "1500"))
IMEM_WORDS = 64

def rand_word(rng):
    cls = rng.choices(["LDI", "ALU", "ADDI", "PIN", "SETR", "IN", "WAIT", "TIME", "BR", "JMP", "BPIN", "BFLAG", "HOST", "MISC", "LANE", "RSV"],
                      weights=[10, 12, 6, 12, 6, 5, 10, 6, 6, 3, 4, 2, 2, 2, 1, 1])[0]
    w = D.CLASSES[cls] << 12; r = rng.randrange
    if cls == "LDI":   w |= (r(8) << 9) | r(256)                                   # hi=0 only
    elif cls == "ALU": w |= (r(8) << 9) | (r(8) << 6) | (r(16) << 2)               # fn: 0-15 (11-15 reserved)
    elif cls == "ADDI": w |= (r(8) << 9) | r(512)
    elif cls == "PIN": w |= (r(4) << 10) | (r(4) << 8) | r(256)                    # bank: 0-3 (2-3 reserved)
    elif cls == "SETR": w |= (r(8) << 9) | (r(2) << 8) | (r(8) << 5) | r(16)
    elif cls == "IN":  w |= (r(8) << 9) | (r(4) << 7)
    elif cls == "WAIT":
        sub = rng.choice([1, 2, 3, 4, 5, 6, 7])                        # DELAY, WAITP, WAITF, WAITL, undefined(5-7); 0=WAITT excluded
        w |= sub << 9
        if sub == 1:
            w |= r(65)                                                 # DELAY imm, capped at 64 (bound stall length)
        else:
            rt = 1 + r(7)                                              # rt reg index 1-7 (never R0 == 65535-tick timeout)
            if sub == 3 and rng.random() < 0.7:                        # WAITF: bias toward the 3 defined flag ids
                low6 = rng.choice([0, 1, 2])
            else:
                low6 = r(64)
            w |= (rt << 6) | low6
    elif cls == "TIME": w |= (r(8) << 9) | (r(2) << 8) | r(256)
    elif cls == "BR":  w |= (r(8) << 9) | r(512)
    elif cls == "JMP": w |= (r(2) << 11) | r(IMEM_WORDS)
    elif cls == "BPIN": w |= (r(2) << 11) | (r(2) << 10) | (r(8) << 7) | r(128)
    elif cls == "BFLAG": w |= (r(2) << 11) | (r(32) << 6) | r(64)                  # flag: 0-31 (3-31 reserved)
    elif cls == "HOST": w |= (r(8) << 9) | (r(2) << 8)
    elif cls == "MISC": w |= rng.choice([0, 0, 2, 3, 9])                            # NOP, RET, IRQ, undefined (no HALT: keep programs running)
    elif cls == "RSV": w |= r(4096)                                                 # fully reserved class: any lower bits, always a no-op
    return w

@cocotb.test()
async def rtl_matches_model_on_random_programs(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    for n in range(N_PROGRAMS):
        rng = random.Random(1000 + n)
        words = [rand_word(rng) for _ in range(IMEM_WORDS)]
        for i in range(IMEM_WORDS): dut.u_imem.mem[i].value = words[i]
        dut.prescale.value = 0; dut.run.value = 0; dut.ui_in.value = 0; dut.uio_in.value = 0
        dut.rst_n.value = 0; await ClockCycles(dut.clk, 3); dut.rst_n.value = 1; await ClockCycles(dut.clk, 2)
        dut.run.value = 1; await RisingEdge(dut.clk)
        sim = Sim(words, prescale=1, imem_words=IMEM_WORDS)
        hist = {}
        for k in range(N_CYCLES):
            ui, uio = hist.get(k - 2, (0, 0))
            sim.set_inputs(ui=ui, uio_in=uio)
            exp = sim.step()
            await FallingEdge(dut.clk)
            got = (k, int(dut.uo_out.value), int(dut.uio_out.value), int(dut.uio_oe.value), int(dut.halted.value))
            assert got == exp, f"program {n} cycle {k}: rtl={got} model={exp} pc={int(dut.pc.value)}"
            if rng.random() < 0.15:                                                # change inputs sometimes
                hist[k] = (rng.randrange(256), rng.randrange(256))                 # full 8-bit ui_in: ui[7:4] must be masked away identically on both sides
                dut.ui_in.value = hist[k][0]; dut.uio_in.value = hist[k][1]
            else:
                hist[k] = hist.get(k - 1, (0, 0))
        # sim.regs already reflects cycle (N_CYCLES-1)'s write (Sim._write() is immediate,
        # unlike pin writes which go through self.pending), but the RTL's regs[] only commits
        # that write on the clock edge ending cycle N_CYCLES-1, which the loop above never
        # waits for (its last action was a FallingEdge, mid-cycle). Advance one more full
        # cycle so the RTL side has caught up before comparing final state.
        await RisingEdge(dut.clk); await FallingEdge(dut.clk)
        for i in range(1, 8):
            assert int(dut.u_core.regs[i].value) == sim.regs[i], f"program {n}: R{i} rtl={int(dut.u_core.regs[i].value)} model={sim.regs[i]}"
        f = int(dut.flags.value)
        assert (f & 1, (f >> 1) & 1, (f >> 2) & 1) == (sim.flags["Z"], sim.flags["C"], sim.flags["TO"]), f"program {n}: flags"
