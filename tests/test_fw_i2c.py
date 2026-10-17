"""firmware/i2c_master.s on the oracle (tools/sim.py) against the reference I2C slave and
standard-mode checker tools/refmodels/i2c_slave_ref.py, plus tests of the reference model itself on
synthetic master traces. CLK_HZ, i2c_cmd, NACK/TIMEOUT/STRETCHED, CASES, MUTANT_Q and the case
helpers are also imported by the cocotb suite test/test_i2c_fw.py (the same cases on the RTL).

Timing comes from the protocol (CLK_HZ and the standard-mode table inside the model), never from the
firmware's .equ block; the only .equ read is PRESCALE (to program the timebase the way the host
would)."""
import pytest

from tools.refmodels.i2c_slave_ref import I2cSlaveRef
from tests.fw_harness import FIRMWARE, load, run_model

CLK_HZ = 50_000_000
NACK, TIMEOUT, STRETCHED = 0x100, 0x200, 0x400
def i2c_cmd(data=0, start=False, stop=False, read=False, nack=False):
    """Command word: data[7:0] (for a read: bit 0 = 1 answers with NACK), START[8], STOP[9], READ[10]."""
    return (1 if (read and nack) else data & 0xFF) | (0x100 if start else 0) | (0x200 if stop else 0) | (0x400 if read else 0)
ADDR = 0x50
def wr(addr): return (addr << 1) | 0
def rd(addr): return (addr << 1) | 1
def case(slave, words, expect, at=None):
    return {"slave": slave, "words": words, "expect": expect, "at": at}
CASES = {  # slave: I2cSlaveRef kwargs; words: host commands; expect: result words; at: cycle from which word i may be pushed
    "write2": case({}, [i2c_cmd(wr(ADDR), start=True), i2c_cmd(0xA5), i2c_cmd(0x3C, stop=True)], [wr(ADDR), 0xA5, 0x3C]),
    "read2":  case({"read_data": [0x11, 0x22]}, [i2c_cmd(rd(ADDR), start=True), i2c_cmd(read=True), i2c_cmd(read=True, nack=True, stop=True)], [rd(ADDR), 0x11, 0x22]),
    "write_restart_read": case({"read_data": [0x7E]}, [i2c_cmd(wr(ADDR), start=True), i2c_cmd(0x10), i2c_cmd(rd(ADDR), start=True), i2c_cmd(read=True, nack=True, stop=True)], [wr(ADDR), 0x10, rd(ADDR), 0x7E]),
    "addr_nack": case({}, [i2c_cmd(wr(0x51), start=True, stop=True)], [wr(0x51) | NACK]),
    "data_nack": case({"nack_data_after": 1}, [i2c_cmd(wr(ADDR), start=True), i2c_cmd(0x01), i2c_cmd(0x02, stop=True)], [wr(ADDR), 0x01 | NACK, 0x02 | NACK]),
    "stretch": case({"stretch_after_byte": (0, 1000)}, [i2c_cmd(wr(ADDR), start=True), i2c_cmd(0x5A, stop=True)], [wr(ADDR), 0x5A | STRETCHED]),
    "timeout": case({"stretch_after_byte": (0, 80_000)}, [i2c_cmd(wr(ADDR), start=True), i2c_cmd(0x5A, stop=True), i2c_cmd(wr(ADDR), start=True, stop=True)],
                    [wr(ADDR), 0x5A | TIMEOUT, wr(ADDR)], at=[0, 0, 90_000]),
}
MUTANT_Q = ("Q        128", "Q        96")


def cycle_budget(c):
    """6,000 cycles per command plus one more 6,000 (a byte is nine 10.24 us bits = 4,608 cycles; a
    command with START and STOP takes about 6,600), plus 100,000 for the timeout case (80,000-cycle
    stretch, third word at 90,000)."""
    return 6000 * (len(c["words"]) + 1) + (100_000 if c["slave"].get("stretch_after_byte", (0, 0))[1] > 65_535 else 0)

def model_for(c):
    return I2cSlaveRef(CLK_HZ, ADDR, **c["slave"])

