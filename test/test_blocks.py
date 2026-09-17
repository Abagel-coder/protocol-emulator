import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    dut.rst_n.value = 0; await ClockCycles(dut.clk, 3); dut.rst_n.value = 1; await RisingEdge(dut.clk)

@cocotb.test()
async def timebase_counts_and_prescales(dut):
    await start(dut); dut.en.value = 1; dut.prescale.value = 0
    await ClockCycles(dut.clk, 10); await FallingEdge(dut.clk); t0 = int(dut.t_out.value)
    await ClockCycles(dut.clk, 5); await FallingEdge(dut.clk); assert int(dut.t_out.value) == t0 + 5
    dut.prescale.value = 1                                   # divide by 2
    await FallingEdge(dut.clk); t1 = int(dut.t_out.value)
    await ClockCycles(dut.clk, 10); await FallingEdge(dut.clk); assert int(dut.t_out.value) == t1 + 5

@cocotb.test()
async def gpio_reset_state_and_write_timing(dut):
    await start(dut)
    await FallingEdge(dut.clk)
    assert int(dut.uio_oe.value) == 0 and int(dut.uo_out.value) == 0 and int(dut.uio_out.value) == 0
    dut.wr_en.value = 1; dut.wr_op.value = 0; dut.wr_bank.value = 0; dut.wr_mask.value = 0x05   # SET UO 0x05
    await RisingEdge(dut.clk); dut.wr_en.value = 0
    await FallingEdge(dut.clk); assert int(dut.uo_out.value) == 0x05
    dut.wr_en.value = 1; dut.wr_op.value = 2; dut.wr_mask.value = 0x01                          # TGL UO 0x01
    await RisingEdge(dut.clk); dut.wr_en.value = 0
    await FallingEdge(dut.clk); assert int(dut.uo_out.value) == 0x04
    dut.wr_en.value = 1; dut.wr_op.value = 3; dut.wr_bank.value = 1; dut.wr_mask.value = 0xF0    # OE set 0xF0
    await RisingEdge(dut.clk); dut.wr_en.value = 0
    await FallingEdge(dut.clk); assert int(dut.uio_oe.value) == 0xF0
    dut.pin_en.value = 1; dut.pin_bank.value = 1; dut.pin_idx.value = 7; dut.pin_val.value = 1   # SETR uio[7]=1
    await RisingEdge(dut.clk); dut.pin_en.value = 0
    await FallingEdge(dut.clk); assert int(dut.uio_out.value) == 0x80

@cocotb.test()
async def gpio_input_sync_two_cycles(dut):
    await start(dut); dut.ui_in.value = 0
    await ClockCycles(dut.clk, 3); dut.ui_in.value = 0x0F
    await RisingEdge(dut.clk); await FallingEdge(dut.clk); assert int(dut.ui_sync.value) == 0x00
    await RisingEdge(dut.clk); await FallingEdge(dut.clk); assert int(dut.ui_sync.value) == 0x0F
    assert int(dut.ui_prev.value) == 0x00
    await RisingEdge(dut.clk); await FallingEdge(dut.clk); assert int(dut.ui_prev.value) == 0x0F
