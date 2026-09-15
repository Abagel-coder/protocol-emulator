# SPDX-FileCopyrightText: © 2026 anbaghel
# SPDX-License-Identifier: Apache-2.0
"""cocotb tests for the warm-up UART transmitter wrapped in the Tiny Tapeout top level.

The checks are deliberately cycle-exact: every bit must last exactly CLKS_PER_BIT
clock cycles and the start bit must appear on the edge after START is sampled.
Inputs are driven right after a rising edge; outputs are sampled on falling edges,
so every sample reflects the value settled after the preceding rising edge.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

CLKS_PER_BIT = 434  # must match src/project.v
TX_BIT = 0
BUSY_BIT = 1


def tx(dut):
    return (int(dut.uo_out.value) >> TX_BIT) & 1


def busy(dut):
    return (int(dut.uo_out.value) >> BUSY_BIT) & 1


async def start_clock_and_reset(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())  # 50 MHz
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)


async def send_byte(dut, byte):
    """Pulse START for exactly one sampled clock edge and return per-cycle TX samples."""
    dut.ui_in.value = byte
    dut.uio_in.value = 1
    await RisingEdge(dut.clk)  # START is sampled here; start bit drives on this edge
    dut.uio_in.value = 0
    samples = []
    busy_samples = []
    for _ in range(10 * CLKS_PER_BIT):
        await FallingEdge(dut.clk)
        samples.append(tx(dut))
        busy_samples.append(busy(dut))
    return samples, busy_samples


@cocotb.test()
async def test_idle_after_reset(dut):
    await start_clock_and_reset(dut)
    await FallingEdge(dut.clk)
    assert tx(dut) == 1, "TX must idle high"
    assert busy(dut) == 0, "BUSY must be low after reset"
    assert int(dut.uio_oe.value) == 0, "all bidirectional pins must be inputs"
    await ClockCycles(dut.clk, 50)
    await FallingEdge(dut.clk)
    assert tx(dut) == 1 and busy(dut) == 0, "no spurious frame without START"


@cocotb.test()
async def test_frame_timing(dut):
    await start_clock_and_reset(dut)
    for byte in (0x55, 0x00, 0xFF, 0xA3, 0x01, 0x80):
        samples, busy_samples = await send_byte(dut, byte)
        expected = [0] + [(byte >> i) & 1 for i in range(8)] + [1]
        for i, bit in enumerate(expected):
            seg = samples[i * CLKS_PER_BIT:(i + 1) * CLKS_PER_BIT]
            bad = [k for k, s in enumerate(seg) if s != bit]
            assert not bad, (
                f"byte 0x{byte:02x} bit {i}: expected {bit} for {CLKS_PER_BIT} cycles, "
                f"first mismatch at cycle {bad[0]} of the bit"
            )
        assert all(busy_samples), f"byte 0x{byte:02x}: BUSY dropped during the frame"
        await FallingEdge(dut.clk)
        assert busy(dut) == 0, "BUSY must fall right after the stop bit"
        assert tx(dut) == 1, "TX must return to idle after the stop bit"
        await ClockCycles(dut.clk, 3)


@cocotb.test()
async def test_start_ignored_while_busy(dut):
    await start_clock_and_reset(dut)
    dut.ui_in.value = 0x3C
    dut.uio_in.value = 1
    await RisingEdge(dut.clk)
    dut.ui_in.value = 0xC3  # change data and keep START high mid-frame: must not retrigger
    await ClockCycles(dut.clk, 5 * CLKS_PER_BIT)
    dut.uio_in.value = 0
    await ClockCycles(dut.clk, 5 * CLKS_PER_BIT)
    await FallingEdge(dut.clk)
    assert busy(dut) == 0
    # d0 of 0x3C is 0; sample the middle of bit 1 of the frame that was actually sent
    # by replaying: cycles elapsed since START = 10*CLKS_PER_BIT+1, so the frame ended.
    # Verify no second frame starts because START was released before the frame ended.
    await ClockCycles(dut.clk, 20)
    await FallingEdge(dut.clk)
    assert busy(dut) == 0 and tx(dut) == 1