def kinds(ref): return [e[0] for e in ref.events]
def byte_events(ref): return [e for e in ref.events if e[0] == "BYTE"]

def case_errors(name, ref, pushes):
    """The checks every firmware case makes (oracle and RTL), as a list of error strings: no
    violation, the pushed results, and the slave's view of the transfer."""
    c = CASES[name]; errors = list(ref.violations)
    got = [w for _, w in pushes]
    if got != c["expect"]: errors.append("pushed %s, expected %s" % ([hex(w) for w in got], [hex(w) for w in c["expect"]]))
    ks, bs = kinds(ref), byte_events(ref)
    def want(cond, what):
        if not cond: errors.append("%s: events %s, written %s" % (what, ref.events, ref.written))
    if name == "write2":
        want(ref.written == [0xA5, 0x3C], "written")
        want(ks == ["START", "BYTE", "BYTE", "BYTE", "STOP"], "START, 3 bytes, STOP")
        want([(b[2], b[3], b[4]) for b in bs] == [(wr(ADDR), True, "W"), (0xA5, True, "W"), (0x3C, True, "W")], "bytes")
    elif name == "read2":
        want([(b[2], b[3], b[4]) for b in bs] == [(rd(ADDR), True, "W"), (0x11, True, "R"), (0x22, False, "R")], "two R bytes, the second NACKed")
        want(ks[0] == "START" and ks[-1] == "STOP" and ks.count("START") == 1, "one START, one STOP")
    elif name == "write_restart_read":
        want(ks.count("START") == 2 and ks.count("STOP") == 1 and ks[-1] == "STOP", "two STARTs, one STOP")
        want([(b[2], b[3], b[4]) for b in bs] == [(wr(ADDR), True, "W"), (0x10, True, "W"), (rd(ADDR), True, "W"), (0x7E, False, "R")], "bytes")
        want(ref.written == [0x10], "written")
    elif name == "addr_nack":
        want(ks == ["START", "BYTE", "STOP"] and bs[0][3] is False, "address NACKed, then STOP")
    elif name == "data_nack":
        want(ref.written == [0x01, 0x02] and [b[3] for b in bs] == [True, False, False], "data bytes NACKed")
    elif name == "stretch":
        want(ref.written == [0x5A] and ks == ["START", "BYTE", "BYTE", "STOP"], "transfer completes")
        lows = [v for _, v in ref.measured["tLOW"]]
        want(max(lows) >= 1000, "the stretched low is on the bus (max tLOW %d)" % max(lows))
    elif name == "timeout":
        # 0x5A is abandoned in its first bit (no byte, no STOP); the third command's START succeeds
        want(ks == ["START", "BYTE", "START", "BYTE", "STOP"], "abandoned byte, then a START that works")
        want([(b[2], b[3]) for b in bs] == [(wr(ADDR), True), (wr(ADDR), True)], "both addresses ACKed")
        want(ref.written == [], "nothing written")
    return errors


# ---- the reference model on its own (synthetic master traces, no firmware) ---------------------

QS = 125                                 # the synthetic master's quarter period (10.0 us SCL period)

