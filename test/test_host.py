import os
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from tools.asm import assemble, assemble_file
from tools.host import *

FIRMWARE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firmware")

async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    dut.ena.value = 1; dut.uio_in.value = 0; dut.ui_in.value = 0x40   # CS_n high, RUN low
    dut.rst_n.value = 0; await ClockCycles(dut.clk, 3); dut.rst_n.value = 1; await ClockCycles(dut.clk, 2)
    return SpiMaster(dut, other_bits=0x00)

# The datasheet's bytes: these two literals are exactly what the "How to test" table in
# docs/info.md prints for loading and running firmware/blink.s, and must be kept identical to
# it. datasheet_blink_sequence below also checks them against what tools/asm.py and
# tools/host.py actually produce from the firmware file, so a change to the firmware, the
# assembler, the encoders or the datasheet's table fails the test instead of drifting quietly.
DATASHEET_WRITE_IMEM = bytes([0x01, 0x00, 0x00, 0x48, 0x01, 0x72, 0x06, 0xA0, 0x00, 0x00, 0x00])
DATASHEET_WRITE_CTRL = bytes([0x02, 0x01])

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
async def datasheet_blink_sequence(dut):
    """docs/info.md's "How to test" walk-through prints an exact SPI byte sequence that loads and
    starts firmware/blink.s, and claims a cocotb test exercises it -- this is that test. First
    confirm the printed bytes are still what the tools produce from the real firmware file, then
    send those literal bytes over the SPI pins and check the datasheet's timing claim on the chip
    pin itself: uo[0] toggles every 10 core clocks (20-clock period). Only the top-level uo_out
    pin is observed -- no internal signal -- so this holds identically in gate-level simulation,
    where the hierarchy does not survive synthesis."""
    words = assemble_file(os.path.join(FIRMWARE, "blink.s"))
    assert DATASHEET_WRITE_IMEM == encode_write_imem(0, words), (
        "docs/info.md's WRITE_IMEM bytes no longer match encode_write_imem() on firmware/blink.s",
        DATASHEET_WRITE_IMEM.hex(" "), encode_write_imem(0, words).hex(" "))
    assert DATASHEET_WRITE_CTRL == encode_write_ctrl(run=True), (
        "docs/info.md's WRITE_CTRL bytes no longer match encode_write_ctrl(run=True)",
        DATASHEET_WRITE_CTRL.hex(" "), encode_write_ctrl(run=True).hex(" "))

    spi = await start(dut)
    await spi.xfer(DATASHEET_WRITE_IMEM)                          # step 1: WRITE_IMEM at address 0
    await FallingEdge(dut.clk)
    assert int(dut.uo_out.value) & 1 == 0, "uo[0] moved before the core was started"
    await spi.xfer(DATASHEET_WRITE_CTRL)                          # step 2: WRITE_CTRL run=1

    # Time the toggles on uo_out[0] alone. The loop is already in steady state by the time the
    # WRITE_CTRL transfer's trailing CS_n-high settle is over, so every interval seen from here
    # must be the full loop: TGL(1) + DELAY 6(7) + JMP(1) + delay-slot NOP(1) = 10 core clocks.
    prev = int(dut.uo_out.value) & 1
    edges, cycle = [], 0
    while len(edges) < 6 and cycle < 200:
        await FallingEdge(dut.clk); cycle += 1
        cur = int(dut.uo_out.value) & 1
        if cur != prev:
            edges.append(cycle); prev = cur
    assert len(edges) == 6, ("uo[0] did not keep toggling after the datasheet's step 2", edges)
    intervals = [b - a for a, b in zip(edges, edges[1:])]         # 5 consecutive intervals
    assert all(i == 10 for i in intervals), (
        "uo[0] toggle interval is not the datasheet's 10 core clocks", intervals)

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
    (word index 126 onward, counting from bidx=0 at the command byte). This sends 128 words in
    one CS_n-active transaction; the second 64 overwrite IMEM addresses 0..63 (the memory is 64
    words, so word 64+k lands at address k): `JMP 63` at address 0, NOP in its delay slot at 1,
    HALT at 2..62 and `TGL UO, 0x01` at address 63 (word 127, the last one sent, well past the
    saturation point). Only if word 127 really reached address 63 does the core run the 3-cycle
    loop 0 -> 1 -> 63 -> 0 (JMP, slot, TGL; pc wraps modulo 64) and toggle uo[0] every 3 cycles;
    a word that landed anywhere else (mutant M6: imem_waddr stops incrementing once bidx sticks
    at 0xFF, so words 125..127 all land on address 61) leaves NOP/HALT at 63 and the pin never
    moves. Pin-only, so it holds identically in gate-level simulation."""
    spi = await start(dut)
    fast = SpiMaster(dut, other_bits=0x00, half_period_ns=160)   # minimum half period (8 core clocks); keeps this long transfer fast
    jmp63, nop, halt, tgl = assemble("JMP 63")[0], 0, assemble("HALT")[0], assemble("TGL UO, 0x01")[0]
    second = [jmp63, nop] + [halt] * 61 + [tgl]                   # words 64..127 -> addresses 0..63
    assert len(second) == 64
    words = [nop] * 64 + second
    await fast.xfer(encode_write_imem(0, words))
    assert int(dut.uo_out.value) & 1 == 0, "uo[0] must start low (no TGL has executed yet)"
    await spi.xfer(encode_write_ctrl(run=True))
    prev = int(dut.uo_out.value) & 1
    edges, cycle = [], 0
    while len(edges) < 6 and cycle < 400:
        await FallingEdge(dut.clk); cycle += 1
        cur = int(dut.uo_out.value) & 1
        if cur != prev:
            edges.append(cycle); prev = cur
    assert len(edges) == 6, ("no 0->1->63 toggle loop: word 127 is not at IMEM address 63", edges)
    intervals = [b - a for a, b in zip(edges, edges[1:])]
    assert all(i == 3 for i in intervals), ("toggle interval is not the 3-cycle JMP/slot/TGL loop", intervals)

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
        while len(edges) < 5 and cycle < 400:       # bounded: a loop that stops toggling must fail, not hang
            await FallingEdge(dut.clk)
            cycle += 1
            cur = int(dut.uo_out.value) & 1
            if cur != prev:
                edges.append(cycle); prev = cur
        assert len(edges) == 5, ("uo[0] stopped toggling at prescale %d" % prescale, edges)
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

# ---- host-port contracts from the datasheet (docs/info.md) that no earlier test distinguished
# from broken RTL (whole-branch review, final-review-verif.md M3/M4/M5, final-review-rtl.md
# E4/E8/E8c). All pin-level: no hierarchical reads, nothing X-capable, so they hold in gate-level
# simulation too.

async def status(spi):
    st = await spi.xfer(bytes([CMD_READ_STATUS, 0, 0, 0, 0]))
    return st[1], (st[2] << 8) | st[3], st[4]        # status byte, pc, flags

async def first_edge_after(dut, limit, mask=1):
    """Number of clock cycles (rising edges) until uo & mask first reads non-zero, sampled at
    each falling edge; None if it never does within `limit` cycles."""
    for n in range(1, limit + 1):
        await RisingEdge(dut.clk); await FallingEdge(dut.clk)
        if int(dut.uo_out.value) & mask:
            return n
    return None

@cocotb.test()
async def write_imem_start_address_is_honoured(dut):
    """docs/info.md protocol table: WRITE_IMEM's two address bytes set the start address and
    the address auto-increments per word. Every other test loads at 0, so a port that ignored
    the low address byte (mutant M3) was indistinguishable. Load a frame at 0 whose JMP reaches
    address 4, then load a marker program AT address 4 in a second transaction: with the
    address honoured the run shows 0x03 on uo (delay-slot SET UO,0x02 then the marker's
    SET UO,0x01) and halts at pc 5; with the second load landing at 0 instead it shows 0x01 and
    halts at pc 1."""
    spi = await start(dut)
    await spi.xfer(encode_write_imem(0, assemble("JMP 4\nSET UO, 0x02\nHALT\nNOP\nHALT\nNOP\nNOP\nNOP")))   # addresses 0..7 all defined
    await spi.xfer(encode_write_imem(4, assemble("SET UO, 0x01\nHALT\nNOP")))                             # addresses 4..6
    await spi.xfer(encode_write_ctrl(run=True)); await ClockCycles(dut.clk, 12); await FallingEdge(dut.clk)
    assert int(dut.uo_out.value) & 0x7F == 0x03, hex(int(dut.uo_out.value))
    st, pc, _ = await status(spi)
    assert st & 1 == 1 and pc == 5, (st, pc)         # halted at address 5, i.e. the marker really lived at 4

@cocotb.test()
async def run_latency_pin_three_cycles_ctrl_two(dut):
    """docs/info.md: a RUN-pin transition reaches the first executing instruction after three
    clock cycles (two synchroniser flops + the core's RUN register), and WRITE_CTRL's run bit,
    already a register in the clock domain, takes effect one cycle sooner. Pinned on the pin:
    with `SET UO, 0x01` at address 0 the registered pin write adds one more cycle, so uo[0]
    must read 1 exactly after the 4th rising edge following the RUN pin's rise (a bypassed
    synchroniser, mutant M4a, gives 2; an extra stage, M4b, gives 5). For WRITE_CTRL the run
    bit is set two edges after the 8th SCK rising edge of its payload byte is first sampled
    (SCK synchroniser + edge detect + byte_done), then RUN register, execute, pin write: uo[0]
    reads 1 exactly after the 6th rising edge following that SCK edge, i.e. two register
    stages (ctrl_run, run_q) from the run bit to the first instruction against the pin's three."""
    spi = await start(dut)
    await spi.xfer(encode_write_imem(0, assemble("SET UO, 0x01\nHALT\nNOP")))
    # RUN pin: drive it on a falling edge so the next rising edge is unambiguously the first to see it.
    await FallingEdge(dut.clk)
    dut.ui_in.value = 0x80 | 0x40                                    # RUN high, CS_n high, SCK/MOSI low
    n = await first_edge_after(dut, 10)
    assert n == 4, ("uo[0] rose after rising edge %r following the RUN pin, expected 4 (3 cycles to the first instruction + the registered pin write)" % n)
    # WRITE_CTRL: same program, restarted halted-and-stopped; hand-driven SPI aligned to falling edges.
    dut.ui_in.value = 0x40                                           # RUN low again
    await spi.xfer(encode_write_ctrl(run=False, reset=True))         # core_reset pulse -> pc 0, not halted; run stays 0
    await ClockCycles(dut.clk, 4); await FallingEdge(dut.clk)
    assert int(dut.uo_out.value) & 1 == 1                            # (the pin keeps its value across core_reset: pe_gpio has no core_reset)
    await spi.xfer(encode_write_imem(0, assemble("CLR UO, 0x01\nSET UO, 0x01\nHALT\nNOP")))   # clears, then sets: the SET is the 2nd instruction
    half = 20
    async def drive(sck, mosi, cs_n, cycles):
        dut.ui_in.value = (sck << 4) | (mosi << 5) | (cs_n << 6)
        for _ in range(cycles): await FallingEdge(dut.clk)
    await FallingEdge(dut.clk)
    await drive(0, 0, 0, half)                                       # CS_n low
    tx = [CMD_WRITE_CTRL, 0x01]
    for bi, b in enumerate(tx):
        for i in range(7, -1, -1):
            bit = (b >> i) & 1
            await drive(0, bit, 0, half)
            last = (bi == 1 and i == 0)
            if last:
                dut.ui_in.value = (1 << 4) | (bit << 5)              # 8th SCK rising edge of the payload byte, driven right after a falling edge
                # The CLR at address 0 executes first, so watch for uo[0] to go 1 -> 0 -> 1: the SET (2nd
                # instruction) lands one cycle after the CLR. Count edges until the CLR is visible instead.
                for n in range(1, 12):
                    await RisingEdge(dut.clk); await FallingEdge(dut.clk)
                    if int(dut.uo_out.value) & 1 == 0:
                        break
                else:
                    n = None
            else:
                await drive(1, bit, 0, half)
    await FallingEdge(dut.clk); dut.ui_in.value = 0x40               # CS_n high
    assert n == 6, ("first instruction after WRITE_CTRL run=1 became visible after rising edge %r following the 8th SCK edge, expected 6" % n)
    await ClockCycles(dut.clk, 4); await FallingEdge(dut.clk)
    assert int(dut.uo_out.value) & 1 == 1                            # the SET followed one cycle later and the program halted

