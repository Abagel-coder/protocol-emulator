import os
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from tools.asm import assemble, assemble_file
from tests.test_sim import WAITT_TO_PROGRAM, waitt_program   # the same programs the oracle's tests run

FIRMWARE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firmware")

_clk_task = None            # one clock driver per test: cocotb cancels it when the test ends

def load(dut, words):
    for i in range(64): dut.u_imem.mem[i].value = words[i] if i < len(words) else 0

async def boot(dut, prog, prescale=0):
    """Load `prog` (assembly source, or a list of raw 16-bit words), reset, raise RUN.
    Starts the clock once per test: a test that boots twice must not end up with two
    drivers writing dut.clk (they would only agree by scheduler-order luck)."""
    global _clk_task
    if _clk_task is None or _clk_task.done():
        _clk_task = Clock(dut.clk, 20, unit="ns").start()
    load(dut, assemble(prog) if isinstance(prog, str) else prog)
    dut.prescale.value = prescale; dut.run.value = 0
    dut.rst_n.value = 0; await ClockCycles(dut.clk, 3); dut.rst_n.value = 1; await ClockCycles(dut.clk, 2)
    dut.run.value = 1; await RisingEdge(dut.clk)        # cycle 0 starts after this edge

async def trace(dut, n):
    out = []
    for _ in range(n):
        await FallingEdge(dut.clk); out.append((int(dut.uo_out.value), int(dut.uio_out.value), int(dut.uio_oe.value)))
    return out

def distinct(seq):
    """Collapse a per-cycle trace of uo values into the ordered list of distinct values seen."""
    out = []
    for v in seq:
        if not out or v != out[-1]: out.append(v)
    return out

@cocotb.test()
async def pin_write_visible_next_cycle(dut):
    await boot(dut, "SET UO, 0x01\nHALT\nNOP"); tr = await trace(dut, 4)
    assert [t[0] for t in tr] == [0, 1, 1, 1], tr
    assert int(dut.halted.value) == 1

@cocotb.test()
async def blink_period_10_cycles(dut):
    await boot(dut, assemble_file(os.path.join(FIRMWARE, "blink.s"))); tr = await trace(dut, 64)
    uo = [t[0] & 1 for t in tr]; edges = [i for i in range(1, 64) if uo[i] != uo[i-1]]
    # 64 cycles at a 10-cycle toggle period give 7 edges (1, 11, ..., 61). Requiring at least 6
    # is what makes the interval check below non-vacuous: a hung core (DELAY never ending,
    # RTL mutant E3) produces exactly one edge, for which `all(...)` over an empty zip is True.
    assert len(edges) >= 6, edges
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
    assert len(edges) >= 8, edges
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
async def r0_timeout_is_65535_ticks(dut):
    """isa.yaml semantics.waits: `Rt = R0` means a 65535-tick timeout. Nothing else pins the
    length (the fuzzer never draws R0 as a timeout register; the WAITP/R0 case above releases
    on the pin). With prescale 0 a tick is a cycle, and this harness's T reads 0 in cycle 0
    (tb_core.v), so the WAITF at address 1 first stalls in cycle 1 with T == 1 and a deadline
    of 1 + 65535 == 0 (mod 2^16): it must complete in cycle 65536, when T is 0 again -- 65535
    ticks after it started -- then BTO (65537), its delay slot (65538) and SET UO, 0x01 (65539)
    put the timeout on the pin at cycle 65540. A 65534- or 4095-tick default (RTL mutants E6,
    R2) moves that edge; a wait that never ends never produces it. TO itself is visible both
    through the BTO branch (uo[0] rather than uo[2]) and in flags_out."""
    await boot(dut, "SET UO, 0x02\nWAITF RXV, R0\nBTO to\nNOP\nSET UO, 0x04\nHALT\nNOP\nto: SET UO, 0x01\nHALT\nNOP", prescale=0)
    first = None
    for k in range(65600):
        await FallingEdge(dut.clk)
        if int(dut.uo_out.value) & 1:
            first = k; break
    assert first == 65540, ("uo[0] (the BTO-taken marker) rose at cycle %r, expected 65540" % first)
    await trace(dut, 3)
    assert int(dut.uo_out.value) == 0x03 and int(dut.halted.value) == 1, int(dut.uo_out.value)   # 0x02 (running) | 0x01 (timeout branch), never 0x04
    assert (int(dut.flags.value) >> 2) & 1 == 1, "TO not set after the R0 timeout"

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
async def core_reset_suppresses_side_effects(dut):
    await boot(dut, "SET UO, 0x01\nSET UO, 0x02\nHALT\nNOP")
    # Pulse core_reset across the cycle in which SET UO, 0x01 (pc=0) would execute:
    # `active` must drop combinationally this cycle, so the pin write is never applied,
    # and the synchronous reset (pc/halted/etc back to 0) takes effect on the edge that
    # ends this cycle, since core_reset is still asserted at that edge.
    dut.core_reset.value = 1
    tr0 = await trace(dut, 1)
    assert tr0[0][0] == 0, tr0                       # SET's write never reached uo_out
    await RisingEdge(dut.clk)                        # synchronous reset lands here
    assert int(dut.pc.value) == 0 and int(dut.halted.value) == 0
    await FallingEdge(dut.clk)                       # wait for settled values
    assert int(dut.uo_out.value) == 0
    assert int(dut.uio_out.value) == 0
    assert int(dut.uio_oe.value) == 0
    assert int(dut.active.value) == 0
    dut.core_reset.value = 0
    tr = await trace(dut, 8)
    # program restarts cleanly from pc=0: SET ORs into uo, so both SETs together give 0x03.
    assert 0x03 in [t[0] for t in tr], tr
    assert tr[-1][0] == 0x03 and int(dut.halted.value) == 1