def perfect_master(addr_byte, data_byte, q=QS, short_high=None, high_glitch=None, late_stop=None):
    """A textbook master, one uio_oe value per cycle (uio_out stays 0): idle, START (SDA falls 2q
    after both lines are high, SCL falls 2q later), the address byte and a data byte (SDA set q
    after each SCL fall, SCL high 2q from q after that, the ACK slot released), STOP (SDA low q
    after the last fall, SCL released at 2q, SDA released 2q after the rise), idle. Returns
    (oe list, marks) where marks records the cycle of each injected fault. Faults:
    short_high = n shortens bit n's SCL high time (bit 0 = the address MSB) to 150 cycles and adds
    the difference to the following low (the period is unchanged); high_glitch = n flips SDA in the
    middle of bit n's high time; late_stop releases SDA only 50 cycles after the STOP's SCL rise."""
    oe = []; st = {"sda": 0, "scl": 0}; marks = {}
    def emit(n): oe.extend([(st["scl"] << 1) | st["sda"]] * n)
    emit(10)
    emit(2 * q); st["sda"] = 1; emit(2 * q); st["scl"] = 1            # START
    n = 0
    for byte in (addr_byte, data_byte):
        for i in range(9):
            level = (byte >> (7 - i)) & 1 if i < 8 else 1               # the ACK slot: released
            emit(q); st["sda"] = 1 - level; emit(q); st["scl"] = 0       # SCL released
            if short_high == n:
                emit(150); st["scl"] = 1; marks["fall"] = len(oe); emit(2 * q - 150)
            elif high_glitch == n:
                emit(q); st["sda"] ^= 1; marks["glitch"] = len(oe); emit(q); st["scl"] = 1
            else:
                emit(2 * q); st["scl"] = 1
            n += 1
    emit(q); st["sda"] = 1; emit(q); st["scl"] = 0                       # STOP
    if late_stop: emit(50); st["sda"] = 0; marks["stop"] = len(oe); emit(4 * q - 50)
    else: emit(2 * q); st["sda"] = 0; emit(2 * q)
    emit(10)
    return oe, marks

def drive(ref, oe):
    return [ref.step(0, 0, v)[1] for v in oe]

def test_i2c_ref_accepts_a_perfect_master():
    oe, _ = perfect_master(wr(ADDR), 0xA5)
    ref = I2cSlaveRef(CLK_HZ, ADDR)
    uio = drive(ref, oe)
    assert ref.finish() == []
    assert ref.written == [0xA5]
    assert [e[0] for e in ref.events] == ["START", "BYTE", "BYTE", "STOP"]
    assert [(e[2], e[3], e[4]) for e in byte_events(ref)] == [(wr(ADDR), True, "W"), (0xA5, True, "W")]
    assert all(u & 0xFC == 0xFC for u in uio)
    # the slave's ACK: SDA low on the bus T_SLAVE after the eighth fall, released T_SLAVE after the ninth
    falls = [k for k in range(1, len(uio)) if uio[k - 1] & 2 and not uio[k] & 2]
    f8, f9 = falls[1 + 7], falls[1 + 8]                                  # falls[0] ends the START
    assert all(uio[j] & 1 == 0 for j in range(f8 + 5, f9 + 5)) and uio[f9 + 5] & 1 == 1
    # every measured interval exactly as built (q = 125)
    m = {n: {v for _, v in ref.measured[n]} for n in ref.measured}
    assert m["tLOW"] == {250} and m["tHIGH"] == {250} and min(m["period"]) == 500
    assert m["tHD;STA"] == {250} and m["tSU;STO"] == {250} and m["tHD;DAT"] == {125}

def test_i2c_ref_serves_reads_and_stretches():
    """Read side: the slave drives read_data T_SLAVE after each fall and lets go for the master's
    ACK; stretch_after_byte holds SCL low across the master's release."""
    oe, _ = perfect_master(rd(ADDR), 0xFF)                               # master releases SDA for the data byte
    ref = I2cSlaveRef(CLK_HZ, ADDR, read_data=[0x96], stretch_after_byte=(0, 300))
    uio = drive(ref, oe)
    (b0, b1) = byte_events(ref)
    assert (b0[2], b0[3], b0[4]) == (rd(ADDR), True, "W")
    assert (b1[2], b1[4]) == (0x96, "R") and b1[3] is False             # the trace NACKs (SDA released)
    lows = [v for _, v in ref.measured["tLOW"]]
    assert max(lows) == 300 and all(u & 2 == 0 for u in uio[b0[1]:b0[1] + 300])
    # the synthetic master keeps its own grid (it does not re-time its high period from the observed
    # rise), so the stretch eats 50 cycles of that high time and the next period is 450: exactly
    # the error a master must avoid by measuring tHIGH from the rise, as the firmware does
    assert len(ref.violations) == 1 and "period 450" in ref.violations[0], ref.violations