@cocotb.test()
async def write_ctrl_run0_stops_core_and_run1_resumes(dut):
    """docs/info.md: WRITE_CTRL's run bit (or the RUN pin) holds the core active only while
    asserted. No earlier test ever sent run=0 (mutant M5: a sticky run bit). Start the blink
    loop, see it toggling, send run=0: the pin must freeze within a few cycles and stay frozen;
    run=1 again (without reset) resumes the loop where it stopped."""
    spi = await start(dut)
    await spi.xfer(encode_write_imem(0, assemble_file(os.path.join(FIRMWARE, "blink.s"))))
    await spi.xfer(encode_write_ctrl(run=True))
    async def count_edges(cycles):
        prev = int(dut.uo_out.value) & 1; edges = 0
        for _ in range(cycles):
            await FallingEdge(dut.clk)
            cur = int(dut.uo_out.value) & 1
            if cur != prev: edges += 1; prev = cur
        return edges
    assert await count_edges(60) >= 5, "blink loop not running before run=0"
    await spi.xfer(encode_write_ctrl(run=False))
    st, _, _ = await status(spi)
    assert st & 0x02 == 0, ("status bit1 (running) still set after run=0", st)
    assert st & 0x01 == 0, ("core reports halted after a run=0 pause (it must be paused, not halted)", st)
    await ClockCycles(dut.clk, 4)                                    # let the last in-flight cycle settle
    assert await count_edges(300) == 0, "uo[0] kept toggling after WRITE_CTRL run=0"
    await spi.xfer(encode_write_ctrl(run=True))
    assert await count_edges(60) >= 5, "blink loop did not resume after run=1"

