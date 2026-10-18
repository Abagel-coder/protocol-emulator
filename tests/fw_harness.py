"""Run a firmware on the oracle (tools/sim.py) against a cycle-stepped reference model, with the
chip's two-cycle input latency (test/test_diff.py's convention: levels driven in cycle k reach the
core in cycle k+2). Returns the core->host pushes as (cycle, word)."""
import pathlib
from collections import deque
from tools.asm import assemble, constants
from tools.sim import Sim

FIRMWARE = pathlib.Path(__file__).resolve().parents[1] / "firmware"
H2C_DEPTH = 4            # the chip's host->core FIFO depth (pe_fifo.v); Sim's deque is unbounded
IDLE = (0x0F, 0xFF)      # all protocol inputs high before the model's first step

def load(name, text=None):
    text = text if text is not None else (FIRMWARE / name).read_text()
    return assemble(text), constants(text)

def run_model(words, prescale_reg, model, cycles, host_words=(), host_at=None, t0=0xFF00,
              drain_from=0, core_prefill=()):
    """host_words[i] is pushed into the host->core FIFO at the first cycle >= host_at(i) (default 0)
    at which the FIFO has room. T starts at t0 (nonzero: deadlines cross the 16-bit wrap early).
    The core->host FIFO is drained (and its words returned as pushes) from cycle `drain_from` on
    (default 0: every cycle); until then it keeps what it holds, so a firmware that pushes into a
    full FIFO is stalled or loses the word. core_prefill: words already in that FIFO at cycle 0
    (they are returned with the first drain, at cycle `drain_from`)."""
    sim = Sim(words, prescale=prescale_reg + 1, t0=t0)
    sim.core_to_host.extend(core_prefill)
    lag = deque([IDLE, IDLE]); pending = list(host_words); i = 0; pushes = []
    for k in range(cycles):
        while pending and len(sim.host_to_core) < H2C_DEPTH and k >= (host_at(i) if host_at else 0):
            sim.host_to_core.append(pending.pop(0)); i += 1
        ui, uio = lag.popleft(); sim.set_inputs(ui=ui, uio_in=uio)
        _, uo, uio_out, uio_oe, _ = sim.step()
        while sim.core_to_host and k >= drain_from: pushes.append((k, sim.core_to_host.popleft()))
        lag.append(model.step(uo, uio_out, uio_oe))
    return pushes
