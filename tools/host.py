"""Host-side encoding of the SPI loader protocol, plus a cocotb SPI master for tests."""
CMD_WRITE_IMEM, CMD_WRITE_CTRL, CMD_READ_STATUS, CMD_PUSH_FIFO, CMD_POP_FIFO, CMD_READ_GPIO, CMD_WRITE_PRESCALE = 1, 2, 3, 4, 5, 6, 7

def _check(name, value, bits):
    if not isinstance(value, int) or not 0 <= value < (1 << bits):
        raise ValueError("%s must be an integer in 0..%d, got %r" % (name, (1 << bits) - 1, value))
    return value

def encode_write_imem(addr, words):
    """WRITE_IMEM: 10-bit start address, then 16-bit words. Out-of-range values raise
    ValueError rather than being masked (a 17-bit word would otherwise load silently corrupted;
    note the chip's 64-word memory aliases addresses modulo 64, docs/info.md)."""
    _check("addr", addr, 10)
    out = bytes([CMD_WRITE_IMEM, (addr >> 8) & 3, addr & 0xFF])
    for i, w in enumerate(words):
        _check("words[%d]" % i, w, 16)
        out += bytes([(w >> 8) & 0xFF, w & 0xFF])
    return out

def encode_write_ctrl(run, reset=False):
    return bytes([CMD_WRITE_CTRL, (1 if run else 0) | (2 if reset else 0)])

def encode_write_prescale(v):
    """WRITE_PRESCALE: the timebase ticks once every (v + 1) clock cycles; v is 0..255."""
    _check("prescale", v, 8)
    return bytes([CMD_WRITE_PRESCALE, v])

try:
    import cocotb
    from cocotb.triggers import Timer

    class SpiMaster:
        """Mode-0 master on the Tiny Tapeout pins. half_period_ns must be >= 8 core clocks."""
        def __init__(self, dut, half_period_ns=400, other_bits=0x80):
            self.dut, self.half, self.other_bits = dut, half_period_ns, other_bits   # 0x80 = RUN high
            self._drive(sck=0, mosi=0, cs_n=1)

        def _drive(self, sck, mosi, cs_n):
            self.dut.ui_in.value = (self.other_bits & 0x8F) | (sck << 4) | (mosi << 5) | (cs_n << 6)

        async def xfer(self, tx):
            rx = bytearray(); self._drive(0, 0, 0); await Timer(self.half, unit="ns")
            for b in tx:
                r = 0
                for i in range(7, -1, -1):
                    self._drive(0, (b >> i) & 1, 0); await Timer(self.half, unit="ns")
                    self._drive(1, (b >> i) & 1, 0); r = (r << 1) | ((int(self.dut.uo_out.value) >> 7) & 1)
                    await Timer(self.half, unit="ns")
                rx.append(r)
            self._drive(0, 0, 1); await Timer(self.half, unit="ns")
            return bytes(rx)
except ImportError:      # plain-Python use (demo-board script) needs only the encoders
    pass
