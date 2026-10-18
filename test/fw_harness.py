"""Shared cocotb harness for the protocol-firmware suites: the full chip (test/tb.v) through its
Tiny Tapeout pins. The host SPI port and the protocol inputs share ui_in, so PinBus owns that
register and merges the two writers; the model loop runs one reference-model step per falling
clock edge and records the core->host pushes from the core's push strobe (RTL only); drain()
keeps reading words back through POP_FIFO so the 4-entry FIFO never drops a push and every test
covers the real host path."""
import os
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, Lock
from tools.asm import assemble, constants
from tools.host import (SpiMaster, encode_write_imem, encode_write_ctrl, encode_write_prescale,
                        CMD_PUSH_FIFO, CMD_POP_FIFO, CMD_READ_STATUS)

FIRMWARE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firmware")
HOST_IDLE = 0x40                       # CS_n high, SCK/MOSI low, RUN low

class PinBus:
    def __init__(self, dut): self.dut, self.host, self.proto = dut, HOST_IDLE, 0x0F
    def apply(self): self.dut.ui_in.value = (self.host & 0x70) | (self.proto & 0x0F)

class HostPort(SpiMaster):
    """SpiMaster that writes the three host lines through the PinBus (half period 200 ns: SCK at
    clk/20, within the port's clk/16 limit), leaving ui[3:0] to the model loop. Every transfer
    holds a lock, so coroutines sharing the port (host_push alongside drain) never interleave
    their bit sequences on ui_in."""
    def __init__(self, bus): self.bus = bus; self.lock = Lock(); super().__init__(bus.dut, half_period_ns=200)
    def _drive(self, sck, mosi, cs_n): self.bus.host = (sck << 4) | (mosi << 5) | (cs_n << 6); self.bus.apply()
    async def xfer(self, tx):
        async with self.lock: return await super().xfer(tx)

def firmware_text(name):
    with open(os.path.join(FIRMWARE, name)) as f: return f.read()

async def boot(dut, fw_name, fw_text=None):
    """Clock, reset, PRESCALE from the firmware's own .equ, load over WRITE_IMEM, WRITE_CTRL run."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    text = fw_text if fw_text is not None else firmware_text(fw_name)
    words, prescale = assemble(text), constants(text)["PRESCALE"]
    bus = PinBus(dut); dut.ena.value = 1; dut.uio_in.value = 0xFF; bus.apply()
    dut.rst_n.value = 0; await ClockCycles(dut.clk, 3); dut.rst_n.value = 1; await ClockCycles(dut.clk, 2)
    host = HostPort(bus)
    await host.xfer(encode_write_prescale(prescale))
    await host.xfer(encode_write_imem(0, words))
    await host.xfer(encode_write_ctrl(run=True))
    return bus, host, words

async def run_model(dut, bus, model, cycles):
    core = dut.user_project.u_core; pushes = []
    for k in range(cycles):
        await FallingEdge(dut.clk)
        if int(core.c2h_push.value): pushes.append((k, int(core.c2h_data.value)))
        ui, uio_in = model.step(int(dut.uo_out.value) & 0x7F, int(dut.uio_out.value), int(dut.uio_oe.value))
        bus.proto = ui; bus.apply(); dut.uio_in.value = uio_in
    return pushes

async def status(host):
    return (await host.xfer(bytes([CMD_READ_STATUS, 0, 0, 0, 0])))[1]

async def host_push(host, word):
    while (await status(host)) & 0x10: pass            # h2c full: poll
    await host.xfer(bytes([CMD_PUSH_FIFO, (word >> 8) & 0xFF, word & 0xFF]))

async def drain(host, out, stop):
    """Pop every core->host word into `out` until stop() is true (and the FIFO is empty)."""
    while True:
        st = await status(host)
        if not st & 0x08:
            r = await host.xfer(bytes([CMD_POP_FIFO, 0, 0])); out.append((r[1] << 8) | r[2])
        elif stop(): return