@cocotb.test()
async def reset_core_mid_wait_restarts_from_pc0(dut):
    """docs/info.md: WRITE_CTRL bit1 restarts the program at PC 0. A reset issued while the core
    is stalled in a wait, or while a taken branch's delay slot is pending, must discard that
    state too (formal P1; mutants E4a: wait_active survives core_reset, E4b: the pending
    redirect survives). Both are timed so the reset transaction (fast SPI, ~280 clocks) lands
    inside a DELAY 400:
      (a) `DELAY 400; SET UO,0x01; HALT` -- after the reset the DELAY must start over, so the
          pin rises ~400 cycles after the reset (a surviving countdown would rise much sooner);
      (b) `JMP 4; DELAY 400 (delay slot); ...; 4: SET UO,0x01` -- after the reset the JMP
          re-executes and its slot's DELAY runs in full before address 4 is reached (a surviving
          redirect sends the restarted JMP straight to 4 within a few cycles).
    Each scenario sets its own uo bit (pe_gpio keeps its outputs across core_reset, so a bit
    set by the previous scenario would otherwise read as an early rise), and that bit still
    reading 0 when the reset transaction ends proves the reset landed inside the DELAY rather
    than after the SET -- and is itself the assertion the mutants trip: with a surviving
    countdown (dcnt is reset to 0, so the stale wait completes at once) or a surviving
    redirect, the SET executes 2-3 cycles after the reset pulse, before the transaction's
    trailing CS_n settle is over. Measured on the pristine RTL: the pin rises 392 cycles after a start
    transaction ends (401 stall cycles + the SET, minus the ~10 cycles between the run/reset
    pulse and the transaction's trailing CS_n settle), and the same after a mid-wait reset."""
    spi = await start(dut)
    fast = SpiMaster(dut, other_bits=0x00, half_period_ns=160)
    async def scenario(src, mask, expect_lo, expect_hi):
        await spi.xfer(encode_write_imem(0, assemble(src)))
        await fast.xfer(encode_write_ctrl(run=True, reset=True))     # start (a fresh program, so reset+run)
        await fast.xfer(encode_write_ctrl(run=True, reset=True))     # the mid-wait reset under test, ~270 clocks after the start
        assert int(dut.uo_out.value) & mask == 0, (
            "uo bit already set when the reset transaction ended: either the reset landed after the SET "
            "(retime the test) or the restarted program reached its SET within the ~10 trailing cycles of "
            "the transaction, i.e. a wait countdown or a pending redirect survived core_reset")
        n = await first_edge_after(dut, 700, mask)
        assert n is not None and expect_lo <= n <= expect_hi, ("uo bit rose %r cycles after the mid-wait reset, expected %d..%d" % (n, expect_lo, expect_hi))
        await ClockCycles(dut.clk, 4)
        st, pc, _ = await status(spi)
        return pc
    # (a) DELAY 400 restarted from scratch: 392 cycles (a surviving countdown: ~130).
    pc = await scenario("DELAY 400\nSET UO, 0x01\nHALT\nNOP", 0x01, 385, 400)
    assert pc == 2, pc
    # (b) pending redirect discarded: JMP (1) + DELAY 400 (401) + SET -> 393 cycles (a surviving redirect: ~2).
    pc = await scenario("JMP 4\nDELAY 400\nHALT\nNOP\nSET UO, 0x02\nHALT\nNOP", 0x02, 385, 402)
    assert pc == 5, pc