def alu_word(fn, rd, rs):
    return (2 << 12) | (rd << 9) | (rs << 6) | (fn << 2)

@cocotb.test()
async def reserved_alu_fn_is_noop(dut):
    """ALU fn 11-15 are reserved and must be true no-ops: no register write, no flag change
    (pe_core.v alu_valid; tools/sim.py falls through to _advance()). rs and rd are different
    registers holding different values, so a reserved fn that decays into the MOV default
    (RTL mutant M7: alu_valid forced true) changes R1 to 9 and is caught; C is pre-set by an
    overflowing ADD and Z cleared by the LDIs, so a reserved fn that decays into ADD or
    touches the flags is caught too."""
    words = (assemble("LDI R3, 0xFF\nLDIH R3, 0xFF\nLDI R4, 1\nADD R3, R4\nLDI R1, 5\nLDI R2, 9")   # C=1 from the ADD, then Z=0
             + [alu_word(12, 1, 2), alu_word(11, 1, 2), alu_word(15, 2, 1)]                      # reserved fn 12, 11, 15
             + assemble("HALT\nNOP"))
    await boot(dut, words)
    await trace(dut, 14)
    assert int(dut.halted.value) == 1
    assert int(dut.u_core.regs[1].value) == 5, int(dut.u_core.regs[1].value)
    assert int(dut.u_core.regs[2].value) == 9, int(dut.u_core.regs[2].value)
    f = int(dut.flags.value)
    assert f & 1 == 0, f          # Z=0 from LDI R2, 9 (a reserved fn must not set Z)
    assert (f >> 1) & 1 == 1, f   # C=1 from the overflowing ADD (a reserved fn must not touch C)

@cocotb.test()
async def pin_bank_field_truthiness(dut):
    # raw PIN word with bank field = 2 should treat it as UIO (like the oracle)
    words = [(4<<12)|(0<<10)|(2<<8)|0x10, 0, 0, 0]  # PIN SET with bank=2, mask=0x10; then NOP x3 (the program never halts; 4 cycles are traced)
    await boot(dut, words)
    await trace(dut, 4)
    assert int(dut.uio_out.value) == 0x10
    assert int(dut.uo_out.value) == 0

@cocotb.test()
async def call_ret(dut):
    await boot(dut, "CALL 4\nNOP\nSET UO, 0x02\nHALT\nSET UO, 0x01\nRET\nNOP\nNOP"); tr = await trace(dut, 10)
    assert int(dut.halted.value) == 1 and tr[-1][0] == 0x03, tr

