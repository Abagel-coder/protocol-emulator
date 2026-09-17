import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from tools.asm import assemble

def load(dut, words):
    for i in range(64): dut.u_imem.mem[i].value = words[i] if i < len(words) else 0

async def boot(dut, src, prescale=0):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    load(dut, assemble(src)); dut.prescale.value = prescale; dut.run.value = 0
    dut.rst_n.value = 0; await ClockCycles(dut.clk, 3); dut.rst_n.value = 1; await ClockCycles(dut.clk, 2)
    dut.run.value = 1; await RisingEdge(dut.clk)        # cycle 0 starts after this edge

async def trace(dut, n):
    out = []
    for _ in range(n):
        await FallingEdge(dut.clk); out.append((int(dut.uo_out.value), int(dut.uio_out.value), int(dut.uio_oe.value)))
    return out

@cocotb.test()
async def pin_write_visible_next_cycle(dut):
    await boot(dut, "SET UO, 0x01\nHALT\nNOP"); tr = await trace(dut, 4)
    assert [t[0] for t in tr] == [0, 1, 1, 1], tr
    assert int(dut.halted.value) == 1

@cocotb.test()
async def blink_period_10_cycles(dut):
    await boot(dut, open("../firmware/blink.s").read()); tr = await trace(dut, 64)
    uo = [t[0] & 1 for t in tr]; edges = [i for i in range(1, 64) if uo[i] != uo[i-1]]
    assert edges[0] == 1 and all(b - a == 10 for a, b in zip(edges, edges[1:])), edges

@cocotb.test()
async def delay_slot_after_jmp(dut):
    await boot(dut, "JMP 3\nSET UO, 0x02\nSET UO, 0x04\nHALT\nNOP"); tr = await trace(dut, 6)
    assert tr[2][0] == 0x02 and tr[3][0] == 0x02, tr

@cocotb.test()
async def waitt_no_drift(dut):
    await boot(dut, "SETT R1, 0\nloop:\n ADDT R1, 5\n TGL UO, 0x01\n WAITT R1\n JMP loop\n NOP"); tr = await trace(dut, 60)
    uo = [t[0] & 1 for t in tr]; edges = [i for i in range(1, 60) if uo[i] != uo[i-1]]
    # edges[0] is the first toggle after the one-time SETT/ADDT warm-up; "no drift" means
    # the steady-state period stays exactly 5 for every interval after that first one.
    assert all(b - a == 5 for a, b in zip(edges[1:], edges[2:])), edges

@cocotb.test()
async def waitp_timeout_and_release(dut):
    # BTO's target is pc+1+simm with one delay slot always executing; BTO is at addr 2,
    # so simm=3 lands the taken (timeout) branch at addr 2+1+3=6 (SET UO, 0x02), while
    # fall-through after the delay slot (addr 3) reaches addr 4 (SET UO, 0x01).
    await boot(dut, "LDI R2, 3\nWAITP UI, 0, HIGH, R2\nBTO 3\nNOP\nSET UO, 0x01\nHALT\nSET UO, 0x02\nHALT\nNOP")
    await trace(dut, 12); assert int(dut.halted.value) == 1 and int(dut.uo_out.value) == 0x02 and (int(dut.flags.value) >> 2) & 1 == 1
    await boot(dut, "WAITP UI, 0, RISE, R0\nSET UO, 0x01\nHALT\nNOP")
    await trace(dut, 5); dut.ui_in.value = 1; tr = await trace(dut, 8)
    assert int(dut.halted.value) == 1 and tr[-1][0] == 1 and (int(dut.flags.value) >> 2) & 1 == 0

@cocotb.test()
async def alu_flags_and_r0(dut):
    # MOV is ALU-class and always sets Z from its own result (docs/isa.md), so Z/C from
    # the ADD must be checked with ADD as the final instruction before HALT, before a
    # later MOV overwrites them.
    await boot(dut, "LDI R1, 0xFF\nLDIH R1, 0xFF\nLDI R2, 1\nADD R1, R2\nHALT\nNOP"); await trace(dut, 8)
    f = int(dut.flags.value)
    assert int(dut.u_core.regs[1].value) == 0 and f & 1 == 1 and (f >> 1) & 1 == 1
    # rd=0 writes are discarded: MOV R0, R2 must not change R0.
    await boot(dut, "LDI R1, 0xFF\nLDIH R1, 0xFF\nLDI R2, 1\nADD R1, R2\nMOV R0, R2\nHALT\nNOP"); await trace(dut, 8)
    assert int(dut.u_core.regs[0].value) == 0

@cocotb.test()
async def call_ret(dut):
    await boot(dut, "CALL 4\nNOP\nSET UO, 0x02\nHALT\nSET UO, 0x01\nRET\nNOP\nNOP"); tr = await trace(dut, 10)
    assert int(dut.halted.value) == 1 and tr[-1][0] == 0x03, tr

@cocotb.test()
async def host_fifo_push_pop(dut):
    await boot(dut, "WAITF RXV, R0\nPOP R1\nPUSH R1\nHALT\nNOP")
    await trace(dut, 3); dut.h2c_wdata.value = 0xBEEF; dut.h2c_push.value = 1; await RisingEdge(dut.clk); dut.h2c_push.value = 0
    await trace(dut, 8); assert int(dut.c2h_valid.value) == 1 and int(dut.c2h_rdata.value) == 0xBEEF
