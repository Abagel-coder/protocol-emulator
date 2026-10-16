import random
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

async def imem_write(dut, addr, data):
    """One host write, clocked at the next rising edge (active must be 0 for it to land)."""
    dut.im_wr_en.value = 1; dut.im_waddr.value = addr; dut.im_wdata.value = data
    await RisingEdge(dut.clk); dut.im_wr_en.value = 0

async def imem_fill(dut, words):
    for a, w in enumerate(words): await imem_write(dut, a, w)

async def imem_idle(dut):
    """Quiet inputs so no state leaks in from the previous test."""
    dut.im_active.value = 0; dut.im_wr_en.value = 0; dut.im_raddr.value = 0; dut.im_waddr.value = 0; dut.im_wdata.value = 0

async def imem_read(dut, addr):
    """Present addr, clock once, sample both outputs after the edge."""
    dut.im_raddr.value = addr; await RisingEdge(dut.clk); await FallingEdge(dut.clk)
    return int(dut.im_rdata_m.value), int(dut.im_rdata_f.value)

@cocotb.test()
async def imem_512_words_read_back_and_alias_bit9(dut):
    """All 512 words are distinct and readable; raddr/waddr bit 9 is ignored (512+k reads and writes k)."""
    await start(dut); await imem_idle(dut)
    words = [(a * 0x9E37 + 0x1234) & 0xFFFF for a in range(512)]
    await imem_fill(dut, words)
    for a in [0, 1, 63, 64, 255, 256, 511, 512 + 5, 1023]:
        m, f = await imem_read(dut, a)
        assert m == words[a % 512] and f == words[a % 512], (a, hex(m), hex(f))
    await imem_write(dut, 512 + 9, 0xA5A5); await imem_write(dut, 1023, 0x5A5A)   # waddr bit 9 set lands on 9 and 511
    assert await imem_read(dut, 9) == (0xA5A5, 0xA5A5), "write at 512+9 must land on word 9"
    assert await imem_read(dut, 511) == (0x5A5A, 0x5A5A), "write at 1023 must land on word 511"

@cocotb.test()
async def imem_write_while_active_is_dropped_and_reported(dut):
    """A write with active=1 changes nothing and pulses wr_dropped for exactly that cycle; the
    same write with active=0 lands and is not flagged."""
    await start(dut); await imem_idle(dut)
    await imem_fill(dut, [0x1111] * 512)
    dut.im_active.value = 1
    dut.im_wr_en.value = 1; dut.im_waddr.value = 7; dut.im_wdata.value = 0x2222
    await FallingEdge(dut.clk)
    assert int(dut.im_drop_m.value) == 1 and int(dut.im_drop_f.value) == 1
    await RisingEdge(dut.clk); dut.im_wr_en.value = 0
    await FallingEdge(dut.clk)
    assert int(dut.im_drop_m.value) == 0 and int(dut.im_drop_f.value) == 0
    dut.im_active.value = 0
    assert await imem_read(dut, 7) == (0x1111, 0x1111), "a write while active must be dropped"
    dut.im_wr_en.value = 1; dut.im_waddr.value = 7; dut.im_wdata.value = 0x2222   # accepted write: sample before its edge
    await FallingEdge(dut.clk)
    assert int(dut.im_drop_m.value) == 0 and int(dut.im_drop_f.value) == 0, "an accepted write must not be flagged as dropped"
    await RisingEdge(dut.clk); dut.im_wr_en.value = 0
    assert await imem_read(dut, 7) == (0x2222, 0x2222)

@cocotb.test()
async def imem_read_output_holds_during_a_write(dut):
    """A paused core keeps reading its stalled pc. A host write to that same address must not
    change the output register during the write cycle (no write-through); the next read cycle
    returns the new word. With a different waddr and raddr the output must still be the previous
    word (not mem[raddr], not mem[waddr]), then raddr's word, and the written word lands."""
    await start(dut); await imem_idle(dut)
    await imem_fill(dut, list(range(512)))
    assert await imem_read(dut, 100) == (100, 100)
    await imem_write(dut, 100, 0xBEEF)                 # raddr is still 100
    await FallingEdge(dut.clk)
    assert (int(dut.im_rdata_m.value), int(dut.im_rdata_f.value)) == (100, 100), "output must hold through the write"
    await RisingEdge(dut.clk); await FallingEdge(dut.clk)
    assert (int(dut.im_rdata_m.value), int(dut.im_rdata_f.value)) == (0xBEEF, 0xBEEF), "the read after the write sees the new word"
    await imem_write(dut, 100, 100)                    # restore, then the different-address case
    assert await imem_read(dut, 100) == (100, 100)
    dut.im_raddr.value = 300; dut.im_wr_en.value = 1; dut.im_waddr.value = 200; dut.im_wdata.value = 0xBEEF
    await RisingEdge(dut.clk); dut.im_wr_en.value = 0
    await FallingEdge(dut.clk)
    assert (int(dut.im_rdata_m.value), int(dut.im_rdata_f.value)) == (100, 100), "output must hold the old word when waddr != raddr"
    await RisingEdge(dut.clk); await FallingEdge(dut.clk)
    assert (int(dut.im_rdata_m.value), int(dut.im_rdata_f.value)) == (300, 300), "the cycle after the write is a normal read of raddr"
    assert await imem_read(dut, 200) == (0xBEEF, 0xBEEF), "the write to 200 landed"

@cocotb.test()
async def imem_macro_and_flops_agree_under_random_traffic(dut):
    """2,000 random cycles of reads, writes and active toggles: both implementations must give
    the same rdata every cycle, and wr_dropped must equal (active and wr_en) of that cycle."""
    await start(dut); await imem_idle(dut)
    rng = random.Random(7)
    await imem_fill(dut, [rng.randrange(65536) for _ in range(512)])
    for _ in range(2000):
        active = int(rng.random() < 0.5); wr_en = int(rng.random() < 0.3)
        dut.im_active.value = active; dut.im_wr_en.value = wr_en
        dut.im_waddr.value = rng.randrange(1024); dut.im_wdata.value = rng.randrange(65536)
        dut.im_raddr.value = rng.randrange(1024)
        await RisingEdge(dut.clk); await FallingEdge(dut.clk)
        assert int(dut.im_rdata_m.value) == int(dut.im_rdata_f.value)
        assert int(dut.im_drop_m.value) == int(active and wr_en), "wr_dropped must be active and wr_en"
        assert int(dut.im_drop_f.value) == int(active and wr_en), "wr_dropped must be active and wr_en"
    await imem_idle(dut)
