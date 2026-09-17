import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge
from tools.asm import assemble
from tools.host import *

async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    dut.ena.value = 1; dut.uio_in.value = 0; dut.ui_in.value = 0x40   # CS_n high, RUN low
    dut.rst_n.value = 0; await ClockCycles(dut.clk, 3); dut.rst_n.value = 1; await ClockCycles(dut.clk, 2)
    return SpiMaster(dut, other_bits=0x00)

@cocotb.test()
async def load_program_and_run(dut):
    spi = await start(dut)
    words = assemble("SET UO, 0x05\nSET UIO, 0x81\nOE 1, 0x81\nHALT\nNOP")
    await spi.xfer(encode_write_imem(0, words))
    await FallingEdge(dut.clk); assert int(dut.uo_out.value) & 0x7F == 0         # halted: nothing ran yet
    await spi.xfer(encode_write_ctrl(run=True)); await ClockCycles(dut.clk, 10); await FallingEdge(dut.clk)
    assert int(dut.uo_out.value) & 0x7F == 0x05 and int(dut.uio_out.value) == 0x81 and int(dut.uio_oe.value) == 0x81
    st = await spi.xfer(bytes([CMD_READ_STATUS, 0, 0, 0, 0]))
    assert st[1] & 1 == 1, st                                                     # halted
    assert (st[2] << 8 | st[3]) == 3, st                                          # pc at HALT

@cocotb.test()
async def fifo_roundtrip_and_gpio_snapshot(dut):
    spi = await start(dut)
    await spi.xfer(encode_write_imem(0, assemble("WAITF RXV, R0\nPOP R1\nADDI R1, 1\nPUSH R1\nHALT\nNOP")))
    await spi.xfer(encode_write_ctrl(run=True))
    await spi.xfer(bytes([CMD_PUSH_FIFO, 0x12, 0x34])); await ClockCycles(dut.clk, 20)
    r = await spi.xfer(bytes([CMD_POP_FIFO, 0, 0])); assert (r[1] << 8 | r[2]) == 0x1235, r
    g = await spi.xfer(bytes([CMD_READ_GPIO, 0, 0, 0, 0, 0])); assert len(g) == 6

@cocotb.test()
async def core_reset_restarts_program(dut):
    spi = await start(dut)
    await spi.xfer(encode_write_imem(0, assemble("TGL UO, 0x01\nHALT\nNOP")))
    await spi.xfer(encode_write_ctrl(run=True)); await ClockCycles(dut.clk, 10)
    await spi.xfer(encode_write_ctrl(run=True, reset=True)); await ClockCycles(dut.clk, 10); await FallingEdge(dut.clk)
    assert int(dut.uo_out.value) & 1 == 0            # toggled twice