@cocotb.test()
async def cs_abort_discards_partial_byte(dut):
    """docs/info.md: a byte is received on the SPI clock edge that samples its last bit, framed
    by CS_n. Raising CS_n mid-byte must discard the partial byte and the bit count, so the next
    CS_n-framed transaction is framed from scratch (mutant E8: bitcnt not reset when CS_n is
    high, so the leftover bits misframe every later byte). A WRITE_CTRL whose payload byte is
    aborted after 4 bits must not start the core; a complete WRITE_CTRL run=1 right after it
    must."""
    spi = await start(dut)
    await spi.xfer(encode_write_imem(0, assemble("TGL UO, 0x01\nHALT\nNOP")))
    half = 20
    async def drive(sck, mosi, cs_n, cycles):
        dut.ui_in.value = (sck << 4) | (mosi << 5) | (cs_n << 6)
        for _ in range(cycles): await FallingEdge(dut.clk)
    await FallingEdge(dut.clk)
    await drive(0, 0, 0, half)                                       # CS_n low
    for i in range(7, -1, -1):                                       # full command byte: WRITE_CTRL
        bit = (CMD_WRITE_CTRL >> i) & 1
        await drive(0, bit, 0, half); await drive(1, bit, 0, half)
    for i in range(7, 3, -1):                                        # 4 bits of the payload (0000), then abort
        await drive(0, 0, 0, half); await drive(1, 0, 0, half)
    await drive(0, 0, 1, half)                                       # CS_n high mid-byte
    await ClockCycles(dut.clk, 20); await FallingEdge(dut.clk)
    st, _, _ = await status(spi)
    assert st & 0x03 == 0 and int(dut.uo_out.value) & 1 == 0, ("the aborted WRITE_CTRL took effect", st)
    await spi.xfer(encode_write_ctrl(run=True))
    await ClockCycles(dut.clk, 10); await FallingEdge(dut.clk)
    assert int(dut.uo_out.value) & 1 == 1, "WRITE_CTRL run=1 after a mid-byte abort did not start the core (stale bit count)"

