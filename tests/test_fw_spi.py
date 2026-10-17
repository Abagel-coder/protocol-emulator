"""firmware/spi_master.s on the oracle (tools/sim.py) against the reference SPI slave and master
checker tools/refmodels/spi_slave_ref.py, plus tests of the reference model itself on synthetic
master traces. CLK_HZ, SCK_HZ, spi_cmd, CASES, MUTANT_HALF and host_words are also imported by the
cocotb suite test/test_spi_fw.py (the same cases on the RTL).

Timing comes from the protocol (CLK_HZ, SCK_HZ), never from the firmware's .equ block; the only
.equ read is PRESCALE (to program the timebase the way the host would)."""
import pytest

from tools.refmodels.spi_slave_ref import SpiSlaveRef
from tests.fw_harness import FIRMWARE, load, run_model

CLK_HZ, SCK_HZ = 50_000_000, 1_000_000
def spi_cmd(byte, mode, last=False): return byte | (0x100 if last else 0) | (mode << 9)
TX = [0x83, 0x1C, 0xA6]; RX = [0xC1, 0x0F, 0x9A]   # no byte reads the same bit-reversed: bit order shows
def case(modes, txs, miso, window=True, at=None):
    return {"modes": modes, "txs": txs, "miso": miso, "window": window, "at": at}
CASES = {  # modes: one per transaction; txs: the bytes of each transaction; at: cycle from which word i may be pushed
    "mode0": case([0], [TX], RX), "mode1": case([1], [TX], RX), "mode2": case([2], [TX], RX), "mode3": case([3], [TX], RX),
    "mode_change": case([0, 3], [[0x55], [0xAA, 0x01]], [0x12, 0x34, 0x56], window=False),
    "single_byte": case([2], [[0x80]], [0x01]),
    "late_words": case([0], [TX], RX, at=[0, 3000, 6000]),      # gaps between bytes longer than a byte
}
MUTANT_HALF = ("HALF     25", "HALF     27")
P = CLK_HZ // SCK_HZ                    # nominal SCK period in cycles (50)
H = P // 2                              # half period (25)


def host_words(c):
    """The host->core command words of a case, in order (LAST on each transaction's final byte)."""
    return [spi_cmd(b, m, last=(i == len(tx) - 1)) for m, tx in zip(c["modes"], c["txs"]) for i, b in enumerate(tx)]

def cycle_budget(c):
    return 400 * (len(host_words(c)) + 2) + 2000 + (c["at"][-1] if c["at"] else 0)

