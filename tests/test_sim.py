import pathlib
from tools import isa_defs as D
from tools.asm import assemble
from tools.sim import Sim

FIRMWARE = pathlib.Path(__file__).resolve().parents[1] / "firmware"   # not CWD-relative: pytest works from any directory

def run(src, cycles, **kw):
    s = Sim(assemble(src), **kw); return s, s.run(cycles)

def test_pin_write_visible_next_cycle():
    s, tr = run("SET UO, 0x01\nHALT\nNOP", 4)
    assert [t[1] for t in tr] == [0, 1, 1, 1]      # written in cycle 0, visible from cycle 1

def test_blink_period_is_10_cycles():
    src = (FIRMWARE / "blink.s").read_text()
    s, tr = run(src, 64)
    uo = [t[1] & 1 for t in tr]
    # Total loop = TGL(1) + DELAY 6(7) + JMP(1) + delay-slot NOP(1) = 10 cycles.
    edges = [i for i in range(1, 64) if uo[i] != uo[i-1]]
    assert edges[0] == 1 and all(b - a == 10 for a, b in zip(edges, edges[1:]))

def test_delay_slot_executes_after_jmp():
    s, tr = run("JMP 3\nSET UO, 0x02\nSET UO, 0x04\nHALT\nNOP", 6)
    assert tr[2][1] == 0x02 and tr[3][1] == 0x02          # slot executed, address 2 skipped

def test_waitt_exact_and_no_drift():
    src = "SETT R1, 0\nloop:\n ADDT R1, 5\n TGL UO, 0x01\n WAITT R1\n JMP loop\n NOP"
    s, tr = run(src, 60)
    uo = [t[1] & 1 for t in tr]
    edges = [i for i in range(1, 60) if uo[i] != uo[i-1]]
    # edges[0] is the first toggle after the one-time SETT/ADDT warm-up (3 cycles);
    # "no drift" means the steady-state period stays exactly 5 thereafter.
    assert all(b - a == 5 for a, b in zip(edges[1:], edges[2:]))

def test_waitp_timeout_sets_TO():
    s = Sim(assemble("WAITP UI, 0, HIGH, R2\nHALT\nNOP"))
    s.regs[2] = 3; s.run(10)
    assert s.halted and s.flags["TO"] == 1

def test_r0_timeout_is_65535_ticks():
    # isa.yaml semantics.waits: a timed wait whose Rt is R0 times out after 65535 ticks. With
    # prescale=1 (a tick every cycle, T == cycle) and nothing pushed into the host->core FIFO,
    # WAITF RXV, R0 at pc 0 captures deadline 0 + 65535 in cycle 0 and must still be waiting
    # after cycle 65534, then complete in cycle 65535 (T == 65535) with TO = 1. Pins the
    # length of the default timeout, which a 255-tick default (oracle mutant S1) would shorten.
    s = Sim(assemble("WAITF RXV, R0\nSET UO, 0x01\nHALT\nNOP"), prescale=1)
    s.run(65535)                                                # cycles 0..65534: T == 65534 after the last of them
    assert s.pc == 0 and s.wait_state == 65535 and s.flags["TO"] == 0 and not s.halted
    s.step()                                                    # cycle 65535: T == 65535 == deadline
    assert s.pc == 1 and s.wait_state is None and s.flags["TO"] == 1
    tr = s.run(3)
    assert [t[1] for t in tr] == [0, 1, 1] and s.halted        # SET lands, then HALT

def test_waitp_release_on_rise():
    s = Sim(assemble("WAITP UI, 0, RISE, R0\nSET UO, 0x01\nHALT\nNOP"))
    s.run(5); s.set_inputs(ui=1, uio_in=0); tr = s.run(6)
    assert s.flags["TO"] == 0 and tr[-1][1] == 1

def test_alu_flags_and_r0_zero():
    s = Sim(assemble("LDI R1, 0xFF\nLDIH R1, 0xFF\nLDI R2, 1\nADD R1, R2\nMOV R0, R2\nHALT\nNOP"))
    s.run(4)  # through ADD R1, R2: check its flags before MOV (which also sets Z) overwrites them
    assert s.regs[1] == 0 and s.flags["Z"] == 1 and s.flags["C"] == 1
    s.run(4)  # MOV R0, R2 then HALT: rd=0 writes are discarded
    assert s.regs[0] == 0

def test_call_ret_stack():
    s = Sim(assemble("CALL 4\nNOP\nSET UO, 0x02\nHALT\nSET UO, 0x01\nRET\nNOP\nNOP")); tr = s.run(10)
    assert s.halted and tr[-1][1] == 0x03

