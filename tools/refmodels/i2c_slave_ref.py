"""I2C slave and master checker for standard mode, written from the bus definition (UM10204):
START = SDA falls while SCL high, STOP = SDA rises while SCL high, data sampled on SCL's rising
edge and stable while SCL is high, nine bits per byte (eight data MSB first, then ACK = SDA low).
The model computes the wired-AND bus from the master's pull-downs (uio_oe & ~uio_out, bits 0 = SDA
and 1 = SCL) and its own, and returns the bus levels as the chip's uio_in (other bits 1).

Standard-mode limits checked on the bus, in cycles from clk_hz (never from the firmware):
  period (rise to rise) >= 10.0 us; tLOW >= 4.7 us; tHIGH >= 4.0 us; tSU;STA >= 4.7 us (SDA and SCL
  both high before SDA falls); tHD;STA >= 4.0 us (SDA low before SCL falls); tSU;DAT >= 250 ns;
  tHD;DAT <= 3.45 us (except the master's first SDA change after an ACK bit: between commands it
  holds SCL low for as long as its host takes, which is master-side stretching, and while the slave
  stretches; UM10204 applies the maximum only to an unstretched low period); tSU;STO >= 4.0 us;
  tBUF >= 4.7 us; any other SDA change while SCL is high is a violation. Open drain: a master
  line driven high (uio_oe & uio_out, bits 0-1) is a violation.
Slave: ACKs its own address (either direction), NACKs others; stores written bytes; serves
read_data on reads and stops after the master's NACK; nack_data_after = n NACKs the n-th written
data byte; stretch_after_byte = (k, cycles) holds SCL low for `cycles` after the ACK bit of byte k
(0 = the address byte) -- longer than the master's 65,535-tick timeout is the timeout case; the
slave then lets go and keeps listening for a START.
Sampling-instant check (the I2C counterpart of the SPI model's MISO window): every bit the slave
transmits (read data, and its ACK or NACK of a byte written to it) is the complement from the
cycle SCL falls (T_SLAVE = 0, a legal hold time of 0) and the real level only from tVD;DAT =
3.45 us after the fall (172 cycles at 50 MHz, the latest UM10204 allows), or, while the slave
stretches, only from tSU;DAT before it lets SCL go if that is later (UM10204 Table 10: with SCL
stretched the data must be valid by the set-up time before the release). The real level then stays
until the next fall. So a master that samples SDA after the fall, or in the low phase before the
real level is due, reads the wrong bit; one that samples while SCL is high reads the right one. The
slave's own tSU;DAT stays legal: 172 cycles into a low period of at least tLOW = 235 leaves 63 (86
against the firmware's measured 258), and the stretched case leaves exactly tSU;DAT (13).

Conventions this implementation fixes (all from the bus definition, none from a firmware):
  - cycles are counted from the model's first step; a level change "at cycle k" is the first step
    that sees the new bus level. A minimum is met when the measured interval is >= the limit
    rounded up to whole cycles (period 500, tLOW 235, tHIGH 200, tSU;STA 235, tHD;STA 200, tSU;DAT
    13, tSU;STO 200, tBUF 235 at 50 MHz); the tHD;DAT maximum is rounded down (172). No further
    tolerance: the master's fixed latencies (pin writes visible the cycle after the instruction,
    inputs read two cycles late) are its own business and must fit inside the table.
  - the bus is idle-high before the first step (both lines released, as the chip resets).
    Intervals whose start was never seen (e.g. tSU;STA of the first START, SCL high since reset)
    are not checked.
  - tSU;STA / tBUF: at a START the bus-free time since the last STOP is checked against tBUF; any
    other START (the first one, or a repeated START) is checked against tSU;STA, measured from the
    later of the last SCL rise and the last SDA rise (the time both lines have been high).
  - tSU;DAT: an SDA change on the bus while SCL is low (from the cycle SCL falls) must precede the
    next SCL rise by tSU;DAT; a change in the very cycle SCL rises has a setup of 0.
  - tHD;DAT: judged on the master's own SDA pull-down (the model sees it apart from the slave's),
    from the last SCL fall to every change while SCL is low, including the first bit after a
    START. Exempt: the master's first change after an ACK bit (a command boundary: the next byte's
    first bit, a STOP's SDA low or a repeated START's SDA release), and any change while the slave
    holds SCL low (e.g. the master's abort releasing SDA during a long stretch).
  - START and STOP are recognised only between bytes (no bit of the current byte clocked yet; the
    SCL pulse they occur in is not a data bit) or before the first START. An SDA change while SCL
    is high in bits 1-9 of a byte is a violation and is otherwise ignored (the bit keeps the level
    sampled at the rise).
  - nack_data_after = n: data bytes written to this slave are counted over the model's lifetime;
    the n-th and every later one is NACKed (nack_data_after = 1 NACKs every data byte). NACKed
    bytes are still recorded in `written` (bytes received) and in `events` (acked False).
  - stretch_after_byte = (k, cycles): byte k of a transaction, counted from its START (0 = the
    address byte); it fires once, the first time that byte's ACK bit ends. The slave pulls SCL low
    in the cycle SCL falls at the end of that ACK bit and releases it `cycles` cycles later.
    measured["scl_release_lag"] lists (release cycle, cycles until SCL rose on the bus) for every
    release (None if SCL never rose before finish()), so a test can check that the master had let
    go of SCL by then (after its own release, or after aborting on a timeout).
  - the slave's SDA changes happen T_SLAVE = 0 cycles after SCL falls (in the fall's own cycle):
    the ACK or a data byte's NACK after the eighth bit (complement first, see the sampling-instant
    check), its release after the ninth; on a read, each data bit (the first one after the address
    ACK or the master's ACK of the previous byte; complement first) and the release for the
    master's ACK after the eighth. Another device's address gets no response (SDA left released,
    no complement). read_data beyond its end is served as 0xFF (SDA released). After the
    master's NACK of a read byte, or a NACK of the address, the slave ignores the bus until the
    next START. A START or STOP cancels the slave's pending SDA changes.
  - open drain: the violation "SDA/SCL driven high (open-drain contract)" is recorded once in
    each cycle a master line becomes driven high (uio_oe & uio_out); the bus still treats such a
    line as released (the wired-AND takes only pull-downs).
  - finish(stop_expected=True), called once after the last step, records a violation for a byte
    half-received and, unless stop_expected is False, for a transaction still open (no STOP).
  - events: ("START", k), ("STOP", k), ("BYTE", k, value, acked, "W"|"R") at the SCL fall that
    ends the byte's ACK bit, for every byte while the slave is addressed (the address byte itself
    is a "W" byte, acked if it was ours). measured[name] lists (k, cycles) for every interval
    checked, for reports."""
