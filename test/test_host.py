import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
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
async def run_pin_starts_core_without_ctrl(dut):
    """Finding 4: no existing test exercises the RUN-pin leg of `run = ui_sync[7] | ctrl_run`
    -- every other test starts the core solely via WRITE_CTRL's run bit. Load a program, never
    send WRITE_CTRL run=True (ctrl_run stays 0 throughout), and raise ui_in[7] directly instead
    -- the program must still run. RUN is asynchronous on chip and passes through pe_gpio's
    two-flop input synchroniser plus the core's own RUN register (finding 2), so allow a few
    extra cycles for it to take effect."""
    spi = await start(dut)
    await spi.xfer(encode_write_imem(0, assemble("TGL UO, 0x01\nHALT\nNOP")))
    # A fresh SpiMaster whose idle drive (CS_n high, SCK/MOSI low) also holds RUN high; no
    # WRITE_CTRL transfer is ever issued, so ctrl_run remains 0 the whole test.
    SpiMaster(dut, other_bits=0x80)
    await ClockCycles(dut.clk, 10)               # 2-flop input sync + core RUN register settle
    await FallingEdge(dut.clk)
    assert int(dut.uo_out.value) & 1 == 1, "raising ui_in[7] (RUN) directly did not start the core"

@cocotb.test()
async def fifo_roundtrip_and_gpio_snapshot(dut):
    spi = await start(dut)
    await spi.xfer(encode_write_imem(0, assemble("WAITF RXV, R0\nPOP R1\nADDI R1, 1\nPUSH R1\nHALT\nNOP")))
    await spi.xfer(encode_write_ctrl(run=True))
    await spi.xfer(bytes([CMD_PUSH_FIFO, 0x12, 0x34])); await ClockCycles(dut.clk, 20)
    r = await spi.xfer(bytes([CMD_POP_FIFO, 0, 0])); assert (r[1] << 8 | r[2]) == 0x1235, r

    # Finding 3: READ_GPIO must report real, checkable values, not just a fixed reply length.
    # Load the pin-setting program from load_program_and_run, drive known ui_in[3:0]/uio_in
    # levels (via SpiMaster.other_bits, which the module's _drive holds on ui_in[3:0] and
    # ui_in[7] throughout a whole transfer -- see tools/host.py), let the two-flop input
    # synchroniser settle (finding 10: pe_host_spi now reports ui_sync/uio_sync, not the raw
    # pins), then check the snapshot.
    gpio_spi = SpiMaster(dut, other_bits=0x05)         # RUN=0, ui_in[3:0]=0x5
    dut.uio_in.value = 0x3C
    await spi.xfer(encode_write_imem(0, assemble("SET UO, 0x05\nSET UIO, 0x81\nOE 1, 0x81\nHALT\nNOP")))
    await gpio_spi.xfer(encode_write_ctrl(run=True, reset=True))
    await ClockCycles(dut.clk, 10)                      # program to HALT, and ui_sync/uio_sync to settle
    g = await gpio_spi.xfer(bytes([CMD_READ_GPIO, 0, 0, 0, 0, 0]))
    assert len(g) == 6, g
    # g[1] (ui_in snapshot) also carries the live SPI pins (bits [6:4]) and RUN (bit 7), which
    # are necessarily in motion during the READ_GPIO transfer itself; only ui_in[3:0] is a
    # meaningful, stable comparison (the core itself only ever looks at ui_sync[3:0] -- see
    # pe_core.v's ui_eff).
    assert g[1] & 0x0F == 0x05, g
    assert g[2] == 0x3C, g                              # uio_in: not pin-shared with the host port, so exact
    assert g[3] & 0x7F == 0x05, g                        # uo_out (top bit is MISO, mask it out)
    assert g[4] == 0x81, g                               # uio_out
    assert g[5] == 0x81, g                               # uio_oe

@cocotb.test()
async def write_ctrl_survives_tight_cs_deassert(dut):
    """Finding 6: byte_done is a one-cycle pulse that fires one clock after the 8th SCK rising
    edge; cs_act is itself a synchronised (2-cycle-delayed) view of CS_n. If the host raises
    CS_n immediately after clocking the last bit -- with none of the generous settling margin
    SpiMaster.xfer normally gives -- the WRITE_CTRL run bit must still take effect, not be
    silently dropped."""
    spi = await start(dut)
    await spi.xfer(encode_write_imem(0, assemble("TGL UO, 0x01\nHALT\nNOP")))

    half = 20  # core clocks per SPI half-period (matches SpiMaster's default 400ns / 20ns clk)

    def drive(sck, mosi, cs_n):
        dut.ui_in.value = (sck << 4) | (mosi << 5) | (cs_n << 6)

    drive(0, 0, 1); await ClockCycles(dut.clk, 2)
    drive(0, 0, 0); await ClockCycles(dut.clk, half)          # assert CS_n
    tx = bytes([CMD_WRITE_CTRL, 0x01])                        # run=1, reset=0
    for bi, b in enumerate(tx):
        for i in range(7, -1, -1):
            bit = (b >> i) & 1
            drive(0, bit, 0); await ClockCycles(dut.clk, half)
            drive(1, bit, 0)
            last_bit = (bi == len(tx) - 1) and (i == 0)
            if last_bit:
                await ClockCycles(dut.clk, 1)                 # minimal settle: one core clock only
                drive(0, 0, 1)                                # CS_n rises immediately
            else:
                await ClockCycles(dut.clk, half)
    await ClockCycles(dut.clk, 60)
    assert int(dut.uo_out.value) & 1 == 1, "WRITE_CTRL run bit was dropped under tight CS_n deassertion"