@cocotb.test()
async def call_stack_depth_4_overflow_and_ret_on_empty(dut):
    """The call stack is 4 deep (isa.yaml semantics.branches): four nested CALLs return to the
    right places, a fifth CALL drops the oldest entry, and RET on an empty stack goes to
    address 0 (pe_core.v ret_t; tools/sim.py). Each return point sets a distinct uo bit, so
    the ORDER of uo values on the pin is the stack trace. RTL mutant E11 (st3 never written,
    stack effectively 3 deep) makes the 4th RET land on 0 instead of its return point."""
    # 4-deep nesting: f1 -> f2 -> f3 -> f4, unwinding sets 0x10, 0x08, 0x04, 0x02, then 0x01 at top level.
    await boot(dut, "CALL f1\nNOP\nSET UO, 0x01\nHALT\nNOP\n"
                    "f1: CALL f2\nNOP\nSET UO, 0x02\nRET\nNOP\n"
                    "f2: CALL f3\nNOP\nSET UO, 0x04\nRET\nNOP\n"
                    "f3: CALL f4\nNOP\nSET UO, 0x08\nRET\nNOP\n"
                    "f4: SET UO, 0x10\nRET\nNOP")
    tr = await trace(dut, 30)
    assert distinct([t[0] for t in tr]) == [0x00, 0x10, 0x18, 0x1C, 0x1E, 0x1F], distinct([t[0] for t in tr])
    assert int(dut.halted.value) == 1 and int(dut.pc.value) == 3
    # 5-deep nesting: the 5th CALL (in f4) drops CALL#1's return address (5, whose SET UO, 0x01
    # must therefore never run); after the four remaining RETs the 5th RET finds the stack
    # empty and goes to 0, where BZ (Z=1 from the LDI R1, 0 -- no later instruction touches Z)
    # is now taken and reaches `done`. Flags are 0 at reset, so BZ falls through on the first pass.
    await boot(dut, "BZ done\nNOP\nLDI R1, 0\nCALL f1\nNOP\nSET UO, 0x01\nHALT\nNOP\n"
                    "f1: CALL f2\nNOP\nSET UO, 0x02\nRET\nNOP\n"
                    "f2: CALL f3\nNOP\nSET UO, 0x04\nRET\nNOP\n"
                    "f3: CALL f4\nNOP\nSET UO, 0x08\nRET\nNOP\n"
                    "f4: CALL f5\nNOP\nSET UO, 0x10\nRET\nNOP\n"
                    "f5: SET UO, 0x20\nRET\nNOP\n"
                    "done: SET UO, 0x40\nHALT\nNOP")
    tr = await trace(dut, 40)
    assert distinct([t[0] for t in tr]) == [0x00, 0x20, 0x30, 0x38, 0x3C, 0x3E, 0x7E], distinct([t[0] for t in tr])
    assert int(dut.halted.value) == 1 and int(dut.pc.value) == 32, int(dut.pc.value)   # halted at `done`'s HALT, never at address 6

@cocotb.test()
async def waitt_period_holds_across_T_wraparound(dut):
    # T free-runs from reset and never pauses (isa.yaml semantics.timebase); it is unrelated
    # to when a program starts, so a firmware timing loop must not glitch when T wraps past
    # 0xFFFF back to 0. This harness starts T at 0 (see the run_q_tb comment in tb_core.v), so
    # run long enough at prescale 0 (tick every cycle) to force a real wrap within the run:
    # ~65536 cycles to wrap once, plus margin.
    await boot(dut, "SETT R1, 0\nloop:\n ADDT R1, 5\n TGL UO, 0x01\n WAITT R1\n JMP loop\n NOP", prescale=0)
    N = 66000
    uo = []; t = []
    for _ in range(N):
        await FallingEdge(dut.clk)
        uo.append(int(dut.uo_out.value) & 1); t.append(int(dut.t_out.value))
    # Bit-exact wraparound arithmetic: T must increment by exactly 1 every single cycle
    # (prescale=0, en stable after boot), wrapping 0xFFFF -> 0x0000 without a glitch, and the
    # 66000-cycle run must span exactly one such wrap.
    assert all(t[i] == (t[i - 1] + 1) & 0xFFFF for i in range(1, N)), "T did not increment by exactly 1 every cycle"
    wraps = [i for i in range(1, N) if t[i] < t[i - 1]]
    assert len(wraps) == 1, wraps   # confirms the run truly spans (exactly) one wrap
    edges = [i for i in range(1, N) if uo[i] != uo[i - 1]]
    periods = [b - a for a, b in zip(edges[1:], edges[2:])]
    assert len(periods) > 65536 // 5, len(periods)   # confirms the run truly spans the wrap
    assert all(p == 5 for p in periods), (periods[:5], periods[-5:])

