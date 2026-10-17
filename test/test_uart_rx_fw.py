"""firmware/uart_rx.s on the full chip RTL (test/tb.v, through its pins) against the 8N1 reference
receiver checker tools/refmodels/uart_rx_ref.py: the same CASES as the oracle suite
tests/test_fw_uart_rx.py, plus its in-suite sentinel mutant (BIT 210 must be rejected). Every case
also checks that the words read back over the host port (POP_FIFO) equal the monitored pushes."""
import cocotb
from tools.refmodels.uart_rx_ref import UartRxRef
from tests.test_fw_uart_rx import CASES, CLK_HZ, BAUD, MUTANT_BIT
from fw_harness import boot, run_model, drain, firmware_text

async def run_case(dut, frames, fw_text=None):
    bus, host, _ = await boot(dut, "uart_rx.s", fw_text)
    ref = UartRxRef(CLK_HZ, BAUD); ref.schedule(frames)
    done = [False]; drained = []
    task = cocotb.start_soon(drain(host, drained, lambda: done[0]))
    pushes = await run_model(dut, bus, ref, ref.cycles)
    done[0] = True; await task
    return ref.check(pushes), pushes, drained

def make_test(name):
    async def test(dut):
        errors, pushes, drained = await run_case(dut, CASES[name])
        assert errors == [], errors
        assert drained == [w for _, w in pushes], (drained, pushes)
    test.__name__ = test.__qualname__ = "uart_rx_" + name; return cocotb.test()(test)

for _name in sorted(CASES): globals()["test_" + _name] = make_test(_name)

@cocotb.test()
async def uart_rx_sentinel_mutant_is_rejected(dut):
    src = firmware_text("uart_rx.s"); assert MUTANT_BIT[0] in src
    errors, _, _ = await run_case(dut, CASES["probe"], src.replace(*MUTANT_BIT, 1))
    assert errors, "the reference accepted a 3 % fast BIT"