@cocotb.test()
async def write_imem_survives_bidx_saturation(dut):
    """Finding 7: bidx saturates at 0xFF; the old C_IMEM hi/lo byte selection used bidx[0]
    parity, which gets stuck at a constant value forever once bidx saturates, silently
    breaking WRITE_IMEM for any single transaction whose data crosses the bidx=0xFF boundary
    (word index 126 onward, counting from bidx=0 at the command byte). This sends 128 words
    -- enough to cross that boundary within one CS_n-active transaction -- and checks that
    word 127 (which lands in IMEM address 63, the same wrapped address as word 63, since the
    default IMEM is only 64 words deep) actually overwrote it, i.e. really got written."""
    spi = await start(dut)
    fast = SpiMaster(dut, other_bits=0x00, half_period_ns=160)   # minimum half period (8 core clocks); keeps this long transfer fast
    tgl_word = assemble("TGL UO, 0x01")[0]
    words = [0] * 128                          # all NOP except word 127
    words[127] = tgl_word                      # word 127 -> IMEM addr 63 (127 mod 64), same slot as word 63 (left as NOP)
    await fast.xfer(encode_write_imem(0, words))
    await spi.xfer(encode_write_ctrl(run=True))
    # PC free-runs through the (wrapped) 64-word IMEM at one NOP/cycle, so watch for it reaching
    # 63 and sample the toggle right after -- before PC wraps back around to 63 (as PC==127) and
    # re-executes the same TGL, which would toggle the pin back and mask a correct result.
    for _ in range(400):
        await RisingEdge(dut.clk)
        if int(dut.user_project.pc.value) == 63:
            break
    else:
        assert False, "core never reached PC 63"
    await ClockCycles(dut.clk, 2)
    assert int(dut.uo_out.value) & 1 == 1, "word 127 (sent after bidx=0xFF saturation) never reached IMEM address 63"

@cocotb.test()
async def h2c_fifo_full_reported_and_protected(dut):
    """Finding 8: the host->core FIFO is only 4 entries deep; PUSH_FIFO must not blindly drop
    data on the floor with no way for the host to see it coming. Fill it to full with the core
    halted (not consuming it), confirm STATUS bit4 (h2c_full) reports full only once it truly
    is, confirm an extra PUSH_FIFO while full does not displace what's already queued, and
    confirm the 4 original values come back out correctly once the core drains the FIFO."""
    spi = await start(dut)
    prog = ("WAITF RXV, R0\nPOP R1\nPUSH R1\n" * 4) + "HALT\nNOP"
    await spi.xfer(encode_write_imem(0, assemble(prog)))

    async def status_byte():
        st = await spi.xfer(bytes([CMD_READ_STATUS, 0, 0, 0, 0]))
        return st[1]

    assert (await status_byte()) & 0x10 == 0, "h2c_full asserted before any push"
    for v in (0x1000, 0x1001, 0x1002, 0x1003):
        await spi.xfer(bytes([CMD_PUSH_FIFO, (v >> 8) & 0xFF, v & 0xFF]))
    st = await status_byte()
    assert st & 0x10 == 0x10, ("h2c_full (status bit4) not reported once the 4-entry FIFO is full", st)
    assert st & 0x04 == 0x04, "h2c_valid (status bit2) should still read set while full"

    await spi.xfer(bytes([CMD_PUSH_FIFO, 0xDE, 0xAD]))     # FIFO is full: this push must be dropped
    st = await status_byte()
    assert st & 0x10 == 0x10, "h2c_full cleared unexpectedly after a dropped push"

    await spi.xfer(encode_write_ctrl(run=True))
    await ClockCycles(dut.clk, 60)
    got = []
    for _ in range(4):
        r = await spi.xfer(bytes([CMD_POP_FIFO, 0, 0]))
        got.append((r[1] << 8) | r[2])
    assert got == [0x1000, 0x1001, 0x1002, 0x1003], got   # the original 4, not the dropped 0xDEAD

    st = await status_byte()
    assert st & 0x10 == 0, "h2c_full still set after the FIFO was drained"

