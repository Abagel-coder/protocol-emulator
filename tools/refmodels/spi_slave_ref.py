"""SPI slave and master checker, written from the mode definitions (CPOL = idle SCK level; the
leading edge is the edge away from idle; CPHA=0 samples on the leading edge and shifts on the
trailing one with the first bit set up before the first edge; CPHA=1 shifts on the leading edge and
samples on the trailing one). MSB first, 8 bits per byte, CS_n low for a whole transaction.

Pins: SCK uo[1], MOSI uo[2], CS_n uo[3]; MISO is returned on ui[1].
Tolerances (from the nominal period P = clk_hz / sck_hz, H = P // 2; never from the firmware):
  - while CS_n is high (from the first time it is seen high; uo resets low) SCK changes level at most
    once -- the switch to the next transaction's CPOL -- and it must equal the transaction's CPOL at
    CS_n's fall, between the bytes of the transaction and at CS_n's rise;
  - first edge >= H - 2 cycles after CS_n falls and in the leading direction; last edge >= H - 2 before CS_n rises;
  - edge-to-edge within a byte: H +- 1 cycles; between bytes >= H - 1 with SCK idle;
  - MOSI unchanged from P // 4 cycles before each sampling edge to P // 4 after it;
  - a transaction holds a multiple of 16 edges.
MISO: each bit valid t_co cycles after its shifting edge (CPHA=0: the first bit t_co after CS_n
falls) and held to the next shifting edge; with miso_window = w the bit is valid only within +-w
cycles of the predicted sampling edge (previous edge + H) and the complement elsewhere -- the first
bit of a CPHA=0 transaction is driven plainly.

Conventions this implementation fixes (all from the protocol, none from a firmware):
  - cycles are counted from the model's first step; an edge "at cycle k" is the first step that
    sees the new SCK level. The SCK level "at CS_n's fall" is the level in the last cycle CS_n was
    high, and the level "at CS_n's rise" the level in the last cycle CS_n was low; an SCK change in
    the cycle CS_n falls is the transaction's first edge (lead 0), one in the cycle CS_n rises is a
    change while CS_n is high. With SCK at CPOL when CS_n falls the first edge is necessarily the
    leading one, so the direction rule is enforced by the CS_n-fall level check.
  - `mode` is an int (every transaction) or a list (transaction j is judged against mode[j]; a
    transaction beyond the list's end is a violation and is judged against the list's last mode).
  - MISO window and CPHA=0: the first bit of EVERY byte of a CPHA=0 transaction is driven plainly,
    not only the transaction's first bit. Why: that bit's sampling edge is the byte's first edge,
    which follows a stretch of idle SCK -- after CS_n's fall for the first byte, after a
    between-byte gap for the others -- whose length the master (here, paced by its host) chooses
    and the protocol does not fix. "Previous edge + H" would put the window at the wrong place and
    a correct master that waits for its next byte would read the complement. The bit is still
    checked: it is valid only from t_co after its shifting edge (CS_n's fall, or the previous
    byte's last trailing edge) to the next shifting edge. Every other bit, and every bit of a CPHA=1
    byte (whose first edge is the shifting edge, so its sampling edge is predictable), is windowed.
  - before a bit is valid MISO holds its previous level; while CS_n is high and before a CPHA=1
    transaction's first shifting edge it is high (idle). A byte whose bits run out of miso_bytes is
    driven as 0xFF.
  - mosi_bytes / miso_expected gain a byte when its eighth sampling edge has been seen;
    transactions is a list of {"cs_fall": k, "cs_rise": k or None, "edges": n}; edge_cycles holds
    each transaction's edge cycles (for reports)."""


