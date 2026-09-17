"""Host-side encoding of the SPI loader protocol, plus a cocotb SPI master for tests."""
CMD_WRITE_IMEM, CMD_WRITE_CTRL, CMD_READ_STATUS, CMD_PUSH_FIFO, CMD_POP_FIFO, CMD_READ_GPIO, CMD_WRITE_PRESCALE = 1, 2, 3, 4, 5, 6, 7

def encode_write_imem(addr, words):
    out = bytes([CMD_WRITE_IMEM, (addr >> 8) & 3, addr & 0xFF])
    for w in words: out += bytes([(w >> 8) & 0xFF, w & 0xFF])
    return out

def encode_write_ctrl(run, reset=False):
    return bytes([CMD_WRITE_CTRL, (1 if run else 0) | (2 if reset else 0)])

def encode_write_prescale(v):
    return bytes([CMD_WRITE_PRESCALE, v & 0xFF])

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
