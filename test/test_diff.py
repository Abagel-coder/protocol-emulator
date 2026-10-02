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
(0-3, 2-3 reserved), WAIT sub the full defined-plus-reserved range (0-7; WAITT since core v0.1), BFLAG flag the full
5-bit field (0-31, 3-31 reserved), and the reserved classes LANE and RSV (both all-NOP in v0)
are generated with random operand bits -- LANE used to be generated with all operand bits zero,
which let an RTL mutant that made LANE perform PIN-style writes (final-review mutant E10) pass as
`SET UO, 0x00`.

One encoding is still excluded entirely and two are shaped -- each because it can make a
random program stall for very long (or park for good) rather than because it's untested; directed
tests in test_core.py / tests/test_sim.py cover them individually:
  - LDIH: generated only occasionally (about one LDI word in ten) and only with imm8 in {0, 1},
    so every register still holds small values (at most 0x1FF, or arithmetic on those). This
    keeps WAITP/WAITF/WAITL's `rt` *register content* (the actual tick count used as a timeout,
    as opposed to the `rt` field below, which only selects which register) from landing near
    65535, while still exercising the hi-byte load path (a mutant that clears the low byte on
    LDIH, task-8 mutant E12, used to be caught by directed tests only).
  - WAITT (WAIT sub=0): generated since core v0.1 made it wrap-safe (it completes once bit 15 of
    T - Rn is 0). It used to be excluded because v0's equality compare stalled a random program
    for up to 65,535 ticks whenever Rn had already passed. Now a deadline up to 32,767 ticks
    behind completes at once and only one up to 32,768 ticks ahead stalls (a deadline further
    behind than 32,767 counts as ahead), so WAITT is drawn like the other sub-ops but
    shaped: with probability 0.8 it comes right after a SETT or ADDT on the same
    register with a small positive offset (1..32) -- SETT arms a deadline a few ticks ahead
    (an on-time stall that must release exactly at T == Rn), ADDT moves an earlier deadline or a
    data value by a few ticks, which in a loop or after other work usually lands behind T (a
    late WAITT, completing at once) -- and otherwise it waits on an arbitrary register (R0 means
    deadline 0). Its ignored operand bits [5:0] are random. A deadline far ahead can still stall
    longer than the program's N_CYCLES budget; then the RTL and the model simply stall together
    for the rest of it (every cycle is still compared), costing coverage, not correctness or time
    -- the loop runs exactly N_CYCLES cycles per program either way.
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

Register-seeding preamble (task-7 round 3): every program's first seven words are fixed --
LDI Rk, v for k = 1..7, v drawn uniformly from 8..63 -- before the 57 random words that fill
addresses 7..63. Random JMP/BR targets may still land back on 0-6; that's fine, it just
re-seeds those registers rather than corrupting anything. Without this, `rt` (1-7 per above)
named a register whose *content* -- not just which register the field picks -- was almost
always still its reset value of 0: only about a third of the generated instruction classes
write a register at all, and LDIH (the only encoding that can put a large value in a register)
was excluded (it is now generated rarely and only with a 0/1 high byte, see above). WAIT's `_deadline()` treats a zero-content register as "deadline ==
current tick", so the wait resolves in the same cycle it started -- a "zero-tick" wait that
never actually exercises multi-cycle stall behaviour. Measured on the oracle alone
(tools.sim.Sim, no RTL/cocotb), 300 programs x 1500 cycles, same seeds (random.Random(1000+n))
and per-cycle loop this test uses:

  |                                 | before (no preamble) | after (preamble + bias, below) |
  |---------------------------------|-----------------------|---------------------------------|
  | WAITP zero-tick starts          | 70.0%                 | 1.4%                            |
  | WAITP completions: condition    | 44.8%                 | 68.3%                           |
  | WAITP completions: timeout      | 55.2%                 | 31.7%                           |
  | WAITF zero-tick starts          | 55.3%                 | 5.2%                             |
  | WAITF completions: condition    | 36.6%                 | 51.9%                            |
  | WAITF completions: timeout      | 63.4%                 | 48.1%                            |
  | cycles stalled in a WAIT        | 39.3%                 | 40.8%                            |
  | mean distinct addresses/program | 99.1                  | 109.3                           |