class SpiSlaveRef:
    def __init__(self, clk_hz, sck_hz, mode, miso_bytes, miso_window=None, t_co=5):
        self.clk_hz, self.sck_hz, self.mode = clk_hz, sck_hz, mode
        self.miso_bytes, self.miso_window, self.t_co = list(miso_bytes), miso_window, t_co
        self.P = clk_hz // sck_hz
        self.H = self.P // 2
        self.k = 0
        self.violations, self.mosi_bytes, self.transactions, self.miso_expected = [], [], [], []
        self.edge_cycles = []
        self.seen_high = False
        self.prev = None                 # (cs_n, sck, mosi) of the previous step
        self.idle_changes = 0            # SCK level changes in the current CS_n-high period
        self.last_mosi_change = None
        self.holds = []                  # sampling-edge cycles whose MOSI hold window is still open
        self.tx = None                   # the open transaction's state (dict), None while CS_n is high
        self.miso = 1                    # MISO level returned this cycle
        self.drive = None                # (bit, valid_from, predicted sampling edge or None)

    # ---- helpers ----------------------------------------------------------------------------
    def _v(self, what):
        self.violations.append("cycle %d: %s" % (self.k, what))

    def _mode_of(self, j):
        if isinstance(self.mode, int):
            return self.mode
        if j >= len(self.mode):
            self._v("transaction %d has no mode (only %d given)" % (j, len(self.mode)))
            return self.mode[-1]
        return self.mode[j]

    def _miso_byte(self):
        n = len(self.miso_expected)
        return self.miso_bytes[n] if n < len(self.miso_bytes) else 0xFF

    def _shift_out(self, bit_index, valid_from, predicted):
        """Start driving bit `bit_index` (7 = MSB) of the next MISO byte."""
        b = (self._miso_byte() >> bit_index) & 1
        self.drive = (b, valid_from, predicted)

    # ---- one cycle --------------------------------------------------------------------------
    def step(self, uo, uio_out, uio_oe):
        k = self.k
        sck, mosi, cs_n = (uo >> 1) & 1, (uo >> 2) & 1, (uo >> 3) & 1
        prev = self.prev
        self.prev = (cs_n, sck, mosi)
        if prev is not None and mosi != prev[2]:
            self.last_mosi_change = k
            for e in self.holds:
                if k <= e + self.P // 4:
                    self._v("MOSI changed %d cycles after the sampling edge at %d (hold %d)" % (k - e, e, self.P // 4))
            self.holds = []
        self.holds = [e for e in self.holds if k < e + self.P // 4]

        if not self.seen_high:
            if cs_n:
                self.seen_high, self.idle_changes = True, 0
            self.k += 1
            return self._out()

        p_cs, p_sck, _ = prev
        sck_changed = sck != p_sck
        if p_cs and not cs_n:                                 # CS_n falls: a transaction starts
            j = len(self.transactions)
            m = self._mode_of(j)
            cpol, cpha = m >> 1, m & 1
            self.tx = {"cpol": cpol, "cpha": cpha, "n": 0, "last": None, "mosi": 0, "bits": 0}
            self.transactions.append({"cs_fall": k, "cs_rise": None, "edges": 0})
            self.edge_cycles.append([])
            if p_sck != cpol:
                self._v("SCK = %d at CS_n's fall, mode %d needs CPOL = %d" % (p_sck, m, cpol))
            if cpha == 0:
                self._shift_out(7, k + self.t_co, None)        # first bit: plain, from CS_n's fall
            else:
                self.drive = None
        elif not p_cs and cs_n:                               # CS_n rises: the transaction ends
            tx = self.tx
            rec = self.transactions[-1]
            rec["cs_rise"] = k
            if p_sck != tx["cpol"]:
                self._v("SCK = %d at CS_n's rise, CPOL = %d" % (p_sck, tx["cpol"]))
            if tx["n"] % 16:
                self._v("transaction ended after %d SCK edges (not a multiple of 16)" % tx["n"])
            if tx["last"] is not None and k - tx["last"] < self.H - 2:
                self._v("CS_n rose %d cycles after the last SCK edge (lag >= %d)" % (k - tx["last"], self.H - 2))
            self.tx, self.drive, self.idle_changes = None, None, 0

        if sck_changed:
            if cs_n:                                          # while CS_n is high
                self.idle_changes += 1
                if self.idle_changes == 2:
                    self._v("SCK changed level twice while CS_n was high")
            else:
                self._edge(k, sck, mosi)

        self.k += 1
        return self._out()

    def _edge(self, k, sck, mosi):
        tx = self.tx
        n, H = tx["n"], self.H
        self.edge_cycles[-1].append(k)
        if n == 0:
            lead = k - self.transactions[-1]["cs_fall"]
            if lead < H - 2:
                self._v("first SCK edge %d cycles after CS_n fell (lead >= %d)" % (lead, H - 2))
        elif n % 16 == 0:
            if k - tx["last"] < H - 1:
                self._v("gap between bytes %d cycles (>= %d)" % (k - tx["last"], H - 1))
        elif abs(k - tx["last"] - H) > 1:
            self._v("SCK edge-to-edge interval %d cycles within a byte (H = %d +- 1)" % (k - tx["last"], H))
        leading = n % 2 == 0
        bit = (n % 16) // 2                                    # 0 = MSB
        sampling = leading == (tx["cpha"] == 0)
        if sampling:
            lim = self.P // 4
            if self.last_mosi_change is not None and self.last_mosi_change > k - lim:
                self._v("MOSI changed %d cycles before the sampling edge (setup %d)" % (k - self.last_mosi_change, lim))
            else:
                self.holds.append(k)
            tx["mosi"] = ((tx["mosi"] << 1) | mosi) & 0xFF
            tx["bits"] += 1
            if tx["bits"] == 8:
                self.mosi_bytes.append(tx["mosi"]); self.miso_expected.append(self._miso_byte())
                tx["bits"], tx["mosi"] = 0, 0
        else:                                                  # shifting edge
            w = self.miso_window is not None
            if tx["cpha"] == 1:                                # leading edge: shift bit `bit`
                self._shift_out(7 - bit, k + self.t_co, k + H if w else None)
            elif bit < 7:                                      # trailing edge: shift the next bit
                self._shift_out(6 - bit, k + self.t_co, k + H if w else None)
            else:                                              # after a byte: next byte's MSB, plain
                self._shift_out(7, k + self.t_co, None)
        tx["n"] = n + 1; tx["last"] = k
        self.transactions[-1]["edges"] = n + 1

    def _out(self):
        k = self.k - 1
        if self.tx is None or self.drive is None:
            self.miso = 1
        else:
            b, valid_from, predicted = self.drive
            if k >= valid_from:
                if predicted is None or abs(k - predicted) <= self.miso_window:
                    self.miso = b
                else:
                    self.miso = 1 - b
        return ((self.miso << 1) | 0x0D, 0xFF)
