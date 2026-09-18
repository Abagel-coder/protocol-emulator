"""Random-program differential test: RTL (tb_core) vs tools.sim.Sim, cycle by cycle.

Inputs driven in cycle k reach the core's synchronised inputs in cycle k+2, so the model is
fed the RTL's input history delayed by two cycles. LDIH and WAITT are excluded from random
programs (they can stall for 65535 cycles); directed tests in test_core.py cover them.
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
    cls = rng.choices(["LDI", "ALU", "ADDI", "PIN", "SETR", "IN", "WAIT", "TIME", "BR", "JMP", "BPIN", "BFLAG", "HOST", "MISC", "LANE"],
                      weights=[10, 12, 6, 12, 6, 5, 10, 6, 6, 3, 4, 2, 2, 2, 1])[0]
    w = D.CLASSES[cls] << 12; r = rng.randrange
    if cls == "LDI":   w |= (r(8) << 9) | r(256)                                   # hi=0 only
    elif cls == "ALU": w |= (r(8) << 9) | (r(8) << 6) | (r(12) << 2)
    elif cls == "ADDI": w |= (r(8) << 9) | r(512)
    elif cls == "PIN": w |= (r(4) << 10) | (r(2) << 8) | r(256)
    elif cls == "SETR": w |= (r(8) << 9) | (r(2) << 8) | (r(8) << 5) | r(16)
    elif cls == "IN":  w |= (r(8) << 9) | (r(4) << 7)
    elif cls == "WAIT":
        sub = rng.choice([1, 2, 3, 5])                                            # DELAY, WAITP, WAITF, undefined
        w |= sub << 9
        if sub == 1: w |= r(33)
        else: w |= (r(8) << 6) | r(64)
    elif cls == "TIME": w |= (r(8) << 9) | (r(2) << 8) | r(256)
    elif cls == "BR":  w |= (r(8) << 9) | r(512)
    elif cls == "JMP": w |= (r(2) << 11) | r(IMEM_WORDS)
    elif cls == "BPIN": w |= (r(2) << 11) | (r(2) << 10) | (r(8) << 7) | r(128)
    elif cls == "BFLAG": w |= (r(2) << 11) | (r(4) << 6) | r(64)
    elif cls == "HOST": w |= (r(8) << 9) | (r(2) << 8)
    elif cls == "MISC": w |= rng.choice([0, 0, 2, 3, 9])                            # NOP, RET, IRQ, undefined (no HALT: keep programs running)
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
            got = (k, int(dut.uo_out.value), int(dut.uio_out.value), int(dut.uio_oe.value))
            assert got == exp, f"program {n} cycle {k}: rtl={got} model={exp} pc={int(dut.pc.value)}"
            if rng.random() < 0.15:                                                # change inputs sometimes
                hist[k] = (rng.randrange(16), rng.randrange(256))
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
        assert int(dut.halted.value) == int(sim.halted)