def test_reserved_flag_id_reads_as_false():
    # BFLAG/WAITF select a flag by a 5-bit id; ids 3+ are reserved and always read as 0 (never
    # satisfied), matching pe_core.v's default case for bf_v/flag_v (isa.yaml semantics.flag_ids).
    # tools/sim.py's _flag() used to KeyError on any id above 2 -- found by test_diff.py's fuzzer
    # (program 3, a random BFLAG word with flag=3).
    s = Sim(assemble("BFLAG 3, 0, 2\nSET UO, 0x01\nSET UO, 0x02\nHALT\nNOP"))
    tr = s.run(6)
    assert tr[-1][1] == 0x01 and s.halted   # flag(3)==0==level -> branch taken, 0x02 never applied

def test_reserved_br_cond_never_taken():
    # BR's cond field is 3 bits but only 6 conditions are defined (0-5); reserved cond 6/7 must
    # never branch, matching pe_core.v's br_take default (isa.yaml semantics.branches).
    # tools/sim.py's BR handler used to KeyError on cond 6/7 -- found by test_diff.py's fuzzer
    # (program 0, a random BR word with cond=6).
    br_word = (D.CLASSES["BR"] << 12) | (6 << 9) | 0        # reserved cond=6, simm9=0
    s = Sim([br_word] + assemble("SET UO, 0x01\nSET UO, 0x02\nHALT\nNOP"))
    tr = s.run(6)
    assert tr[-1][1] == 0x03 and s.halted   # not taken -> fall through hits both SETs

def test_setr_uo_pin7_is_reserved_noop():
    # uo has only 7 output bits; pin 7 is the host SPI MISO line (docs/info.md, isa.yaml
    # semantics.pins) and is reserved. PIN SET/CLR/TGL already mask uo to 7 bits, but SETR
    # writes a single bit directly and needs its own guard, matching pe_gpio.v's
    # `pin_idx != 3'd7` guard. tools/sim.py's SETR used to let bit 7 leak into self.uo
    # (found by test_diff.py's fuzzer: program 75, cycle 1210, uo=132 instead of 4).
    #
    # A trailing SET UO, 0x04 always re-masks uo to 7 bits on its own (PIN's own apply() ANDs
    # with 0x7F), so checking only the final uo value or the final trace entry passes even
    # with the `elif pin != 7` guard reverted -- that check is vacuous. The leak is visible
    # only at trace index 2 (the value of uo as of the *start* of the SET cycle, i.e. right
    # after SETR's pending write lands and before SET's write applies): 0x00 with the guard,
    # 0x80 without it. Assert the whole trace so this regression actually fails without the
    # fix (verified: reverting the guard makes this FAIL with tr == [0, 0, 128, 4, 4, 4]).
    s = Sim(assemble("LDI R1, 1\nSETR UO, 7, R1, 0\nSET UO, 0x04\nHALT\nNOP"))
    tr = s.run(6)
    assert [t[1] for t in tr] == [0, 0, 0, 4, 4, 4]
    assert s.uo == 0x04 and s.halted

def test_timebase_t0_wraparound_preserves_waitt_period():
    # T is a free-running counter that starts at reset, not at RUN, and never pauses; a
    # program can start with T at any value, not just 0 (isa.yaml semantics.timebase). The
    # steady-state period of a SETT/ADDT/WAITT loop must be the same regardless of T's
    # starting value, including when T wraps past 0xFFFF back to 0 mid-loop.
    src = "SETT R1, 0\nloop:\n ADDT R1, 5\n TGL UO, 0x01\n WAITT R1\n JMP loop\n NOP"
    def periods(t0):
        s = Sim(assemble(src), t0=t0); tr = s.run(60)
        uo = [t[1] & 1 for t in tr]
        edges = [i for i in range(1, 60) if uo[i] != uo[i - 1]]
        return [b - a for a, b in zip(edges[1:], edges[2:])]
    p0 = periods(0)
    p_wrap = periods(0xFFF0)          # T runs 0xFFF0..0xFFF0+59, wrapping past 0xFFFF partway through
    assert len(p0) >= 8 and all(p == 5 for p in p0)
    assert len(p_wrap) >= 8 and all(p == 5 for p in p_wrap)
    assert p0 == p_wrap

# ---- wrap-safe WAITT (isa.yaml semantics.waits; core v0.1): WAITT Rn completes in the first cycle in
# which bit 15 of (T - Rn) mod 2^16 is 0 -- a deadline 1..32,767 ticks behind T completes at once, one
# 1..32,768 ticks ahead completes exactly at T == Rn. Flags are untouched.

