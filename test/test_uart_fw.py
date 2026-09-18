import re

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge

from tools.asm import assemble
from tools.host import SpiMaster, encode_write_imem, encode_write_ctrl, encode_write_prescale

FW_PATH = "../firmware/uart_tx.s"
with open(FW_PATH) as _f:
    FW_SRC = _f.read()

# The firmware hardcodes the byte it sends as `LDI R2, 0x55`. To check the firmware's
# deadline arithmetic (not just the one byte it ships with), build variants of the source
# with that immediate replaced, while leaving firmware/uart_tx.s itself sending 0x55.
LDI_R2_RE = re.compile(r"(LDI\s+R2,\s*)0x55")


def _fw_source_for(byte):
    text, n = LDI_R2_RE.subn(r"\g<1>0x%02X" % byte, FW_SRC, count=1)
    assert n == 1, "could not find `LDI R2, 0x55` in %s to parameterise" % FW_PATH
    return text


def _first_fall(v):
    return next(i for i in range(1, len(v)) if v[i - 1] == 1 and v[i] == 0)


async def _check_byte(dut, byte):
    # Reset between bytes: T is free-running and firmware/RTL state (regs, PC, the
    # reference transmitter) must start clean for every case.
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)

    spi = SpiMaster(dut, other_bits=0x00)
    await spi.xfer(encode_write_prescale(1))  # 2 cycles per tick -> 217 ticks per bit
    await spi.xfer(encode_write_imem(0, assemble(_fw_source_for(byte))))
    await spi.xfer(encode_write_ctrl(run=True))

    dut.ref_data.value = byte

    fw, ref = [], []
    # Capture a few genuinely-idle cycles before arming the reference transmitter: ref_tx
    # goes low within a single clock of ref_start rising, so without at least one idle
    # sample ahead of it, first_fall() below could never see the preceding high level (the
    # capture would start already mid-transition and mis-detect a later edge instead).
    for _ in range(4):
        await FallingEdge(dut.clk)
        fw.append(int(dut.uo_out.value) & 1)
        ref.append(int(dut.ref_tx.value))

    dut.ref_start.value = 1  # start the reference transmitter too

    for _ in range(12 * 434):
        await FallingEdge(dut.clk)
        fw.append(int(dut.uo_out.value) & 1)
        ref.append(int(dut.ref_tx.value))
        if int(dut.ref_busy.value):
            dut.ref_start.value = 0

    a, b = _first_fall(fw), _first_fall(ref)
    frame_fw = fw[a:a + 10 * 434]
    frame_ref = ref[b:b + 10 * 434]
    assert frame_fw == frame_ref, (
        "firmware frame differs from the fixed transmitter for byte 0x%02X" % byte
    )
    assert fw[a + 10 * 434 + 5] == 1 and ref[b + 10 * 434 + 5] == 1

    # Strengthening: for the alternating 0x55 pattern (start=0, d0..d7 = 1,0,1,0,1,0,1,0,
    # stop=1) every adjacent bit cell differs, so every one of the 9 inter-bit boundaries
    # shows up as an edge. Check those edges are each exactly 434 clocks apart -- this
    # catches a common-mode shift in the deadline arithmetic that a plain equality against
    # the (also 434-clocks-per-bit) reference trace would not distinguish from correct
    # timing shifted by a constant.
    if byte == 0x55:
        edges = [i for i in range(1, len(frame_fw)) if frame_fw[i] != frame_fw[i - 1]]
        assert len(edges) == 9, (byte, edges)
        assert all(y - x == 434 for x, y in zip(edges, edges[1:])), (byte, edges)


@cocotb.test()
async def firmware_uart_matches_fixed_uart(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    for byte in (0x55, 0x00, 0xA3):
        await _check_byte(dut, byte)
