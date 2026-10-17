"""firmware/i2c_master.s on the full chip RTL (test/tb.v, through its pins) against the reference
I2C slave and standard-mode checker tools/refmodels/i2c_slave_ref.py, which also computes the
wired-AND bus the chip's uio_in is driven with: the same CASES as the oracle suite
tests/test_fw_i2c.py, plus its in-suite sentinel mutant (Q 96 must be rejected). Each case runs
with the bus rise time its slave sets (rise_time: 50 cycles, the 1 us standard-mode maximum;
stretch: 3) and an ideal pull-up otherwise; the oracle suite also runs every case at rise 3. The
commands go in over the host port (PUSH_FIFO) while a drain task reads the results back
(POP_FIFO), and every case checks that the drained words equal the pushes monitored on the core's
push strobe."""
import cocotb
from cocotb.triggers import ClockCycles
from tests.test_fw_i2c import CASES, MUTANT_Q, cycle_budget, model_for, case_errors
from fw_harness import boot, run_model, drain, host_push, firmware_text

# One host_push over the port costs about 2,950 cycles (test/test_spi_fw.py); added to the oracle's
# budget, which assumes words that are all in the FIFO at cycle 0.
HOST_PUSH_CYCLES = 3000

async def run_case(dut, name, fw_text=None):
    c = CASES[name]; at = c["at"]; words = c["words"]
    bus, host, _ = await boot(dut, "i2c_master.s", fw_text)
    ref = model_for(c)
    model = cocotb.start_soon(run_model(dut, bus, ref, cycle_budget(c) + HOST_PUSH_CYCLES * len(words)))
    done = [False]; drained = []
    task = cocotb.start_soon(drain(host, drained, lambda: done[0]))
    for i, w in enumerate(words):
        if at and i: await ClockCycles(dut.clk, at[i] - at[i - 1])
        await host_push(host, w)
    pushes = await model
    done[0] = True; await task
    ref.finish()
    return ref, pushes, drained

def make_test(name):
    async def test(dut):
        ref, pushes, drained = await run_case(dut, name)
        dut._log.info("events %s; pushes %s", ref.events, [(k, hex(w)) for k, w in pushes])
        errors = case_errors(name, ref, pushes)
        assert errors == [], errors
        assert drained == [w for _, w in pushes], (drained, pushes)
    test.__name__ = test.__qualname__ = "i2c_" + name; return cocotb.test()(test)

for _name in CASES: globals()["test_" + _name] = make_test(_name)

@cocotb.test()
async def i2c_sentinel_mutant_is_rejected(dut):
    src = firmware_text("i2c_master.s"); assert MUTANT_Q[0] in src
    ref, _, _ = await run_case(dut, "write2", src.replace(*MUTANT_Q, 1))
    assert ref.violations, "the reference accepted a 25 % fast SCL (Q 96)"