def waitt_program(delta):
    """WAITT R1 at address 4, first executing in cycle 4 with R1 == T + delta (mod 2^16): SETT R1, 2 in
    cycle 2 makes R1 == T(4) (a tick per cycle), then ADD/SUB moves it by |delta| (LDI/LDIH build |delta|
    in R2). The SET UO, 0x01 at address 5 executes the cycle after the WAITT completes and lands on the
    pin one cycle later, so a WAITT that completes in its first cycle shows uo == 1 from cycle 6."""
    mag = abs(delta)
    return ("LDI R2, %d\nLDIH R2, %d\nSETT R1, 2\n%s R1, R2\nWAITT R1\nSET UO, 0x01\nHALT\nNOP"
            % (mag & 0xFF, mag >> 8, "ADD" if delta > 0 else "SUB"))

def first_pin_write(tr):
    """The first trace cycle whose uo reads non-zero (the cycle after the SET executed), or None."""
    return next((t[0] for t in tr if t[1]), None)

def test_waitt_late_deadline_completes_in_one_cycle():
    # Deadlines 1, 300 and 32,767 ticks behind T when WAITT first executes: each completes in that one
    # cycle (cycle 4), so the SET after it executes in cycle 5 and is on the pin from cycle 6. Under the
    # v0 equality rule each would stall until T wrapped round to Rn (65,536 - d ticks). T's absolute value
    # does not matter (three starting values, including one where R1 wraps below 0).
    for t0 in (0, 0x8000, 0xFFFE):
        for d in (1, 300, 32767):
            s = Sim(assemble(waitt_program(-d)), t0=t0); tr = s.run(12)
            assert first_pin_write(tr) == 6, (t0, d, [t[1] for t in tr])
            assert s.halted, (t0, d)

def test_waitt_boundary_32768_ahead_waits_exactly():
    # 32,768 ticks ahead is the farthest deadline WAITT still treats as ahead: bit 15 of T - Rn is 1
    # (T - Rn == 0x8000), so it stalls and completes exactly when T == Rn, in cycle 4 + 32,768; the SET
    # follows in cycle 32,773 and is on the pin from cycle 32,774 -- not one cycle earlier or later.
    for t0 in (0, 0xFFFE):
        s = Sim(assemble(waitt_program(32768)), t0=t0); tr = s.run(4 + 32768 + 6)
        assert first_pin_write(tr) == 4 + 32768 + 2, (t0, first_pin_write(tr))
    # 32,769 ticks ahead is indistinguishable from 32,767 behind (T - Rn == 0x7FFF): it completes at once.
    s = Sim(assemble(waitt_program(32769))); tr = s.run(12)
    assert first_pin_write(tr) == 6, [t[1] for t in tr]

# TO = 1 (from a timed-out WAITF), then TO = 0 (from a WAITF that completes on its flag); in each state a
# late WAITT (deadline one tick behind) and an on-time one (two ticks ahead) must leave TO as it was.
# Observed with BTO: each check skips a failure marker, or branches to one, on the TO it expects; success
# leaves exactly 0x01 on uo. Shared with test/test_core.py's waitt_leaves_to_unchanged.
WAITT_TO_PROGRAM = """
        LDI   R3, 2
        WAITF RXV, R3        ; nothing queued: times out after 2 ticks, TO = 1
        SETT  R1, 0          ; R1 = T now: one tick behind when the WAITT executes
        WAITT R1             ; late: completes in its first cycle
        BTO   a              ; TO still 1: taken
        NOP
        SET   UO, 0x02       ; reached only if the late WAITT cleared TO
a:      SETT  R1, 3          ; two ticks ahead of the WAITT's first cycle
        WAITT R1             ; on time: completes when T == R1
        BTO   b
        NOP
        SET   UO, 0x04       ; reached only if the on-time WAITT cleared TO
b:      WAITF TXE, R3        ; core->host FIFO empty: completes at once, TO = 0
        SETT  R1, 0
        WAITT R1             ; late
        BTO   bad            ; TO still 0: not taken
        NOP
        SETT  R1, 3
        WAITT R1             ; on time
        BTO   bad
        NOP
        SET   UO, 0x01       ; success
        HALT
        NOP
bad:    SET   UO, 0x08       ; reached only if a WAITT set TO
        HALT
        NOP
"""

def test_waitt_leaves_to_unchanged():
    s = Sim(assemble(WAITT_TO_PROGRAM)); tr = s.run(40)
    assert s.halted and tr[-1][1] == 0x01, [t[1] for t in tr]
    assert s.flags["TO"] == 0

# A WAITT that stalls across T's wrap. T starts at 0xFFF8; SETT R1, 0 (cycle 0) and ADDT R1, 12 (cycle 1)
# put the deadline at 0x0004, four ticks past the wrap. The WAITT first executes in cycle 2 with T = 0xFFFA,
# ten ticks ahead of its deadline, so it must stall while T runs 0xFFFA..0xFFFF, 0 (cycle 8), 1, 2, 3 and
# complete exactly in cycle 12, when T == R1 == 4; the SET after it executes in cycle 13 and is on the pin
# from cycle 14. An unsigned compare that ignores the wrap (T >= Rn) releases it at once, in cycle 2; one
# that is wrap-safe only in the WAITT's first cycle releases it in cycle 3. Shared with test/test_core.py's
# waitt_stall_across_T_wrap_releases_at_deadline.
WAITT_WRAP_PROGRAM = "SETT R1, 0\nADDT R1, 12\nWAITT R1\nSET UO, 0x01\nHALT\nNOP"
WAITT_WRAP_T0 = 0xFFF8

