"""firmware/uart_rx.s on the oracle (tools/sim.py) against the 8N1 reference receiver checker
tools/refmodels/uart_rx_ref.py, plus tests of the reference model itself. CASES, CLK_HZ, BAUD and
MUTANT_BIT are also imported by the cocotb suite test/test_uart_rx_fw.py (the same cases on the RTL).

Timing comes from the protocol (CLK_HZ, BAUD), never from the firmware's .equ block; the only .equ
read is PRESCALE (to program the timebase the way the host would)."""
import pytest

from tools.refmodels.uart_rx_ref import UartRxRef, Frame, PUSH_SLACK
from tests.fw_harness import FIRMWARE, load, run_model

CLK_HZ, BAUD = 50_000_000, 115200
CASES = {
    "nominal":   [Frame(0x55), Frame(0x00), Frame(0xFF), Frame(0xAA, gap=0), Frame(0xA3, gap=0)],
    "slow_4pct": [Frame(0x55, baud_error=-0.04), Frame(0xC3, baud_error=-0.04, gap=0)],
    "fast_4pct": [Frame(0x55, baud_error=+0.04), Frame(0xC3, baud_error=+0.04, gap=0)],
    "probe":     [Frame(0x55, probe=True), Frame(0xFF, probe=True, gap=150), Frame(0x00, probe=True, gap=150), Frame(0x96, probe=True, gap=150)],
    "framing":   [Frame(0x12, stop_low=True), Frame(0x34)],
    "glitch":    [Frame(0, glitch=100), Frame(0x5A)],
    "long_idle": [Frame(0x01, gap=140_000), Frame(0x02)],   # 70,000 ticks: the 65,535-tick WAITP times out once and rearms
    "break":     [Frame(0, brk=20_000), Frame(0x5A)],        # 46 bits low: one framing-error word, then the next frame intact
}
MUTANT_BIT = ("BIT      217", "BIT      210")   # the in-suite sentinel: 3 % fast -> probe frames must fail
CPB = CLK_HZ / BAUD                     # cycles per bit, 434.027...
TOL = int(CPB / 8)                      # the spec's +-12.5 % of a bit (54 cycles)


# ---- the reference model on its own (no firmware) --------------------------------------------

def test_uart_ref_plain_frame_shape():
    ref = UartRxRef(CLK_HZ, BAUD); ref.schedule([Frame(0x55, gap=0)], lead_in=10)
    line = ref.line
    assert line[:10] == [1] * 10
    bounds = [int(10 + i * CPB) for i in range(11)]
    for i, b in enumerate([0, 1, 0, 1, 0, 1, 0, 1, 0, 1]):         # start, d0..d7 LSB first, stop
        cell = line[bounds[i]:bounds[i + 1]]
        assert len(cell) in (434, 435) and set(cell) == {b}, (i, len(cell), set(cell))
    assert len(line) == bounds[10]
    stop = int(10 + 9.5 * CPB)
    assert TOL == 54 and PUSH_SLACK == 32
    assert ref.expected == [(0x55, stop - 54, stop + 54 + 32)]
    assert ref.cycles == len(line) + int(4 * CPB)
    levels = [ref.step(0, 0, 0) for _ in range(len(line) + 3)]
    assert [ui & 1 for ui, _ in levels[:len(line)]] == line
    assert all(ui == 0x0E | (ui & 1) and uio == 0xFF for ui, uio in levels)
    assert levels[-3:] == [(0x0F, 0xFF)] * 3                         # idle high after the schedule


@pytest.mark.parametrize("byte", [0xFF, 0x00])
def test_uart_ref_probe_frame_is_complement_outside_window(byte):
    ref = UartRxRef(CLK_HZ, BAUD); ref.schedule([Frame(byte, probe=True, gap=0)], lead_in=10)
    line = ref.line
    bounds = [int(10 + i * CPB) for i in range(11)]
    assert set(line[bounds[0]:bounds[1]]) == {0}                    # start bit untouched
    centre = int(10 + 9.5 * CPB)                                    # the stop bit: high only near its sample instant
    for k in range(bounds[9], bounds[10]):
        assert line[k] == (1 if abs(k - centre) <= TOL else 0), (k, centre)
    assert 0 in line[bounds[9]:bounds[10]] and 1 in line[bounds[9]:bounds[10]]
    v = byte & 1
    for i in range(8):
        centre = int(10 + (i + 1.5) * CPB)
        for k in range(bounds[i + 1], bounds[i + 2]):
            want = v if abs(k - centre) <= TOL else 1 - v
            assert line[k] == want, (i, k, centre)
    assert ref.expected == [(byte, int(10 + 9.5 * CPB) - TOL, int(10 + 9.5 * CPB) + TOL + PUSH_SLACK)]