def model_for(c):
    return SpiSlaveRef(CLK_HZ, SCK_HZ, c["modes"], c["miso"], miso_window=P // 8 if c["window"] else None)

def case_errors(c, ref, pushes):
    """The four checks every firmware case makes (oracle and RTL), as a list of error strings."""
    n = len(host_words(c)); errors = list(ref.violations)
    got = [w for _, w in pushes]
    if got != c["miso"][:n]: errors.append("pushed %s, expected %s" % ([hex(w) for w in got], [hex(w) for w in c["miso"][:n]]))
    want_mosi = [b for tx in c["txs"] for b in tx]
    if ref.mosi_bytes != want_mosi: errors.append("slave received %s, expected %s" % ([hex(b) for b in ref.mosi_bytes], [hex(b) for b in want_mosi]))
    if len(ref.transactions) != len(c["txs"]): errors.append("transactions %s, expected %d" % (ref.transactions, len(c["txs"])))
    return errors


# ---- the reference model on its own (synthetic master traces, no firmware) ---------------------

def perfect_master(mode, data, P, *, reset=True, late=None, mosi_glitch=None, sck_pulse=False):
    """A textbook master, one uo value per cycle: CS_n high, SCK to CPOL, CS_n low, each bit's two
    edges H apart (MOSI changed on the shifting edge; CPHA=0 sets the first bit up when CS_n
    falls), H idle between bytes, H from the last edge to CS_n's rise. Returns (uo list, sampling
    edge cycles). Faults: late = n delays edge n (and everything after it) by 3 cycles;
    mosi_glitch = n flips MOSI 2 cycles before sampling edge n; sck_pulse raises SCK for 5 cycles
    while CS_n is high (two level changes)."""
    cpol, cpha = mode >> 1, mode & 1
    H = P // 2
    uo, sampling = [], []
    st = {"sck": 0, "mosi": 0, "cs": 1 if not reset else 0, "edges": 0}

    def emit(n):
        uo.extend([(st["cs"] << 3) | (st["mosi"] << 2) | (st["sck"] << 1)] * n)

    def edge():
        if late == st["edges"]: emit(3)
        st["sck"] ^= 1; st["edges"] += 1

    def setup(n_cycles):           # hold n_cycles before a sampling edge, with the optional glitch
        if mosi_glitch == len(sampling): emit(n_cycles - 2); st["mosi"] ^= 1; emit(2)
        else: emit(n_cycles)

    if reset: emit(3)              # uo resets low: CS_n not yet seen high
    st["cs"] = 1; emit(4)
    st["sck"] = cpol; emit(H)      # the CPOL switch (no change for CPOL = 0)
    if sck_pulse: st["sck"] ^= 1; emit(5); st["sck"] ^= 1; emit(H)
    st["cs"] = 0
    if cpha: emit(H)               # CS_n lead before the first (shifting) edge
    for j, byte in enumerate(data):
        for i in range(8):
            b = (byte >> (7 - i)) & 1
            if cpha == 0:
                st["mosi"] = b; setup(H); edge(); sampling.append(len(uo)); emit(H); edge()
            else:
                edge(); st["mosi"] = b; setup(H); edge(); sampling.append(len(uo)); emit(H)
        if j < len(data) - 1: emit(H)                  # between bytes
    if cpha == 0: emit(H)          # the trailing edge's cycle and the CS_n lag
    st["cs"] = 1; emit(2 * H)
    return uo, sampling

def drive(ref, uo):
    return [ref.step(u, 0, 0)[0] for u in uo]


@pytest.mark.parametrize("mode", [0, 3])
def test_spi_ref_accepts_a_perfect_master(mode):
    data, miso = [0x83, 0x1C], [0xC1, 0x9A]
    uo, sampling = perfect_master(mode, data, P)
    ref = SpiSlaveRef(CLK_HZ, SCK_HZ, mode, miso, miso_window=P // 8)
    ui = drive(ref, uo)
    assert ref.violations == []
    assert ref.mosi_bytes == data and ref.miso_expected == miso
    (t,) = ref.transactions
    assert t["edges"] == 32 and uo[t["cs_fall"]] >> 3 & 1 == 0 and uo[t["cs_fall"] - 1] >> 3 & 1 == 1
    assert uo[t["cs_rise"]] >> 3 & 1 == 1 and uo[t["cs_rise"] - 1] >> 3 & 1 == 0
    bits = [(b >> (7 - i)) & 1 for b in miso for i in range(8)]
    assert len(sampling) == 16
    first_of_byte = {0, 8} if mode & 1 == 0 else set()     # CPHA=0: each byte's MSB is driven plainly
    for n, (e, b) in enumerate(zip(sampling, bits)):
        assert all(ui[k] == (b << 1) | 0x0D for k in range(e - P // 8, e + P // 8 + 1)), (n, e)
        if n not in first_of_byte:                           # the window: complement just outside it
            assert ui[e - P // 8 - 1] >> 1 & 1 == 1 - b and ui[e + P // 8 + 1] >> 1 & 1 == 1 - b, (n, e)
    assert all(u & 0x0D == 0x0D for u in ui)


def test_spi_ref_without_window_holds_each_bit_to_the_next_shifting_edge():
    uo, sampling = perfect_master(1, [0xA6], P)
    ref = SpiSlaveRef(CLK_HZ, SCK_HZ, 1, [0x59], t_co=5)
    ui = drive(ref, uo)
    assert ref.violations == [] and ref.miso_expected == [0x59] and ref.mosi_bytes == [0xA6]
    edges = ref.edge_cycles[0]
    for i in range(8):                                       # CPHA=1: bit i shifted on edge 2i
        b = (0x59 >> (7 - i)) & 1
        end = edges[2 * i + 2] + 5 if i < 7 else ref.transactions[0]["cs_rise"]
        assert all(ui[k] >> 1 & 1 == b for k in range(edges[2 * i] + 5, end)), i


def test_spi_ref_mode_list_and_missing_mode():
    a, _ = perfect_master(0, [0x55], P)
    b, _ = perfect_master(3, [0xAA], P, reset=False)
    ref = SpiSlaveRef(CLK_HZ, SCK_HZ, [0, 3], [0x12, 0x34]); drive(ref, a + b)
    assert ref.violations == [] and ref.mosi_bytes == [0x55, 0xAA] and ref.miso_expected == [0x12, 0x34]
    assert [t["edges"] for t in ref.transactions] == [16, 16]
    ref = SpiSlaveRef(CLK_HZ, SCK_HZ, [0], [0x12, 0x34]); drive(ref, a + a[3:])
    assert len(ref.violations) == 1 and "no mode" in ref.violations[0]
    ref = SpiSlaveRef(CLK_HZ, SCK_HZ, [0, 0], [0x12, 0x34]); drive(ref, a + b)   # mode 3 traffic judged as mode 0
    assert ref.violations and "CPOL" in ref.violations[0]


def test_spi_ref_ignores_everything_before_cs_n_is_first_high():
    uo, _ = perfect_master(0, [0x55], P)
    junk = [0x02, 0x06, 0x00, 0x04, 0x02, 0x00]              # SCK/MOSI toggling with CS_n low (still in reset)
    ref = SpiSlaveRef(CLK_HZ, SCK_HZ, 0, [0x12]); drive(ref, junk + uo)
    assert ref.violations == [] and ref.mosi_bytes == [0x55] and len(ref.transactions) == 1


def one_violation(ref, uo):
    drive(ref, uo)
    assert len(ref.violations) == 1, ref.violations
    return ref.violations[0]

def test_spi_ref_rejects_a_late_edge():
    uo, _ = perfect_master(0, [0x83, 0x1C], P, late=5)
    v = one_violation(SpiSlaveRef(CLK_HZ, SCK_HZ, 0, [0xC1, 0x9A]), uo)
    edge5 = perfect_master(0, [0x83, 0x1C], P)[1][2] + H + 3     # edge 5 = trailing edge of bit 2, 3 late
    assert v.startswith("cycle %d:" % edge5) and "interval %d" % (H + 3) in v, v

def test_spi_ref_rejects_mosi_changed_just_before_a_sampling_edge():
    uo, sampling = perfect_master(0, [0x83, 0x1C], P, mosi_glitch=3)
    v = one_violation(SpiSlaveRef(CLK_HZ, SCK_HZ, 0, [0xC1, 0x9A]), uo)
    assert v.startswith("cycle %d:" % sampling[3]) and "MOSI changed 2 cycles before" in v, v

def test_spi_ref_rejects_sck_active_while_cs_n_is_high():
    uo, _ = perfect_master(0, [0x83, 0x1C], P, sck_pulse=True)
    v = one_violation(SpiSlaveRef(CLK_HZ, SCK_HZ, 0, [0xC1, 0x9A]), uo)
    second = 3 + 4 + H + 5                                     # the pulse's falling edge
    assert v.startswith("cycle %d:" % second) and "while CS_n was high" in v, v

def test_spi_ref_rejects_lead_lag_partial_byte_and_idle_level():
    """Added beyond the plan: the remaining structural rules each fire on a hand-made trace."""
    def mk(cs_sck):                                            # [(cycles, cs_n, sck)] -> uo list
        return [(cs << 3) | (s << 1) for n, cs, s in cs_sck for _ in range(n)]
    lead = mk([(5, 1, 0), (10, 0, 0)] + [(H, 0, i & 1) for i in range(1, 17)] + [(H, 0, 0), (5, 1, 0)])
    v = one_violation(SpiSlaveRef(CLK_HZ, SCK_HZ, 0, [0]), lead); assert "lead" in v, v
    lag = mk([(5, 1, 0)] + [(H, 0, i & 1) for i in range(16)] + [(5, 0, 0), (5, 1, 0)])
    v = one_violation(SpiSlaveRef(CLK_HZ, SCK_HZ, 0, [0]), lag); assert "lag" in v, v
    part = mk([(5, 1, 0)] + [(H, 0, i & 1) for i in range(15)] + [(H, 0, 0), (5, 1, 0)])
    v = one_violation(SpiSlaveRef(CLK_HZ, SCK_HZ, 0, [0]), part); assert "multiple of 16" in v, v
    idle = mk([(5, 1, 1)] + [(H, 0, 1 - (i & 1)) for i in range(17)] + [(H, 0, 1), (5, 1, 1)])
    ref = SpiSlaveRef(CLK_HZ, SCK_HZ, 0, [0]); drive(ref, idle)    # SCK high all along: wrong at both ends
    assert len(ref.violations) == 2 and "CS_n's fall" in ref.violations[0] and "CS_n's rise" in ref.violations[1], ref.violations
    gap = mk([(5, 1, 0)] + [(H, 0, i & 1) for i in range(16)] + [(2, 0, 0)] + [(H, 0, i & 1) for i in range(1, 17)] + [(H, 0, 0), (5, 1, 0)])
    v = one_violation(SpiSlaveRef(CLK_HZ, SCK_HZ, 0, [0, 0]), gap); assert "between bytes" in v, v


# ---- the firmware on the oracle -------------------------------------------------------------

def run_case(name, text=None):
    c = CASES[name]; at = c["at"]
    words, equs = load("spi_master.s", text)
    ref = model_for(c)
    pushes = run_model(words, equs["PRESCALE"], ref, cycle_budget(c), host_words=host_words(c),
                       host_at=(lambda i: at[i]) if at else None)
    return ref, pushes

@pytest.mark.parametrize("name", list(CASES))
def test_spi_master_firmware_matches_reference(name):
    ref, pushes = run_case(name)
    errors = case_errors(CASES[name], ref, pushes); assert errors == [], errors

@pytest.mark.parametrize("name", ["mode0", "mode1", "mode2", "mode3"])
def test_spi_master_edges_are_exactly_half_a_period_apart(name):
    """Every edge-to-edge interval within a byte is H: the deadline-driven loop leaves no jitter."""
    ref, _ = run_case(name)
    for edges in ref.edge_cycles:
        for n in range(1, len(edges)):
            if n % 16: assert edges[n] - edges[n - 1] == H, (n, edges)

def test_spi_master_sentinel_mutant_is_rejected():
    src = (FIRMWARE / "spi_master.s").read_text(); assert MUTANT_HALF[0] in src
    ref, _ = run_case("mode0", src.replace(*MUTANT_HALF, 1))
    assert ref.violations, "the reference accepted an 8 % slow SCK (HALF 27)"