# ---- wrap-safe WAITT (isa.yaml semantics.waits, core v0.1): WAITT Rn completes in the first cycle in
# which bit 15 of (T - Rn) mod 2^16 is 0. The programs come from tests/test_sim.py, where the oracle runs
# them: waitt_program(delta) puts WAITT R1 at address 4, first executing in cycle 4 with R1 == T + delta
# (this harness's T reads 0 in cycle 0 and ticks every cycle at prescale 0, like the oracle's default),
# and the SET UO, 0x01 after it is on the pin from the cycle after it executes.

def first_nonzero(values):
    return next((i for i, v in enumerate(values) if v), None)

@cocotb.test()
async def waitt_late_deadline_completes_in_one_cycle(dut):
    """Deadlines 1, 300 and 32,767 ticks behind T when the WAITT first executes (cycle 4): each completes
    in that cycle, so the SET executes in cycle 5 and uo reads 1 from cycle 6. The v0 equality rule
    (RTL mutant W1) stalled each until T wrapped round to R1, 65,536 - d ticks later; the inverted sign
    (W2) stalls on every late deadline; a window on bit 14 (W3) stalls on the 32,767-tick one."""
    for d in (1, 300, 32767):
        await boot(dut, waitt_program(-d)); tr = await trace(dut, 12)
        assert first_nonzero([t[0] for t in tr]) == 6, (d, [t[0] for t in tr])
        assert int(dut.halted.value) == 1, d

@cocotb.test()
async def waitt_boundary_32768_ahead_waits_exactly(dut):
    """A deadline exactly 32,768 ticks ahead (T - Rn == 0x8000, bit 15 set) still counts as ahead: the
    WAITT stalls and completes exactly when T == Rn in cycle 4 + 32,768, so uo reads 1 from cycle
    32,774 and not one cycle earlier or later (a window on bit 14, W3, completes it at once). One tick
    further, 32,769 ahead (T - Rn == 0x7FFF), is indistinguishable from a passed deadline and completes
    in its first cycle (the v0 equality rule, W1, stalls it 32,769 ticks)."""
    await boot(dut, waitt_program(32768))
    first = None
    for k in range(4 + 32768 + 6):
        await FallingEdge(dut.clk)
        if int(dut.uo_out.value) & 1:
            first = k; break
    assert first == 4 + 32768 + 2, first
    await boot(dut, waitt_program(32769)); tr = await trace(dut, 12)
    assert first_nonzero([t[0] for t in tr]) == 6, [t[0] for t in tr]

@cocotb.test()
async def waitt_leaves_to_unchanged(dut):
    """isa.yaml: WAITT leaves the flags untouched, late or on time. tests/test_sim.py's WAITT_TO_PROGRAM
    sets TO = 1 (a WAITF that times out), runs a late and an on-time WAITT, checks TO with BTO, then sets
    TO = 0 (a WAITF that completes on its flag) and does the same; any WAITT that changed TO puts a
    failure marker (0x02, 0x04 or 0x08) on uo, success leaves exactly 0x01."""
    await boot(dut, WAITT_TO_PROGRAM); tr = await trace(dut, 40)
    assert int(dut.halted.value) == 1 and tr[-1][0] == 0x01, [t[0] for t in tr]
    assert (int(dut.flags.value) >> 2) & 1 == 0

@cocotb.test()
async def host_fifo_push_pop(dut):
    await boot(dut, "WAITF RXV, R0\nPOP R1\nPUSH R1\nHALT\nNOP")
    await trace(dut, 3); dut.h2c_wdata.value = 0xBEEF; dut.h2c_push.value = 1; await RisingEdge(dut.clk); dut.h2c_push.value = 0
    await trace(dut, 8); assert int(dut.c2h_valid.value) == 1 and int(dut.c2h_rdata.value) == 0xBEEF