def test_uart_ref_probe_frame_needs_a_gap_after_it():
    ref = UartRxRef(CLK_HZ, BAUD)
    with pytest.raises(ValueError, match="gap of at least bit/4"):
        ref.schedule([Frame(0x55, probe=True), Frame(0xFF, gap=0)])
    with pytest.raises(ValueError):
        ref.schedule([Frame(0x55, probe=True), Frame(0xFF, gap=int(CPB) // 4 - 1)])
    ref.schedule([Frame(0x55, probe=True), Frame(0xFF, gap=int(CPB) // 4)])
    ref.schedule([Frame(0x55, probe=True), Frame(0xFF)])            # the default gap (2 bits) is fine


def test_uart_ref_options_shape():
    """Added beyond the plan: baud_error stretches every bit, stop_low sets bit 8 of the expected
    word, glitch drives a low pulse and expects nothing, gap defaults to two (nominal) bits."""
    ref = UartRxRef(CLK_HZ, BAUD)
    ref.schedule([Frame(0x01, baud_error=-0.04, gap=0), Frame(0x02, stop_low=True), Frame(0, glitch=100)], lead_in=10)
    slow = CLK_HZ / (BAUD * 0.96)
    b = [int(10 + i * slow) for i in range(11)]
    assert set(ref.line[b[0]:b[1]]) == {0} and set(ref.line[b[1]:b[2]]) == {1} and set(ref.line[b[2]:b[9]]) == {0}
    assert set(ref.line[b[9]:b[10]]) == {1}
    p2 = 10 + 10 * slow + 2 * CPB                                   # default gap: two nominal bits
    assert set(ref.line[b[10]:int(p2)]) == {1}
    c = [int(p2 + i * CPB) for i in range(11)]
    assert set(ref.line[c[0]:c[1]]) == {0} and set(ref.line[c[9]:c[10]]) == {0}   # stop bit driven low
    p3 = p2 + 10 * CPB + 2 * CPB
    assert set(ref.line[c[10]:int(p3)]) == {1}
    assert ref.line[int(p3):] == [0] * (int(p3 + 100) - int(p3))     # the glitch: 100 low cycles, line ends
    s1, s2 = int(10 + 9.5 * CPB), int(p2 + 9.5 * CPB)               # stop sample at the NOMINAL rate
    assert ref.expected == [(0x01, s1 - TOL, s1 + TOL + PUSH_SLACK), (0x102, s2 - TOL, s2 + TOL + PUSH_SLACK)]
    with pytest.raises(ValueError):
        Frame(0x01, baud_error=0.04, probe=True)


def test_uart_ref_break_shape():
    """A break: the line low for brk cycles from the end of the gap, then idle; exactly one 0x100
    expected in the window measured from the break's start as if it were a start edge."""
    ref = UartRxRef(CLK_HZ, BAUD); ref.schedule([Frame(0, brk=5000), Frame(0x5A)], lead_in=10)
    start = int(10 + 2 * CPB)
    assert ref.line[:start] == [1] * start and ref.line[start:start + 5000] == [0] * 5000
    assert set(ref.line[start + 5000:int(start + 5000 + 2 * CPB)]) == {1}
    s1, s2 = int(10 + 2 * CPB + 9.5 * CPB), int(10 + 2 * CPB + 5000 + 2 * CPB + 9.5 * CPB)
    assert ref.expected == [(0x100, s1 - TOL, s1 + TOL + PUSH_SLACK), (0x5A, s2 - TOL, s2 + TOL + PUSH_SLACK)]
    ref.schedule(CASES["break"]); assert [w for w, _, _ in ref.expected] == [0x100, 0x5A]
    with pytest.raises(ValueError, match="at least one frame"):
        ref.schedule([Frame(0, brk=int(10 * CPB))])
    with pytest.raises(ValueError):
        Frame(0x01, brk=5000)


def test_uart_ref_check_rejects_wrong_word_count_value_and_time():
    ref = UartRxRef(CLK_HZ, BAUD); ref.schedule([Frame(0x55)])
    (word, lo, hi), = ref.expected
    assert ref.check([(lo, word)]) == [] and ref.check([(hi, word)]) == []
    assert len(ref.check([])) == 1
    assert len(ref.check([(lo, word), (hi + 500, 0x00)])) == 1
    assert len(ref.check([(lo, word ^ 0x01)])) == 1
    assert len(ref.check([(lo - 1, word)])) == 1
    assert len(ref.check([(hi + 1, word)])) == 1


# ---- the firmware on the oracle -------------------------------------------------------------

def run_case(frames, text=None):
    words, equs = load("uart_rx.s", text)
    ref = UartRxRef(CLK_HZ, BAUD); ref.schedule(frames)
    pushes = run_model(words, equs["PRESCALE"], ref, ref.cycles)
    return ref.check(pushes), pushes

@pytest.mark.parametrize("name", sorted(CASES))
def test_uart_rx_firmware_matches_reference(name):
    errors, _ = run_case(CASES[name]); assert errors == [], errors

# the idle wait (line high before looking for a start bit) removed: the reviewer's mutant U-new
IDLE_WAIT = ("  WAITP UI, 0, HIGH, R0   ; idle line first (also waits out a break after a framing error); timeout rearms\n"
             "  BTO  frame\n", "  NOP\n  NOP\n")

def test_uart_rx_break_fails_without_the_idle_wait():
    """The break case is not vacuous: without the idle wait the rest of the break is read as more
    frames (more 0x100 words, then a corrupt one), so the push count is wrong."""
    src = (FIRMWARE / "uart_rx.s").read_text(); assert src.count(IDLE_WAIT[0]) == 1
    errors, pushes = run_case(CASES["break"], src.replace(*IDLE_WAIT, 1))
    assert errors and "expected 2 pushes" in errors[0] and len(pushes) > 2, (errors, pushes)

def test_uart_rx_sentinel_mutant_is_rejected():
    src = (FIRMWARE / "uart_rx.s").read_text(); assert MUTANT_BIT[0] in src
    errors, _ = run_case(CASES["probe"], src.replace(*MUTANT_BIT, 1)); assert errors, "the probe frames did not reject a 3 % fast BIT"


# ---- regression: a start bit that lands while the timed-out start wait rearms ----------------

REARM_OLD = ("""frame:
  WAITP UI, 0, HIGH, R0   ; idle line first (also waits out a break after a framing error); timeout rearms
  BTO  frame
  NOP
start:
  WAITP UI, 0, LOW, R0    ; the start bit: a level wait, so an edge that lands while the timed-out wait rearms is still caught
  BTO  start
  SETT R1, HALF           ; delay slot: R1 = middle of the start bit (harmless when rearming)
""", """frame:
  WAITP UI, 0, FALL, R0   ; start edge; the 65,535-tick timeout just rearms the wait
  BTO  frame
  SETT R1, HALF           ; delay slot: R1 = middle of the start bit (harmless when rearming)
""")

@pytest.mark.parametrize("gap", [130_870, 130_871, 130_872, 130_873])
def test_uart_rx_start_during_rearm(gap):
    """The first start wait times out after 65,535 ticks (131,070 cycles) and rearms; a start bit
    landing in those few cycles must still be received (level waits catch it; an edge wait misses it)."""
    errors, _ = run_case([Frame(0x01, gap=gap), Frame(0x02)]); assert errors == [], errors

@pytest.mark.parametrize("gap", [130_871, 130_872])
def test_uart_rx_rearm_regression_fails_on_the_edge_wait_firmware(gap):
    """Guard for the regression test above: the old FALL-wait text must fail it."""
    src = (FIRMWARE / "uart_rx.s").read_text(); assert src.count(REARM_OLD[0]) == 1
    errors, _ = run_case([Frame(0x01, gap=gap), Frame(0x02)], src.replace(*REARM_OLD, 1)); assert errors