@cocotb.test()
async def core_reset_restarts_program(dut):
    spi = await start(dut)
    await spi.xfer(encode_write_imem(0, assemble("TGL UO, 0x01\nHALT\nNOP")))
    await spi.xfer(encode_write_ctrl(run=True)); await ClockCycles(dut.clk, 10)
    await spi.xfer(encode_write_ctrl(run=True, reset=True)); await ClockCycles(dut.clk, 10); await FallingEdge(dut.clk)
    assert int(dut.uo_out.value) & 1 == 0            # toggled twice

@cocotb.test()
async def write_prescale_doubles_timebase_period(dut):
    """Finding 5a: no test ever sends WRITE_PRESCALE. T is free-running (pe_timebase.v) and
    ticks once every (prescale+1) core clocks, independent of what the core is doing, so a
    WAITT-based toggle loop's steady-state period (in core clocks) is exactly
    (T delta) * (prescale + 1). Measure that period at prescale=0 and prescale=1 and confirm
    it doubles."""
    spi = await start(dut)
    await spi.xfer(encode_write_imem(0, assemble(
        "SETT R1, 0\nloop:\nADDT R1, 20\nTGL UO, 0x01\nWAITT R1\nJMP loop\nNOP")))

    async def measure_period(prescale):
        await spi.xfer(bytes([CMD_WRITE_PRESCALE, prescale]))
        await spi.xfer(encode_write_ctrl(run=True, reset=True))
        prev = int(dut.uo_out.value) & 1
        edges = []
        cycle = 0
        while len(edges) < 5:
            await FallingEdge(dut.clk)
            cycle += 1
            cur = int(dut.uo_out.value) & 1
            if cur != prev:
                edges.append(cycle); prev = cur
        return edges[-1] - edges[-2]   # last (fully steady-state) interval; skips any warm-up edge

    p0 = await measure_period(0)
    p1 = await measure_period(1)
    assert p0 == 20, p0
    assert p1 == 40, p1

@cocotb.test()
async def status_flags_reflect_alu_result(dut):
    """Finding 5b: status bit4-and-up flags byte (st[4]) is never checked against a real ALU
    result. flags_out = {fto, fc, fz} (pe_core.v), i.e. bit0=Z, bit1=C, bit2=TO. Run an ADD
    that overflows 16 bits (0xFFFF + 1 == 0x0000 mod 2^16, matching test_core.py's
    alu_flags_and_r0 idiom) and confirm both Z and C land where expected."""
    spi = await start(dut)
    await spi.xfer(encode_write_imem(0, assemble(
        "LDI R1, 0xFF\nLDIH R1, 0xFF\nLDI R2, 1\nADD R1, R2\nHALT\nNOP")))
    await spi.xfer(encode_write_ctrl(run=True))
    await ClockCycles(dut.clk, 10)
    st = await spi.xfer(bytes([CMD_READ_STATUS, 0, 0, 0, 0]))
    assert st[1] & 1 == 1, st                     # halted
    flags = st[4]
    assert flags & 0x1 == 1, ("Z not set for 0xFFFF+1 == 0x0000 (mod 2^16)", flags)
    assert flags & 0x2 == 2, ("C not set for an overflowing ADD", flags)

@cocotb.test()
async def status_fifo_flags_track_push_and_pop(dut):
    """Finding 5c: STATUS bit2 (h2c_valid) and bit3 (!c2h_valid, i.e. fifo_tx_empty) are never
    checked. Confirm bit2 goes high after a CMD_PUSH_FIFO with the core halted (not consuming
    it), and confirm bit3 goes from empty (1) to non-empty (0) once a core PUSH instruction
    actually runs."""
    spi = await start(dut)

    async def status_byte():
        st = await spi.xfer(bytes([CMD_READ_STATUS, 0, 0, 0, 0]))
        return st[1]

    # bit2: h2c_valid, set once host pushes data the (halted) core hasn't consumed yet.
    assert await status_byte() & 0x04 == 0, "h2c_valid set before any push"
    await spi.xfer(bytes([CMD_PUSH_FIFO, 0x00, 0x01]))
    assert await status_byte() & 0x04 == 0x04, "h2c_valid not set after PUSH_FIFO with the core halted"

    # bit3: !c2h_valid (fifo_tx_empty), true (1) while empty, false (0) once the core PUSHes.
    await spi.xfer(encode_write_imem(0, assemble("PUSH R0\nHALT\nNOP")))
    st = await status_byte()
    assert st & 0x08 == 0x08, ("fifo_tx_empty not set before the core has pushed anything", st)
    await spi.xfer(encode_write_ctrl(run=True, reset=True))
    await ClockCycles(dut.clk, 10)
    st = await status_byte()
    assert st & 0x08 == 0, ("fifo_tx_empty still set after a core PUSH", st)