With the preamble alone (8-63 tick deadlines) and the toggle probability unchanged at 0.15,
WAITP completions swung hard the other way: 93.3% condition-driven, only 6.7% timeout -- under
this round's >=25%-each target. A freshly-nonzero-deadline WAITP still starts with roughly
even odds that its watched pin already sits at the LOW/HIGH level it wants (the pin's resting
value is ~Bernoulli(0.5) regardless of toggle rate), and 0.15/cycle toggling over an 8-63 tick
window gives ample further chances for LOW/HIGH/RISE/FALL to fire before the now-much-longer
timeout elapses. The fix is not a general toggle-probability change (kept at 0.15, "everything
else as is"): instead, while a WAITP is in flight, the specific bank/pin it is watching --
decoded from the oracle's own `sim.pc`/`sim.imem`/`sim.wait_state`, never from the DUT -- has
its toggle suppressed (kept at its previous value) with probability 0.85 on cycles that would
otherwise toggle it; every other bit, and every cycle without a live WAITP, keeps the plain
0.15 rate untouched. This is a stimulus-generation choice derived only from information the
oracle (and a firmware author reading the program listing) already has, never from anything
the RTL computed, so it cannot mask an RTL/model divergence -- see the "after" column above,
where both condition-driven and timeout completions end up comfortably over 25%.

Re-measured 2026-09-21 after the generator gained random LANE operands and the occasional LDIH
(same oracle-only method, 300 programs x 1500 cycles; the extra random draws shift every seed's
stream, so this is a fresh sample rather than a drift): WAITP completions 58.4% condition /
41.6% timeout, WAITF 53.6% / 46.4% -- still over the 25%-each target.

Re-measured 2026-10-01 after WAITT joined the mix (same oracle-only method and seeds; WAITT shifts
every seed's stream again). 300 programs x 1500 cycles: WAITP completions 63.2% condition / 36.8%
timeout, WAITF 36.4% / 63.6% -- still over the 25%-each target; WAITF zero-tick starts rose to
23.6%, but 290 of them come from one program (seed 1237) looping on a zero-content timeout register
(11 programs have any). The default run, 200 programs x 1500 cycles, places 156 WAITT words (135 of
them armed by a SETT/ADDT on the same register) in 69 programs that execute one, and executes WAITT
2,227 times: 1,486 late (deadline already passed: completes at once), 705 stalling on a deadline
ahead (698 released exactly at T == Rn; 7 were still stalled when their program's budget ran out,
the longest stall being 242 cycles) and 36 with the deadline equal to T. Those late and stalling
WAITTs are what catch v0's equality rule and an inverted sign (RTL mutants W1/W2, program 1 of the
default run) here as well as in the directed tests.
"""
import os, random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from tools import isa_defs as D
from tools.sim import Sim

# 200 x 1500 cycles ~ 15 s (Icarus). 25 let a stack-depth mutant survive (final-review-verif.md M2); so
# does 200 since WAITT reseeded every stream in core v0.1 (it dies at program 369), which is why
# test_core.py's call_stack_depth_4_overflow_and_ret_on_empty pins the stack depth directly.
N_PROGRAMS = int(os.environ.get("DIFF_PROGRAMS", "200"))
N_CYCLES   = int(os.environ.get("DIFF_CYCLES", "1500"))
IMEM_WORDS = 64

def rand_word(rng):
    """One random instruction as a list of words: one word, or for a WAITT usually two -- the
    SETT/ADDT that arms its deadline, then the WAITT (see the module docstring)."""
    cls = rng.choices(["LDI", "ALU", "ADDI", "PIN", "SETR", "IN", "WAIT", "TIME", "BR", "JMP", "BPIN", "BFLAG", "HOST", "MISC", "LANE", "RSV"],
                      weights=[10, 12, 6, 12, 6, 5, 10, 6, 6, 3, 4, 2, 2, 2, 1, 1])[0]
    w = D.CLASSES[cls] << 12; r = rng.randrange
    if cls == "LDI":
        if rng.random() < 0.1: w |= (r(8) << 9) | (1 << 8) | r(2)                  # occasional LDIH with imm8 in {0,1}: exercises the hi-byte path (LDIH clearing the low byte, task-8 mutant E12) while keeping register contents <= 0x1FF, see the docstring
        else:                  w |= (r(8) << 9) | r(256)                              # LDI (hi=0)
    elif cls == "ALU": w |= (r(8) << 9) | (r(8) << 6) | (r(16) << 2)               # fn: 0-15 (11-15 reserved)
    elif cls == "ADDI": w |= (r(8) << 9) | r(512)
    elif cls == "PIN": w |= (r(4) << 10) | (r(4) << 8) | r(256)                    # bank: 0-3 (2-3 reserved)
    elif cls == "SETR": w |= (r(8) << 9) | (r(2) << 8) | (r(8) << 5) | r(16)
    elif cls == "IN":  w |= (r(8) << 9) | (r(4) << 7)
    elif cls == "WAIT":
        sub = rng.choice([0, 1, 2, 3, 4, 5, 6, 7])                     # WAITT, DELAY, WAITP, WAITF, WAITL, undefined(5-7)
        w |= sub << 9
        if sub == 0:                                                   # WAITT; [5:0] are ignored operand bits, randomised
            if rng.random() < 0.8:                                     # mostly: armed by SETT/ADDT rd, 1..32 just before it
                rd = 1 + r(7)
                arm = (D.CLASSES["TIME"] << 12) | (rd << 9) | (r(2) << 8) | (1 + r(32))
                return [arm, w | (rd << 6) | r(64)]
            w |= (r(8) << 6) | r(64)                                   # occasionally: any register as the deadline (R0 = 0)
        elif sub == 1:
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
    elif cls == "LANE": w |= r(4096)                                                # reserved lane class: any lower bits, always a no-op in v0 (RTL mutant E10 made it write pins; all-zero operands hid that)
    elif cls == "RSV": w |= r(4096)                                                 # fully reserved class: any lower bits, always a no-op
    return [w]

def rand_words(rng, n):
    """Exactly n words from rand_word (a SETT/ADDT + WAITT pair cut by the end keeps only its SETT/ADDT)."""
    out = []
    while len(out) < n:
        out += rand_word(rng)
    return out[:n]

def preamble_words(rng):
    """First seven words: LDI Rk, v for k=1..7, v in 8..63 (hi=0, rd=k). See the module
    docstring's "Register-seeding preamble" section for why."""
    return [(D.CLASSES["LDI"] << 12) | (k << 9) | (8 + rng.randrange(56)) for k in range(1, 8)]

@cocotb.test()
async def rtl_matches_model_on_random_programs(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    for n in range(N_PROGRAMS):
        rng = random.Random(1000 + n)
        words = preamble_words(rng) + rand_words(rng, IMEM_WORDS - 7)
        for i in range(IMEM_WORDS): dut.u_imem.mem[i].value = words[i]
        dut.prescale.value = 0; dut.run.value = 0; dut.ui_in.value = 0; dut.uio_in.value = 0
        dut.rst_n.value = 0; await ClockCycles(dut.clk, 3); dut.rst_n.value = 1; await ClockCycles(dut.clk, 2)
        dut.run.value = 1; await RisingEdge(dut.clk)
        sim = Sim(words, prescale=1, imem_words=IMEM_WORDS)
        hist = {}
        watched = None                          # (bank, pin) a live WAITP is watching, from the oracle's own decode only -- see module docstring
        for k in range(N_CYCLES):
            if not sim.halted:
                w = sim.imem[sim.pc % len(sim.imem)]
                if (w >> 12) == D.CLASSES["WAIT"] and ((w >> 9) & 0x7) == D.WAIT_SUB["WAITP"] and sim.wait_state is None:
                    watched = ((w >> 5) & 1, (w >> 2) & 0x7)    # WAIT layout: bank[5:5], pin[4:2]
            ui, uio = hist.get(k - 2, (0, 0))
            sim.set_inputs(ui=ui, uio_in=uio)
            exp = sim.step()
            if sim.wait_state is None: watched = None           # no wait in flight any more (completed, or never started one)
            await FallingEdge(dut.clk)
            got = (k, int(dut.uo_out.value), int(dut.uio_out.value), int(dut.uio_oe.value), int(dut.halted.value))
            assert got == exp, (f"program {n} cycle {k}: rtl={got} model={exp} pc={int(dut.pc.value)} "
                                f"words={' '.join('%04x' % w for w in words)}")
            if rng.random() < 0.15:                                                # change inputs sometimes
                new_ui, new_uio = rng.randrange(256), rng.randrange(256)           # full 8-bit ui_in: ui[7:4] must be masked away identically on both sides
                if watched is not None and rng.random() < 0.85:
                    # Suppress (freeze at its previous value) just the bit a live WAITP is
                    # watching; every other bit and every cycle without a live WAITP keeps the
                    # plain 0.15 rate. Derived only from `watched` above (oracle decode), never
                    # from dut state -- see module docstring for why and the measured effect.
                    bank, pin = watched
                    prev_ui, prev_uio = hist.get(k - 1, (0, 0))
                    if bank == 0: new_ui  = (new_ui  & ~(1 << pin)) | (((prev_ui  >> pin) & 1) << pin)
                    else:         new_uio = (new_uio & ~(1 << pin)) | (((prev_uio >> pin) & 1) << pin)
                hist[k] = (new_ui, new_uio)
                dut.ui_in.value = hist[k][0]; dut.uio_in.value = hist[k][1]
            else:
                hist[k] = hist.get(k - 1, (0, 0))
        # sim.regs already reflects cycle (N_CYCLES-1)'s write (Sim._write() is immediate,
        # unlike pin writes which go through self.pending), but the RTL's regs[] only commits
        # that write on the clock edge ending cycle N_CYCLES-1, which the loop above never
        # waits for (its last action was a FallingEdge, mid-cycle). Advance one more full
        # cycle so the RTL side has caught up before comparing final state. `halted` is a
        # registered signal too (see tools/sim.py's docstring / pe_core.v's `halted <= 1'b1`),
        # so this settle cycle is also when a HALT-like decode reachable from the very last
        # executed cycle (N_CYCLES-1) becomes visible on dut.halted -- something the per-cycle
        # `got`/`exp` comparison above never gets to check, since it captures `halted` at the
        # *start* of each cycle and the loop stops before a cycle N_CYCLES would exist to show
        # it. Compare it here too, in addition to (not instead of) the per-cycle check.
        await RisingEdge(dut.clk); await FallingEdge(dut.clk)
        for i in range(1, 8):
            assert int(dut.u_core.regs[i].value) == sim.regs[i], f"program {n}: R{i} rtl={int(dut.u_core.regs[i].value)} model={sim.regs[i]}"
        f = int(dut.flags.value)
        assert (f & 1, (f >> 1) & 1, (f >> 2) & 1) == (sim.flags["Z"], sim.flags["C"], sim.flags["TO"]), f"program {n}: flags"
        assert int(dut.halted.value) == int(sim.halted), f"program {n}: halted (end-of-run)"