def one_violation(ref, oe):
    drive(ref, oe)
    assert len(ref.violations) == 1, ref.violations
    return ref.violations[0]

def test_i2c_ref_rejects_a_short_high_time():
    oe, marks = perfect_master(wr(ADDR), 0xA5, short_high=3)
    v = one_violation(I2cSlaveRef(CLK_HZ, ADDR), oe)
    assert v.startswith("cycle %d:" % marks["fall"]) and "tHIGH 150" in v, v

def test_i2c_ref_rejects_sda_changed_while_scl_high_mid_byte():
    oe, marks = perfect_master(wr(ADDR), 0xA5, high_glitch=12)           # data byte, bit 3
    v = one_violation(I2cSlaveRef(CLK_HZ, ADDR), oe)
    assert v.startswith("cycle %d:" % marks["glitch"]) and "while SCL high in bit 4" in v, v

def test_i2c_ref_finish_rejects_an_open_transaction_and_a_half_byte():
    oe, _ = perfect_master(wr(ADDR), 0xA5)
    stop = 10 + 4 * QS + 18 * 4 * QS                                     # the last ACK bit's fall
    ref = I2cSlaveRef(CLK_HZ, ADDR); drive(ref, oe[:stop + 10])          # both bytes, no STOP
    assert ref.violations == [] and ref.finish(stop_expected=False) == []
    assert ref.finish() and "no STOP" in ref.violations[-1] and "START at cycle %d" % (10 + 2 * QS) in ref.violations[-1], ref.violations
    half = 10 + 4 * QS + 12 * 4 * QS + 10                                # 3 bits into the data byte
    ref = I2cSlaveRef(CLK_HZ, ADDR); drive(ref, oe[:half])
    assert ref.finish(stop_expected=False) == ["cycle %d: run ended in bit 4 of a byte" % half], ref.violations

def test_i2c_ref_rejects_a_short_stop_setup():
    oe, marks = perfect_master(wr(ADDR), 0xA5, late_stop=True)
    v = one_violation(I2cSlaveRef(CLK_HZ, ADDR), oe)
    assert v.startswith("cycle %d:" % marks["stop"]) and "tSU;STO 50" in v, v


# ---- the firmware on the oracle -------------------------------------------------------------

def run_case(name, text=None):
    c = CASES[name]; at = c["at"]
    words, equs = load("i2c_master.s", text)
    ref = model_for(c)
    pushes = run_model(words, equs["PRESCALE"], ref, cycle_budget(c), host_words=c["words"],
                       host_at=(lambda i: at[i]) if at else None)
    ref.finish()
    return ref, pushes

@pytest.mark.parametrize("name", list(CASES))
def test_i2c_master_firmware_matches_reference(name):
    ref, pushes = run_case(name)
    errors = case_errors(name, ref, pushes); assert errors == [], errors

def test_i2c_master_stop_then_start_meets_tbuf():
    """Added beyond the plan: no case has a STOP followed by a START (repeated STARTs and the
    timeout's retry are not after a STOP), so tBUF is exercised here: an address NACK with STOP, then
    a new transaction."""
    words, equs = load("i2c_master.s"); ref = I2cSlaveRef(CLK_HZ, ADDR)
    pushes = run_model(words, equs["PRESCALE"], ref, 18_000,
                       host_words=[i2c_cmd(wr(0x51), start=True, stop=True), i2c_cmd(wr(ADDR), start=True, stop=True)])
    assert ref.finish() == []
    assert [w for _, w in pushes] == [wr(0x51) | NACK, wr(ADDR)]
    assert kinds(ref) == ["START", "BYTE", "STOP", "START", "BYTE", "STOP"] and len(ref.measured["tBUF"]) == 1

def test_i2c_master_sentinel_mutant_is_rejected():
    src = (FIRMWARE / "i2c_master.s").read_text(); assert MUTANT_Q[0] in src
    ref, _ = run_case("write2", src.replace(*MUTANT_Q, 1))
    assert ref.violations, "the reference accepted a 25 % fast SCL (Q 96)"
