"""8N1 UART line stimulus and receiver checker, written from the frame definition (idle high; start
bit low; 8 data bits LSB first; stop bit high; every bit clk_hz / baud cycles long).

Tolerances (spec, not firmware): a frame's result must be pushed within
[stop sample - bit/8, stop sample + bit/8 + PUSH_SLACK] cycles, where the stop sample is the start
edge + 9.5 bits at the nominal baud rate; probe frames carry each data bit's value only within
+-bit/8 of its nominal sample instant and the complement elsewhere.

Positions are kept in floating point (cycles since the model's first step) and converted with
int() at each boundary, so a 434.03-cycle bit never accumulates rounding drift. The model is driven
through step(uo, uio_out, uio_oe) -> (ui, uio_in): it ignores the chip's outputs and drives the line
on ui[0] (ui[3:1] and uio idle high). `violations` stays empty (a receiver drives nothing the line
could check); check() compares the pushed words with the expectation."""
PUSH_SLACK = 32          # cycles allowed from the ideal stop sample (+bit/8) to the PUSH


class Frame:
    def __init__(self, byte, baud_error=0.0, probe=False, stop_low=False, glitch=None, gap=None):
        # glitch: a low pulse of that many cycles instead of a frame (no word expected; byte is
        # ignored); gap: idle cycles before the frame (default 2 bits); probe and baud_error are
        # not combined.
        if probe and baud_error:
            raise ValueError("probe frames are at the nominal baud rate (baud_error must be 0)")
        if not 0 <= byte <= 0xFF:
            raise ValueError("byte must be 0..255")
        self.byte, self.baud_error, self.probe, self.stop_low = byte, baud_error, probe, stop_low
        self.glitch, self.gap = glitch, gap


class UartRxRef:
    def __init__(self, clk_hz, baud):
        self.clk_hz, self.baud = clk_hz, baud
        self.cpb = clk_hz / baud                       # nominal cycles per bit (float)
        self.tol = int(self.cpb / 8)                   # +-12.5 % of a bit
        self.line, self.expected, self.violations, self.k = [], [], [], 0

    def schedule(self, frames, lead_in=200):
        """Build the per-cycle line (self.line, list of 0/1) and self.expected: list of
        (word, first_ok_cycle, last_ok_cycle). word = byte | (0x100 if stop_low)."""
        line, expected = [], []
        pos = float(lead_in)

        def fill(upto, level):
            n = int(upto) - len(line)
            if n > 0: line.extend([level] * n)

        fill(pos, 1)
        for f in frames:
            pos += 2 * self.cpb if f.gap is None else f.gap
            fill(pos, 1)                                               # idle gap
            if f.glitch is not None:
                pos += f.glitch; fill(pos, 0); continue                # a low pulse, no frame
            bit = self.clk_hz / (self.baud * (1.0 + f.baud_error))     # this frame's own bit time
            edge = pos
            bits = [0] + [(f.byte >> i) & 1 for i in range(8)] + [0 if f.stop_low else 1]
            for i, b in enumerate(bits):
                start = len(line); fill(edge + (i + 1) * bit, b)
                if f.probe and 1 <= i <= 8:                            # value only near the nominal sample
                    centre = int(edge + (i + 0.5) * self.cpb)
                    for k in range(start, len(line)):
                        if abs(k - centre) > self.tol: line[k] = 1 - b
            pos = edge + 10 * bit
            stop = int(edge + 9.5 * self.cpb)                          # nominal-rate stop sample
            expected.append((f.byte | (0x100 if f.stop_low else 0), stop - self.tol, stop + self.tol + PUSH_SLACK))
        self.line, self.expected, self.k = line, expected, 0

    @property
    def cycles(self):
        """len(self.line) + 4 bits of trailing idle"""
        return len(self.line) + int(4 * self.cpb)

    def step(self, uo, uio_out, uio_oe):
        level = self.line[self.k] if self.k < len(self.line) else 1
        self.k += 1
        return (0x0E | level, 0xFF)

    def check(self, pushes):
        """Return a list of error strings (empty when `pushes`, a list of (cycle, word), equals the
        expectation: same count, same words in order, each cycle inside its window)."""
        errors = list(self.violations)
        if len(pushes) != len(self.expected):
            errors.append("expected %d pushes %s, got %d: %s" % (
                len(self.expected), ["0x%03X" % w for w, _, _ in self.expected], len(pushes),
                [(c, "0x%03X" % w) for c, w in pushes]))
        for n, ((cycle, word), (want, lo, hi)) in enumerate(zip(pushes, self.expected)):
            if word != want:
                errors.append("cycle %d: frame %d pushed 0x%03X, expected 0x%03X" % (cycle, n, word, want))
            elif not lo <= cycle <= hi:
                errors.append("cycle %d: frame %d (0x%03X) pushed outside [%d, %d]" % (cycle, n, word, lo, hi))
        return errors