def test_waitt_stall_across_T_wrap_releases_at_deadline():
    s = Sim(assemble(WAITT_WRAP_PROGRAM), t0=WAITT_WRAP_T0)
    tr = s.run(12)                                              # cycles 0..11: T 0xFFF8..0x0003
    assert s.regs[1] == 0x0004 and s.T == 0x0004, (s.regs[1], s.T)   # s.T is T in cycle 12
    assert s.pc == 2 and not s.halted                           # still on the WAITT after the wrap
    tr += [s.step()]                                            # cycle 12: T == Rn, completes
    assert s.pc == 3
    tr += s.run(4)
    assert first_pin_write(tr) == 14, [t[1] for t in tr]

# Zero timeout (isa.yaml semantics.waits): "If Rt's value is 0 the wait completes in its first cycle: TO = 0
# if the condition is already true, else TO = 1." The timeout register is R3 loaded with 0 (Rt = R0 would
# mean 65535). Each program runs a condition-false wait first (WAITF RXV: nothing queued; WAITP HIGH on
# ui[0], which is low), which must time out in its first cycle and set TO, then a condition-true one (WAITF
# TXE: the core->host FIFO is empty; WAITP LOW on ui[0]), which must complete in its first cycle and clear
# TO. BTO checks each TO, and each check is followed by a TGL of uo[0]: with every wait taking exactly one
# cycle uo[0] reads 1 in cycles 5-8 and 0 again from cycle 9. A first-cycle timeout that is missed stalls
# the wait until T comes round to the captured deadline again, 65,536 ticks later; a wrong TO puts a failure
# marker (0x40 or 0x20) on uo. Shared with test/test_core.py's zero_timeout_completes_in_first_cycle.
ZERO_TIMEOUT_WAITS = {"WAITF": ("WAITF RXV, R3", "WAITF TXE, R3"),
                      "WAITP": ("WAITP UI, 0, HIGH, R3", "WAITP UI, 0, LOW, R3")}

def zero_timeout_program(kind):
    false_wait, true_wait = ZERO_TIMEOUT_WAITS[kind]
    return """
        LDI   R3, 0          ; the timeout register holds 0
        {f:20} ; cycle 1: condition false -> times out in this cycle, TO = 1
        BTO   a              ; cycle 2: taken
        NOP
        SET   UO, 0x40       ; reached only if the wait left TO at 0
a:      TGL   UO, 0x01       ; cycle 4: uo[0] = 1 from cycle 5
        {t:20} ; cycle 5: condition already true -> completes in this cycle, TO = 0
        BTO   bad            ; cycle 6: not taken
        NOP
        TGL   UO, 0x01       ; cycle 8: uo[0] = 0 from cycle 9
        HALT
        NOP
bad:    SET   UO, 0x20       ; reached only if the wait left TO at 1
        HALT
        NOP
""".format(f=false_wait, t=true_wait)

ZERO_TIMEOUT_UO = [0] * 5 + [1] * 4 + [0] * 3                   # uo in cycles 0..11

def test_zero_timeout_completes_in_first_cycle():
    for kind in ZERO_TIMEOUT_WAITS:
        s = Sim(assemble(zero_timeout_program(kind))); tr = s.run(12)
        assert [t[1] for t in tr] == ZERO_TIMEOUT_UO, (kind, [t[1] for t in tr])
        assert s.halted and s.flags["TO"] == 0, kind

def test_uart_tx_firmware_bit_timing():
    s = Sim(assemble((FIRMWARE / "uart_tx.s").read_text()), prescale=2); tr = s.run(11 * 434 + 20)
    tx = [t[1] & 1 for t in tr]
    edges = [i for i in range(1, len(tx)) if tx[i] != tx[i-1]]
    # 0x55 = 01010101: start 0, then 1,0,1,0,1,0,1,0, stop 1 -> an edge at every bit boundary.
    # Count them: reset-low -> idle-high, idle -> start, then the 9 boundaries start/d0..d7/stop
    # = 11 edges, and the line must be left high (stop bit). Spacing alone let a 6-data-bit or
    # stop-bit-low firmware pass (mutants F1/F3, caught before only by the cocotb equivalence test).
    assert len(edges) == 11, edges
    assert all(b - a == 434 for a, b in zip(edges[1:], edges[2:])), edges[:12]   # every bit boundary after idle->start
    assert tx[-1] == 1 and s.halted