@cocotb.test()
async def unknown_command_is_ignored(dut):
    """docs/info.md lists commands 0x01..0x07; any other command byte must be ignored together
    with its payload -- not decoded from its low bits (mutant E8c: cmd <= rx_byte[2:0], under
    which 0x09 acts as WRITE_IMEM and 0x0A as WRITE_CTRL). Send a fake WRITE_IMEM (0x09) that
    would overwrite address 0, then a fake WRITE_CTRL (0x0A) with run=1: nothing may run; a
    real WRITE_CTRL then runs the original program."""
    spi = await start(dut)
    await spi.xfer(encode_write_imem(0, assemble("TGL UO, 0x01\nHALT\nNOP")))
    fake_imem = bytes([0x09]) + encode_write_imem(0, assemble("SET UO, 0x02\nHALT\nNOP"))[1:]
    await spi.xfer(fake_imem)
    await spi.xfer(bytes([0x0A, 0x01]))                              # would be run=1 if decoded as 0x02
    await ClockCycles(dut.clk, 30); await FallingEdge(dut.clk)
    st, _, _ = await status(spi)
    assert st & 0x03 == 0, ("core started on an unknown command byte", st)
    assert int(dut.uo_out.value) & 0x7F == 0, hex(int(dut.uo_out.value))
    await spi.xfer(encode_write_ctrl(run=True)); await ClockCycles(dut.clk, 10); await FallingEdge(dut.clk)
    assert int(dut.uo_out.value) & 0x7F == 0x01, ("the fake WRITE_IMEM overwrote address 0", hex(int(dut.uo_out.value)))

@cocotb.test()
async def post_reset_state_and_running_bit(dut):
    """docs/info.md "How to test" step 1: after reset the core is halted-until-RUN, uio_oe == 0,
    all outputs 0 and MISO (uo[7]) idle low. READ_STATUS bit1 (running) reads 1 while the core
    is active and 0 once it halts (bit0)."""
    spi = await start(dut)
    await FallingEdge(dut.clk)
    assert int(dut.uo_out.value) == 0 and int(dut.uio_out.value) == 0 and int(dut.uio_oe.value) == 0
    st, pc, flags = await status(spi)
    assert st & 0x03 == 0 and pc == 0 and flags == 0, (st, pc, flags)     # not halted (no HALT yet), not running, pc 0
    await spi.xfer(encode_write_imem(0, assemble_file(os.path.join(FIRMWARE, "blink.s"))))
    await spi.xfer(encode_write_ctrl(run=True))
    st, _, _ = await status(spi)
    assert st & 0x03 == 0x02, ("running bit not set while the blink loop runs", st)
    await spi.xfer(encode_write_imem(0, assemble("HALT\nNOP")))
    await spi.xfer(encode_write_ctrl(run=True, reset=True)); await ClockCycles(dut.clk, 10)
    st, _, _ = await status(spi)
    assert st & 0x03 == 0x01, ("halted core still reports running", st)
