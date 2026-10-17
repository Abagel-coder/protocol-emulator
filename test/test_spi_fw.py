"""firmware/spi_master.s on the full chip RTL (test/tb.v, through its pins) against the reference
SPI slave and master checker tools/refmodels/spi_slave_ref.py: the same CASES as the oracle suite
tests/test_fw_spi.py, plus its in-suite sentinel mutant (HALF 27 must be rejected). The commands
go in over the host port (PUSH_FIFO) while a drain task reads the results back (POP_FIFO), and
every case checks that the drained words equal the pushes monitored on the core's push strobe and
that every SCK interval within a byte is exactly half a period."""
import cocotb
from cocotb.triggers import ClockCycles
from tests.test_fw_spi import CASES, MUTANT_HALF, H, host_words, cycle_budget, model_for, case_errors
from fw_harness import boot, run_model, drain, host_push, firmware_text

# One host_push over the port: its status poll and PUSH_FIFO at clk/20, interleaved with drain's
# status polls on the locked port, measured at about 2,950 cycles per word; added to the oracle's
# budget, which assumes words that are all in the FIFO at cycle 0.
HOST_PUSH_CYCLES = 3000

async def run_case(dut, name, fw_text=None):
    c = CASES[name]; at = c["at"]; words = host_words(c)
    bus, host, _ = await boot(dut, "spi_master.s", fw_text)
    ref = model_for(c)
    model = cocotb.start_soon(run_model(dut, bus, ref, cycle_budget(c) + HOST_PUSH_CYCLES * len(words)))
    done = [False]; drained = []
    task = cocotb.start_soon(drain(host, drained, lambda: done[0]))
    for i, w in enumerate(words):
        if at and i: await ClockCycles(dut.clk, at[i] - at[i - 1])
        await host_push(host, w)
    pushes = await model
    done[0] = True; await task
    return ref, pushes, drained

def make_test(name):
    async def test(dut):
        ref, pushes, drained = await run_case(dut, name)
        dut._log.info("transactions %s; lead/lag %s; pushes %s", ref.transactions,
                      [(e[0] - t["cs_fall"], t["cs_rise"] - e[-1]) for t, e in zip(ref.transactions, ref.edge_cycles)],
                      [(k, hex(w)) for k, w in pushes])
        ref.finish()
        errors = case_errors(CASES[name], ref, pushes)
        assert errors == [], errors
        assert drained == [w for _, w in pushes], (drained, pushes)
        for edges in ref.edge_cycles:                       # deadline-driven: no jitter within a byte
            assert all(edges[n] - edges[n - 1] == H for n in range(1, len(edges)) if n % 16), edges
    test.__name__ = test.__qualname__ = "spi_" + name; return cocotb.test()(test)

for _name in CASES: globals()["test_" + _name] = make_test(_name)

@cocotb.test()
async def spi_sentinel_mutant_is_rejected(dut):
    src = firmware_text("spi_master.s"); assert MUTANT_HALF[0] in src
    ref, _, _ = await run_case(dut, "mode0", src.replace(*MUTANT_HALF, 1))
    ref.finish()
    assert ref.violations, "the reference accepted an 8 % slow SCK (HALF 27)"