import math
from fractions import Fraction

T_SLAVE = 0                       # the slave's SDA changes, cycles after SCL falls (tHD;DAT 0 is legal)

MIN_NS = {"period": 10_000, "tLOW": 4_700, "tHIGH": 4_000, "tSU;STA": 4_700, "tHD;STA": 4_000,
          "tSU;DAT": 250, "tSU;STO": 4_000, "tBUF": 4_700}
MAX_NS = {"tHD;DAT": 3_450}
T_VD_NS = 3_450                   # tVD;DAT: a transmitter's data is valid at the latest this long after SCL falls


class I2cSlaveRef:
    def __init__(self, clk_hz, address, read_data=(), nack_data_after=None, stretch_after_byte=None):
        self.clk_hz, self.address = clk_hz, address
        self.read_data, self.nack_data_after = list(read_data), nack_data_after
        self.stretch_after_byte = stretch_after_byte
        cyc = lambda ns: Fraction(ns) * clk_hz / 10**9
        self.min = {n: math.ceil(cyc(ns)) for n, ns in MIN_NS.items()}
        self.max = {n: math.floor(cyc(ns)) for n, ns in MAX_NS.items()}
        self.t_vd_max = math.floor(cyc(T_VD_NS))   # 172 at 50 MHz
        self.k = 0
        self.violations, self.written, self.events = [], [], []
        self.measured = {n: [] for n in list(MIN_NS) + list(MAX_NS) + ["scl_release_lag"]}
        self.scl = self.sda = 1           # bus levels in the previous step (idle high)
        self.m_sda = 0                    # the master's SDA pull-down in the previous step
        self.s_sda = self.s_scl = 0       # the slave's pull-downs
        self.actions = []                 # [(cycle, line, pull)] pending slave changes
        self.rise = self.fall = None      # last SCL rise / fall
        self.sda_rise = self.sda_change = None
        self.start_at = None              # START seen in the current SCL-high pulse
        self.cond = False                 # START or STOP in the current SCL-high pulse
        self.last_cond, self.stop_at = None, None
        self.state = "idle"               # idle, addr, write, read, ignore
        self.bits = 0; self.shift = 0; self.sample = 1; self.value = 0
        self.byte_index = 0; self.n_data = 0; self.n_read = 0
        self.ack_given = False; self.stretch_done = False
        self.stretch_release = None       # cycle the slave lets SCL go (while it stretches)
        self.released_at = None           # the slave let SCL go here and SCL has not risen since
        self.after_ack = False            # the master's next SDA change is its first after an ACK bit
        self.m_high = 0                   # master lines driven high in the previous step

    # ---- helpers ----------------------------------------------------------------------------
    def _v(self, what):
        self.violations.append("cycle %d: %s" % (self.k, what))

    def _min(self, name, interval):
        self.measured[name].append((self.k, interval))
        if interval < self.min[name]:
            self._v("%s %d cycles (>= %d)" % (name, interval, self.min[name]))

    def _sda_at(self, cycle, pull):
        self.actions.append((cycle, "sda", pull))

    def _read_byte(self):
        return self.read_data[self.n_read] if self.n_read < len(self.read_data) else 0xFF

    def _apply_due(self, k):
        """Apply the slave's pending changes due by cycle k (pull-downs: 1 = pull low)."""
        due = [a for a in self.actions if a[0] <= k]
        self.actions = [a for a in self.actions if a[0] > k]
        for _, line, pull in due:
            if line == "sda": self.s_sda = pull
            else:
                self.s_scl = pull
                if not pull: self.stretch_release, self.released_at = None, k
        return bool(due)

    def _drive(self, k, pull):
        """The slave transmits a bit (a read data bit, or its ACK/NACK of a byte written to it) for
        the SCL pulse after the fall at k: the complement from k + T_SLAVE, the real level from
        k + t_vd_max (UM10204 tVD;DAT, the latest a transmitter may set its data), or, while the
        slave stretches, from tSU;DAT before it lets SCL go if that is later (UM10204 Table 10:
        with SCL stretched the data need only be valid by the set-up time before the release)."""
        real = k + self.t_vd_max
        if self.stretch_release is not None:
            real = max(real, self.stretch_release - self.min["tSU;DAT"])
        self._sda_at(k + T_SLAVE, 1 - pull)
        self._sda_at(real, pull)

    def _drive_read_bit(self, i):         # i = 7 (MSB) .. 0, for the pulse after this fall
        self._drive(self.k, 1 - ((self._read_byte() >> i) & 1))

    # ---- one cycle --------------------------------------------------------------------------
    def step(self, uo, uio_out, uio_oe):
        k = self.k
        self._apply_due(k)
        high = uio_oe & uio_out & 0x03
        if high and not self.m_high:
            self._v("SDA/SCL driven high (open-drain contract)")
        self.m_high = high
        md = uio_oe & ~uio_out & 0x03
        m_sda, m_scl = md & 1, (md >> 1) & 1
        sda = 0 if (m_sda or self.s_sda) else 1
        scl = 0 if (m_scl or self.s_scl) else 1

        if sda != self.sda:
            if scl and self.scl:                               # SDA changed while SCL high
                if self.state != "idle" and self.bits != 0:
                    self._v("SDA %s while SCL high in bit %d of a byte" % ("fell" if not sda else "rose", self.bits + 1))
                elif not sda:
                    self._start(k)
                else:
                    self._stop(k)
            self.sda_change = k
            if sda: self.sda_rise = k
        self.sda = sda

        if scl and not self.scl:                               # SCL rises
            if self.released_at is not None:
                self.measured["scl_release_lag"].append((self.released_at, k - self.released_at))
                self.released_at = None
            if self.fall is not None: self._min("tLOW", k - self.fall)
            if self.rise is not None: self._min("period", k - self.rise)
            if self.sda_change is not None and self.fall is not None and self.sda_change >= self.fall:
                self._min("tSU;DAT", k - self.sda_change)
            self.rise, self.sample, self.cond, self.start_at = k, sda, False, None
        elif not scl and self.scl:                             # SCL falls
            if self.rise is not None: self._min("tHIGH", k - self.rise)
            if self.start_at is not None: self._min("tHD;STA", k - self.start_at)
            self.fall = k
            if not self.cond and self.state != "idle":
                self._commit(k)
            self.cond, self.start_at = False, None
        self.scl = scl
        if self._apply_due(k):                                 # changes the fall just scheduled (T_SLAVE = 0):
            sda = 0 if (m_sda or self.s_sda) else 1            # on the bus in the fall's own cycle, SCL low
            if sda != self.sda:
                self.sda_change = k
                if sda: self.sda_rise = k
            self.sda = sda

        if m_sda != self.m_sda and not scl and self.state != "idle" and self.s_scl:
            pass                                               # SCL stretched by the slave: exempt
        elif m_sda != self.m_sda and not scl and self.state != "idle" and self.bits == 0 and self.after_ack:
            self.after_ack = False                             # the first change after an ACK: exempt
        elif m_sda != self.m_sda and not scl and self.state != "idle" and self.bits <= 8:
            hold = k - self.fall
            self.measured["tHD;DAT"].append((k, hold))
            if hold > self.max["tHD;DAT"]:
                self._v("tHD;DAT %d cycles (<= %d within a byte)" % (hold, self.max["tHD;DAT"]))
        self.m_sda = m_sda

        self.k += 1
        return (0x0F, 0xFC | (scl << 1) | sda)

    def finish(self, stop_expected=True):
        """End of the run: a byte half-received is a violation, and so is a transaction still open
        (a START with no STOP) when the caller expected the master to have sent its STOP."""
        if self.state != "idle" and self.bits != 0:
            self._v("run ended in bit %d of a byte" % (self.bits + 1))
        if self.released_at is not None:
            self.measured["scl_release_lag"].append((self.released_at, None))
        if stop_expected and self.state != "idle":
            starts = [e[1] for e in self.events if e[0] == "START"]
            self._v("run ended with the transaction from the START at cycle %d still open (no STOP)" % starts[-1])
        return self.violations

    # ---- bus conditions and bits ------------------------------------------------------------
    def _start(self, k):
        if self.last_cond == "STOP":
            self._min("tBUF", k - self.stop_at)
        else:
            since = [x for x in (self.rise, self.sda_rise) if x is not None]
            if since: self._min("tSU;STA", k - max(since))
        self.events.append(("START", k))
        self.last_cond, self.start_at, self.cond = "START", k, True
        self.state, self.bits, self.shift, self.byte_index = "addr", 0, 0, 0
        self.after_ack = False
        self.actions = [a for a in self.actions if a[1] != "sda"]; self.s_sda = 0

    def _stop(self, k):
        if self.rise is not None: self._min("tSU;STO", k - self.rise)
        self.events.append(("STOP", k))
        self.last_cond, self.stop_at, self.cond = "STOP", k, True
        self.state, self.bits, self.shift = "idle", 0, 0
        self.actions = [a for a in self.actions if a[1] != "sda"]; self.s_sda = 0

    def _commit(self, k):
        """SCL fell at the end of a data/ACK pulse: the bit sampled at its rise is clocked."""
        self.bits += 1
        b = self.sample
        self.after_ack = self.bits == 9
        if self.bits <= 8:
            self.shift = ((self.shift << 1) | b) & 0xFF
        st = self.state
        if self.bits < 8:
            if st == "read": self._drive_read_bit(7 - self.bits)
        elif self.bits == 8:
            self.value = self.shift
            if st == "addr":
                self.ack_given = (self.value >> 1) == self.address
            elif st == "write":
                self.n_data += 1
                self.ack_given = not (self.nack_data_after is not None and self.n_data >= self.nack_data_after)
            else:
                self.ack_given = False
            if st in ("addr", "write") and self.ack_given:
                self._drive(k, 1)                              # ACK
            elif st == "write":
                self._drive(k, 0)                              # NACK of a data byte written to us
            else:
                self._sda_at(k + T_SLAVE, 0)                   # release (another device's address, or the master's ACK slot)
        else:                                                  # the ninth (ACK) bit
            acked = b == 0
            if st in ("addr", "write", "read"):
                self.events.append(("BYTE", k, self.value, acked, "R" if st == "read" else "W"))
            if st == "write": self.written.append(self.value)
            self._sda_at(k + T_SLAVE, 0)                       # release the ACK
            if st == "addr":
                self.state = ("read" if self.value & 1 else "write") if self.ack_given else "ignore"
            elif st == "read":
                self.n_read += 1
                self.state = "read" if acked else "ignore"
            sab = self.stretch_after_byte
            if sab is not None and not self.stretch_done and self.byte_index == sab[0] and st != "ignore":
                self.stretch_done = True; self.s_scl = 1
                self.stretch_release = k + sab[1]
                self.actions.append((k + sab[1], "scl", 0))
            if self.state == "read":
                self._drive_read_bit(7)
            self.byte_index += 1; self.bits = 0; self.shift = 0
