# Plan C: Protocol Firmware with Independent Reference Models — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. By the owner's instruction, all code in this plan is written by Opus/Sonnet implementer agents: the plan fixes the exact semantics, files, interfaces, test names, mutants and commands; where a step says "write", the implementer writes it test-first. Firmware drafts are given in full so that delay-slot and flag mistakes are not rediscovered; the implementer may change them where a test shows a draft wrong, and must then say so in the task report.

**Goal:** `firmware/uart_rx.s`, `firmware/spi_master.s` and `firmware/i2c_master.s` run on the chip RTL against reference models written from the protocol specifications, in CI, with each model shown to reject a timing mutant of its firmware.

**Architecture:** One cycle-stepped Python reference model per protocol (`tools/refmodels/`), each with a single `step(uo, uio_out, uio_oe) -> (ui, uio_in)` method, driven by two harnesses: the oracle harness (`tests/fw_harness.py`, runs the firmware on `tools/sim.py`, pytest) and the RTL harness (`test/fw_harness.py`, the full chip through its pins with the host SPI port, cocotb). Design: `docs/superpowers/specs/2026-10-16-protocol-firmware-design.md` — read it first.

**Tech Stack:** pe-isa v0 assembly (`tools/asm.py`), Python 3.12 (`.venv`, pytest 8.4.2), cocotb 2.0.1 + Icarus via `source env.sh`, GitHub Actions `test` and `tools` workflows.

## Global Constraints

- Branch `protocol-fw` (off `sram-imem` at `a850747`). Agents never push, never merge, never touch `main` or `sram-imem`, never amend existing commits. One commit per task with the message shown; the controller commits when a second agent is running.
- `source /Users/baghel_family/Desktop/Untitled/jane_street_challenge/env.sh` in every shell (the worktree has no `env.sh` of its own; the project venv it activates is shared). Run every long command in the foreground with a time limit; never hand work to a background worker or wait on a notification. Write the task report incrementally to `.superpowers/sdd/pc-task-<N>-report.md` (git-ignored; create the directory if missing).
- No change to `src/`, `isa/`, `formal/`, `tools/sim.py`, `tools/host.py`, `tools/gen_isa.py`, `tools/isa_defs.py`. `tools/asm.py` changes only by the `constants()` helper of Task 1. `git diff sram-imem -- src isa formal tools/sim.py tools/host.py` must be empty at the end of every task.
- Pin map (spec §2): UART RX `ui[0]`; SPI SCK `uo[1]`, MOSI `uo[2]`, CS_n `uo[3]`, MISO `ui[1]`; I2C SDA `uio[0]`, SCL `uio[1]` (open drain: `uio_out` bit stays 0, `OE 1,mask` pulls low, `OE 0,mask` releases).
- Every firmware file: a header comment naming the clock (50 MHz) and the pins; then one `.equ` block holding `PRESCALE` (the `WRITE_PRESCALE` register value) and every timing constant, each with its formula in a comment; no numeric timing literal anywhere else in the file. Every wait is a `SETT`/`ADDT` relative deadline; after every `POP` of a host command the firmware re-anchors with `SETT`.
- Reference models and tests take timing from protocol parameters and `CLK_HZ = 50_000_000` declared at the top of the test module — never from the firmware's `.equ` values. The only `.equ` a test reads is `PRESCALE`, to program the host port.
- Model interface (all three): `step(uo, uio_out, uio_oe) -> (ui, uio_in)` where `uo` is the 7-bit output bank, `uio_out`/`uio_oe` the 8-bit banks as the chip drives them in the current cycle, `ui` the 4-bit protocol input value and `uio_in` the 8-bit value the chip's pins should show for the rest of that cycle; `violations` is a list of strings `"cycle <k>: <what>"`, empty when the master behaved; every model counts its own cycles from its first `step`. Idle input levels before the first step are all ones (`ui = 0x0F`, `uio_in = 0xFF`).
- Input latency convention (`test/test_diff.py`): levels driven in cycle k reach the core in cycle k+2. The oracle harness feeds the model's output two cycles late; the RTL harness drives the pins and the chip does the rest.
- Suites that must pass, warning-free, before every commit: `python -m pytest -q` (from the worktree root, after `source env.sh`); `make -C test -B -f Makefile.uartfw`; the suite(s) of the task; and at the end of Task 3 all seven cocotb suites and `python tools/gen_isa.py --check`. `make` exits 0 even when a cocotb test fails: read the `TESTS= PASS= FAIL=` line.
- Every new test is proven decisive: the task's mutant list is applied to a scratch copy of the firmware (never to the checkout; the sentinel test does it in-suite by editing the source text in memory), the suite must FAIL there and PASS on the real tree; record mutant, command and the decisive assertion line in the task report. The reviewer repeats at least three mutants independently.
- Host word formats are exactly those of spec §3–§5; results are pushed with `PUSH`, one per command (SPI, I2C) or per frame (UART).

---

## File structure

| Path | Responsibility |
|---|---|
| `tools/asm.py` | `constants(text) -> dict` (new): the `.equ` table of a source, nothing else changes |
| `tools/refmodels/__init__.py` | package marker (docstring only) |
| `tools/refmodels/uart_rx_ref.py` | `UartRxRef`: 8N1 line stimulus + receiver checker |
| `tools/refmodels/spi_slave_ref.py` | `SpiSlaveRef`: SPI slave + master-timing checker |
| `tools/refmodels/i2c_slave_ref.py` | `I2cSlaveRef`: I2C slave + standard-mode timing checker + wired-AND bus |
| `tests/fw_harness.py` | oracle harness: `load()`, `run_model()` |
| `tests/test_fw_uart_rx.py`, `tests/test_fw_spi.py`, `tests/test_fw_i2c.py` | oracle-level firmware tests; also hold the case tables the cocotb tests import |
| `tests/test_asm.py` | tests for `constants()` |
| `test/fw_harness.py` | RTL harness: `PinBus`, `HostPort`, `boot()`, `run_model()`, `drain()` |
| `test/test_uart_rx_fw.py`, `test/test_spi_fw.py`, `test/test_i2c_fw.py` | cocotb suites |
| `test/Makefile.uartrx`, `test/Makefile.spifw`, `test/Makefile.i2cfw` | one Makefile per suite (chip sources + `tb.v`) |
| `firmware/uart_rx.s`, `firmware/spi_master.s`, `firmware/i2c_master.s` | the firmware |
| `.github/workflows/test.yaml` | three new steps |
| `docs/info.md` | "Protocol firmware" section; `README.md`, `test/README.md`, `HANDOFF.md`, `PLAN.md` | status and suite lists |

---

### Task 1: Shared harnesses and the UART receiver

**Files:**
- Modify: `tools/asm.py` (add `constants`), `tests/test_asm.py`, `.github/workflows/test.yaml`, `docs/info.md`, `test/README.md`
- Create: `tools/refmodels/__init__.py`, `tools/refmodels/uart_rx_ref.py`, `tests/fw_harness.py`, `tests/test_fw_uart_rx.py`, `test/fw_harness.py`, `test/test_uart_rx_fw.py`, `test/Makefile.uartrx`, `firmware/uart_rx.s`

**Interfaces:**
- Consumes: `tools.asm.assemble`, `tools.sim.Sim(words, prescale=<divisor>, t0=)`, `tools.host.SpiMaster` and encoders, `test/tb.v` (top `tb`, signals `clk rst_n ena ui_in uio_in uo_out uio_out uio_oe`, instance `user_project`).
- Produces (Tasks 2 and 3 rely on these exact names):
  - `tools.asm.constants(text) -> dict[str, int]`: the `.equ` names and values of `text` (pass 1 only; raises `AsmError` on a malformed `.equ`).
  - `tests/fw_harness.py`: `FIRMWARE` (path), `load(name, text=None) -> (words, equs)`, `run_model(words, prescale_reg, model, cycles, host_words=(), host_at=None, t0=0xFF00) -> list[(cycle, word)]`.
  - `test/fw_harness.py`: `PinBus(dut)`, `HostPort(bus)` (a `SpiMaster` whose `_drive` writes through the bus, `half_period_ns=200`), `boot(dut, fw_name, fw_text=None) -> (bus, host, words)`, `run_model(dut, bus, model, cycles) -> list[(cycle, word)]`, `drain(host, out, stop)` coroutine, `host_push(host, word)`, `status(host) -> int`.

**Step 1 — `constants()` (test-first).** In `tests/test_asm.py` add:

```python
def test_constants_returns_the_equ_table():
    from tools.asm import constants
    assert constants(".equ A 5\n.equ B, 0x10\nlbl:\n  NOP\n") == {"A": 5, "B": 16}
    assert constants("NOP\n") == {}
```

Run `python -m pytest -q tests/test_asm.py -k constants` → FAIL (ImportError). Implement in `tools/asm.py` right after `assemble_file`:

```python
def constants(text):
    """The `.equ` table of `text` (name -> value), from pass 1 alone: lets a test read a firmware's
    declared assumptions (e.g. PRESCALE) without assembling it. Malformed `.equ` lines raise AsmError."""
    equs = {}
    for n, _label, op, args in _parse(text):
        if op != ".EQU": continue
        try:
            if len(args) == 1:
                parts = args[0].split()
                if len(parts) != 2: raise AsmError(".equ expects NAME VALUE or NAME, VALUE")
                equs[parts[0]] = _int(parts[1], ".equ value")
            elif len(args) == 2:
                equs[args[0].strip()] = _int(args[1], ".equ value")
            else:
                raise AsmError(".equ expects NAME VALUE or NAME, VALUE")
        except AsmError as e:
            raise AsmError("line %d: %s" % (n, e)) from None
    return equs
```

Then make `assemble`'s pass 1 call the same parsing (factor the `.equ` branch into a helper `_equ(args)` used by both, so the two cannot drift). Run the test → PASS; `python -m pytest -q` → all green.

**Step 2 — the reference model (test-first).** Create `tools/refmodels/__init__.py` (docstring: "Cycle-stepped protocol reference models, written from the protocol specifications; see docs/superpowers/specs/2026-10-16-protocol-firmware-design.md §2 for the step() contract."). Write `tools/refmodels/uart_rx_ref.py`:

```python
"""8N1 UART line stimulus and receiver checker, written from the frame definition (idle high; start
bit low; 8 data bits LSB first; stop bit high; every bit clk_hz / baud cycles long).

Tolerances (spec, not firmware): a frame's result must be pushed within
[stop sample - bit/8, stop sample + bit/8 + PUSH_SLACK] cycles, where the stop sample is the start
edge + 9.5 bits at the nominal baud rate; probe frames carry each data bit's value only within
+-bit/8 of its nominal sample instant and the complement elsewhere."""
PUSH_SLACK = 32

class Frame:
    def __init__(self, byte, baud_error=0.0, probe=False, stop_low=False, glitch=None, gap=None):
        # glitch: a low pulse of that many cycles instead of a frame (no word expected); gap: idle
        # cycles before the frame (default 2 bits); probe and baud_error are not combined.
        ...

class UartRxRef:
    def __init__(self, clk_hz, baud): ...
    def schedule(self, frames, lead_in=200):
        """Build the per-cycle line (self.line, list of 0/1) and self.expected: list of
        (word, first_ok_cycle, last_ok_cycle). word = byte | (0x100 if stop_low)."""
    @property
    def cycles(self): """len(self.line) + 4 bits of trailing idle"""
    def step(self, uo, uio_out, uio_oe):
        level = self.line[self.k] if self.k < len(self.line) else 1
        self.k += 1
        return (0x0E | level, 0xFF)
    def check(self, pushes):
        """Return a list of error strings (empty when `pushes`, a list of (cycle, word), equals the
        expectation: same count, same words in order, each cycle inside its window)."""
```

Bit boundaries are computed in floating point and converted with `int()` so a 434.03-cycle bit never drifts. Tests for the model itself, in `tests/test_fw_uart_rx.py` (they do not run firmware):

- `test_uart_ref_plain_frame_shape`: for `UartRxRef(50_000_000, 115200)` and one frame of 0x55 with `gap=0`, `lead_in=10`: the line is high for 10 cycles, then each of the ten bits (0,1,0,1,0,1,0,1,0,1) lasts 434 or 435 cycles, bit boundaries are at `int(10 + i * 434.027...)`; `expected == [(0x55, int(10 + 9.5*cpb) - 54, int(10 + 9.5*cpb) + 54 + 32)]` (54 = `int(434.03/8)`).
- `test_uart_ref_probe_frame_is_complement_outside_window`: for a probe frame of 0xFF, each data bit is 1 only within 54 cycles of its centre and 0 elsewhere; the start and stop bits are untouched.
- `test_uart_ref_check_rejects_wrong_word_count_value_and_time`: `check` returns `[]` for an exact push and one error each for a missing push, a wrong value, a push 1 cycle before `first_ok` and 1 cycle after `last_ok`.

Run these → FAIL (import error) → implement → PASS.

**Step 3 — the oracle harness.** Create `tests/fw_harness.py`:

```python
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

def run_model(words, prescale_reg, model, cycles, host_words=(), host_at=None, t0=0xFF00):
    """host_words[i] is pushed into the host->core FIFO at the first cycle >= host_at(i) (default 0)
    at which the FIFO has room. T starts at t0 (nonzero: deadlines cross the 16-bit wrap early)."""
    sim = Sim(words, prescale=prescale_reg + 1, t0=t0)
    lag = deque([IDLE, IDLE]); pending = list(host_words); i = 0; pushes = []
    for k in range(cycles):
        while pending and len(sim.host_to_core) < H2C_DEPTH and k >= (host_at(i) if host_at else 0):
            sim.host_to_core.append(pending.pop(0)); i += 1
        ui, uio = lag.popleft(); sim.set_inputs(ui=ui, uio_in=uio)
        _, uo, uio_out, uio_oe, _ = sim.step()
        while sim.core_to_host: pushes.append((k, sim.core_to_host.popleft()))
        lag.append(model.step(uo, uio_out, uio_oe))
    return pushes
```

**Step 4 — the firmware (oracle test first).** Add to `tests/test_fw_uart_rx.py` the case table and the oracle tests:

```python
CLK_HZ, BAUD = 50_000_000, 115200
CASES = {
    "nominal":   [Frame(0x55), Frame(0x00), Frame(0xFF), Frame(0xAA, gap=0), Frame(0xA3, gap=0)],
    "slow_4pct": [Frame(0x55, baud_error=-0.04), Frame(0xC3, baud_error=-0.04, gap=0)],
    "fast_4pct": [Frame(0x55, baud_error=+0.04), Frame(0xC3, baud_error=+0.04, gap=0)],
    "probe":     [Frame(0x55, probe=True), Frame(0xFF, probe=True, gap=0), Frame(0x00, probe=True), Frame(0x96, probe=True, gap=0)],
    "framing":   [Frame(0x12, stop_low=True), Frame(0x34)],
    "glitch":    [Frame(0, glitch=100), Frame(0x5A)],
    "long_idle": [Frame(0x01, gap=140_000), Frame(0x02)],   # 70,000 ticks: the 65,535-tick WAITP times out once and rearms
}
MUTANT_BIT = ("BIT      217", "BIT      210")   # the in-suite sentinel: 3 % fast -> probe frames must fail

def run_case(frames, text=None):
    words, equs = load("uart_rx.s", text)
    ref = UartRxRef(CLK_HZ, BAUD); ref.schedule(frames)
    pushes = run_model(words, equs["PRESCALE"], ref, ref.cycles)
    return ref.check(pushes), pushes

@pytest.mark.parametrize("name", sorted(CASES))
def test_uart_rx_firmware_matches_reference(name):
    errors, _ = run_case(CASES[name]); assert errors == [], errors

def test_uart_rx_sentinel_mutant_is_rejected():
    src = (FIRMWARE / "uart_rx.s").read_text(); assert MUTANT_BIT[0] in src
    errors, _ = run_case(CASES["probe"], src.replace(*MUTANT_BIT, 1)); assert errors, "the probe frames did not reject a 3 % fast BIT"
```

(`long_idle`'s 140,000-cycle gap is 70,000 ticks at prescale 2, past the 65,535-tick `WAITP` timeout: the start-edge wait times out once, rearms, and the next frame must still be received.) Run → FAIL (no firmware). Write `firmware/uart_rx.s` from this draft:

```
; 8N1 UART receiver at 115200 baud on ui[0]; each frame is pushed to the host as
; {frame_error[8], data[7:0]} through the core->host FIFO (PUSH; dropped if the host lets it fill).
; Computed for a 50 MHz clock. All timing lives in the .equ block below (one edit for 40 MHz).
.equ PRESCALE 1       ; WRITE_PRESCALE value the constants assume: one tick = PRESCALE+1 = 2 cycles
.equ BIT      217     ; ticks per bit  = 50e6 / 115200 / 2 = 217.0
.equ HALF     108     ; ticks from the detected start edge to the middle of the start bit = BIT / 2
  LDI  R5, 0x01       ; RX pin mask (ui[0])
  LDI  R6, 0x80       ; a received bit enters at bit 7; SHR moves earlier bits down (LSB first)
frame:
  WAITP UI, 0, FALL, R0   ; start edge; the 65,535-tick timeout just rearms the wait
  BTO  frame
  SETT R1, HALF           ; delay slot: R1 = middle of the start bit (harmless when rearming)
  WAITT R1
  IN   R4, UI
  AND  R4, R5             ; Z: still low -> a real start bit
  BNZ  frame              ; high again: a glitch
  LDI  R3, 8              ; delay slot: data bit counter (the branch already decided on AND's Z)
  LDI  R2, 0
bit:
  ADDT R1, BIT            ; next sample instant: edge + 1.5, 2.5, ... 8.5 bits
  WAITT R1
  IN   R4, UI
  AND  R4, R5             ; R4 = 0 or 1
  LDI  R7, 0
  SUB  R7, R4             ; R7 = 0x0000 or 0xFFFF
  AND  R7, R6             ; R7 = 0x00 or 0x80
  SHR  R2
  OR   R2, R7
  ADDI R3, -1
  BNZ  bit
  NOP
  ADDT R1, BIT            ; middle of the stop bit
  WAITT R1
  IN   R4, UI
  AND  R4, R5             ; Z: stop bit low -> framing error
  BNZ  push
  NOP
  LDIH R2, 0x01           ; result bit 8
push:
  PUSH R2
  JMP  frame
  NOP
```

Run the oracle tests → PASS (fix the draft if a case fails and record what changed). Also check `python tools/asm.py firmware/uart_rx.s | wc -l` and note the word count for the datasheet.

**Step 5 — the RTL harness.** Create `test/fw_harness.py`:

```python
"""Shared cocotb harness for the protocol-firmware suites: the full chip (test/tb.v) through its
Tiny Tapeout pins. The host SPI port and the protocol inputs share ui_in, so PinBus owns that
register and merges the two writers; the model loop runs one reference-model step per falling
clock edge and records the core->host pushes from the core's push strobe (RTL only); drain()
keeps reading words back through POP_FIFO so the 4-entry FIFO never drops a push and every test
covers the real host path."""
import os
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge
from tools.asm import assemble, constants
from tools.host import (SpiMaster, encode_write_imem, encode_write_ctrl, encode_write_prescale,
                        CMD_PUSH_FIFO, CMD_POP_FIFO, CMD_READ_STATUS)

FIRMWARE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firmware")
HOST_IDLE = 0x40                       # CS_n high, SCK/MOSI low, RUN low

class PinBus:
    def __init__(self, dut): self.dut, self.host, self.proto = dut, HOST_IDLE, 0x0F
    def apply(self): self.dut.ui_in.value = (self.host & 0x70) | (self.proto & 0x0F)

class HostPort(SpiMaster):
    """SpiMaster that writes the three host lines through the PinBus (half period 200 ns: SCK at
    clk/20, within the port's clk/16 limit), leaving ui[3:0] to the model loop."""
    def __init__(self, bus): self.bus = bus; super().__init__(bus.dut, half_period_ns=200)
    def _drive(self, sck, mosi, cs_n): self.bus.host = (sck << 4) | (mosi << 5) | (cs_n << 6); self.bus.apply()

def firmware_text(name): return open(os.path.join(FIRMWARE, name)).read()

async def boot(dut, fw_name, fw_text=None):
    """Clock, reset, PRESCALE from the firmware's own .equ, load over WRITE_IMEM, WRITE_CTRL run."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    text = fw_text if fw_text is not None else firmware_text(fw_name)
    words, prescale = assemble(text), constants(text)["PRESCALE"]
    bus = PinBus(dut); dut.ena.value = 1; dut.uio_in.value = 0xFF; bus.apply()
    dut.rst_n.value = 0; await ClockCycles(dut.clk, 3); dut.rst_n.value = 1; await ClockCycles(dut.clk, 2)
    host = HostPort(bus)
    await host.xfer(encode_write_prescale(prescale))
    await host.xfer(encode_write_imem(0, words))
    await host.xfer(encode_write_ctrl(run=True))
    return bus, host, words

async def run_model(dut, bus, model, cycles):
    core = dut.user_project.u_core; pushes = []
    for k in range(cycles):
        await FallingEdge(dut.clk)
        if int(core.c2h_push.value): pushes.append((k, int(core.c2h_data.value)))
        ui, uio_in = model.step(int(dut.uo_out.value) & 0x7F, int(dut.uio_out.value), int(dut.uio_oe.value))
        bus.proto = ui; bus.apply(); dut.uio_in.value = uio_in
    return pushes

async def status(host):
    return (await host.xfer(bytes([CMD_READ_STATUS, 0, 0, 0, 0])))[1]

async def host_push(host, word):
    while (await status(host)) & 0x10: pass            # h2c full: poll
    await host.xfer(bytes([CMD_PUSH_FIFO, (word >> 8) & 0xFF, word & 0xFF]))

async def drain(host, out, stop):
    """Pop every core->host word into `out` until stop() is true (and the FIFO is empty)."""
    while True:
        st = await status(host)
        if not st & 0x08:
            r = await host.xfer(bytes([CMD_POP_FIFO, 0, 0])); out.append((r[1] << 8) | r[2])
        elif stop(): return
```

(`c2h_push` is `active && HOST && !pop && !c2h_full`, so the monitor records accepted pushes only — the drain exists so that nothing is ever dropped; a test whose drained list is shorter than the monitored one has found a drop.)

**Step 6 — the cocotb suite.** Create `test/Makefile.uartrx` by copying `test/Makefile.uartfw` and changing: the header comment (this suite: `firmware/uart_rx.s` on the chip against `tools/refmodels/uart_rx_ref.py`, no Verilog reference), `VERILOG_SOURCES += $(PWD)/tb.v` (no `uart_tx_ref.v`), `TOPLEVEL = tb`, `COCOTB_TEST_MODULES = test_uart_rx_fw`. Write `test/test_uart_rx_fw.py`:

```python
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
    test.__name__ = "uart_rx_" + name; return cocotb.test()(test)

for _name in sorted(CASES): globals()["test_" + _name] = make_test(_name)

@cocotb.test()
async def uart_rx_sentinel_mutant_is_rejected(dut):
    src = firmware_text("uart_rx.s"); assert MUTANT_BIT[0] in src
    errors, _, _ = await run_case(dut, CASES["probe"], src.replace(*MUTANT_BIT, 1))
    assert errors, "the reference accepted a 3 % fast BIT"
```

Run `make -C test -B -f Makefile.uartrx` → `TESTS=8 PASS=8 FAIL=0`, no warnings; record the wall-clock. Then `make -C test -B -f Makefile.uartfw` still 1/1 and `python -m pytest -q` all green.

**Step 7 — mutants (scratch copy of `firmware/uart_rx.s`; each must FAIL at least one oracle test and the cocotb suite; U1 is the in-suite sentinel):** U1 `BIT 210`; U2 `HALF 160` (samples at 74 % of each bit: probe must fail, nominal may pass); U3 false-start check removed (`BNZ frame` → `NOP`: the glitch case must fail); U4 bit order (`LDI R6, 0x01` and `SHL R2` in place of `SHR R2`: nominal fails on 0xA3); U5 framing flag never set (`LDIH R2, 0x01` → `NOP`: framing fails); U6 `PRESCALE 0` (everything twice as fast: nominal fails); U7 stop sampled at `+HALF` (`ADDT R1, BIT` → `ADDT R1, HALF` before the stop read: nominal fails on a byte with d7 = 0). Record which test kills each.

**Step 8 — CI and docs.** In `.github/workflows/test.yaml` add after the UART equivalence step:

```yaml
      - name: UART RX firmware vs reference receiver (test/Makefile.uartrx)
        run: |
          cd test
          COCOTB_RESULTS_FILE=results_uartrx.xml make -B -f Makefile.uartrx
          ! grep failure results_uartrx.xml
```

`docs/info.md`: add a section `## Protocol firmware` before `## How to test` with: the pin-map table of spec §2; the paragraph on timing constants (`.equ` block per file, `PRESCALE` read by the tests, `CLK_HZ` in the tests; one edit per file for 40 MHz); a subsection `### UART receiver (firmware/uart_rx.s)` giving the constants, the result word, what the reference model checks (frame timing window, probe frames, ±4 % baud, framing, glitch rejection), the suite (`test/Makefile.uartrx`, test names) and the firmware size in words. `test/README.md`: add the suite to the list (now five). Keep `README.md` for Task 4.

**Step 9 — verify and commit.** `git diff sram-imem -- src isa formal tools/sim.py tools/host.py` empty; `python tools/gen_isa.py --check`; pytest; the three suites named above. Commit:

```bash
git add tools/asm.py tests/test_asm.py tools/refmodels tests/fw_harness.py tests/test_fw_uart_rx.py test/fw_harness.py test/test_uart_rx_fw.py test/Makefile.uartrx firmware/uart_rx.s .github/workflows/test.yaml docs/info.md test/README.md
git commit -m "feat(fw): UART receiver firmware with an 8N1 reference checker on the oracle and the chip RTL; shared firmware harnesses"
```

---

### Task 2: SPI master, modes 0–3

**Files:**
- Create: `tools/refmodels/spi_slave_ref.py`, `tests/test_fw_spi.py`, `test/test_spi_fw.py`, `test/Makefile.spifw`, `firmware/spi_master.s`
- Modify: `.github/workflows/test.yaml`, `docs/info.md`, `test/README.md`

**Interfaces:**
- Consumes: Task 1's `tests/fw_harness.py` (`load`, `run_model(words, prescale_reg, model, cycles, host_words, host_at)`), `test/fw_harness.py` (`boot`, `run_model`, `drain`, `host_push`, `firmware_text`).
- Produces: `SpiSlaveRef(clk_hz, sck_hz, mode, miso_bytes, miso_window=None, t_co=5)` with `step`, `violations`, `mosi_bytes`, `transactions` (list of `{"cs_fall": k, "cs_rise": k, "edges": n}`), `miso_expected` (the MISO bytes consumed so far); command/result word helpers `spi_cmd(byte, mode, last=False) -> int`.

**Step 1 — model (test-first).** Write `tools/refmodels/spi_slave_ref.py`:

```python
"""SPI slave and master checker, written from the mode definitions (CPOL = idle SCK level; the
leading edge is the edge away from idle; CPHA=0 samples on the leading edge and shifts on the
trailing one with the first bit set up before the first edge; CPHA=1 shifts on the leading edge and
samples on the trailing one). MSB first, 8 bits per byte, CS_n low for a whole transaction.

Pins: SCK uo[1], MOSI uo[2], CS_n uo[3]; MISO is returned on ui[1].
Tolerances (from the nominal period P = clk_hz / sck_hz, H = P // 2; never from the firmware):
  - while CS_n is high (from the first time it is seen high; uo resets low) SCK changes level at most
    once -- the switch to the next transaction's CPOL -- and it must equal the transaction's CPOL at
    CS_n's fall, between the bytes of the transaction and at CS_n's rise;
  - first edge >= H - 2 cycles after CS_n falls and in the leading direction; last edge >= H - 2 before CS_n rises;
  - edge-to-edge within a byte: H +- 1 cycles; between bytes >= H - 1 with SCK idle;
  - MOSI unchanged from P // 4 cycles before each sampling edge to P // 4 after it;
  - a transaction holds a multiple of 16 edges.
MISO: each bit valid t_co cycles after its shifting edge (CPHA=0: the first bit t_co after CS_n
falls) and held to the next shifting edge; with miso_window = w the bit is valid only within +-w
cycles of the predicted sampling edge (previous edge + H) and the complement elsewhere -- the first
bit of a CPHA=0 transaction is driven plainly."""
```

Class skeleton: `__init__` stores parameters, `self.k = 0`, `self.violations = []`, `self.mosi_bytes = []`, `self.transactions = []`, `self.miso_expected = []`, previous-cycle `cs_n`, `sck`, `mosi` (initial `cs_n = 1`? No: `uo` resets to 0, so start with `seen_high = False` and take the first cycle with `cs_n == 1` as the start of checking), `last_mosi_change`, a list of pending MOSI-stability checks `(sample_edge_cycle)` resolved at `sample_edge + P//4`. `step()`: decode pins, detect edges, run the checks, update MISO (an integer level) and return `((miso << 1) | 0x0D, 0xFF)`. Violations are strings `"cycle %d: ..."`.

Model tests in `tests/test_fw_spi.py` (synthetic master traces, no firmware): drive the model with a hand-made perfect mode-0 and mode-3 waveform generator (`perfect_master(mode, bytes, P)` yielding `uo` values per cycle) and assert `violations == []`, `mosi_bytes` correct, and that the MISO levels returned equal the expected bits at the sampling edges; then three broken traces — an edge 3 cycles late (interval violation), MOSI changed 2 cycles before a sampling edge (stability violation), SCK high while CS_n high in mode 0 (idle violation) — each produce exactly one violation mentioning the cycle.

**Step 2 — command helpers and case table** (in `tests/test_fw_spi.py`):

```python
CLK_HZ, SCK_HZ = 50_000_000, 1_000_000
def spi_cmd(byte, mode, last=False): return byte | (0x100 if last else 0) | (mode << 9)
TX = [0x81, 0x3C, 0xA5]; RX = [0xC3, 0x0F, 0x96]
def case(modes, txs, miso, window=True, at=None):
    return {"modes": modes, "txs": txs, "miso": miso, "window": window, "at": at}
CASES = {  # modes: one per transaction; txs: the bytes of each transaction; at: cycle from which word i may be pushed
    "mode0": case([0], [TX], RX), "mode1": case([1], [TX], RX), "mode2": case([2], [TX], RX), "mode3": case([3], [TX], RX),
    "mode_change": case([0, 3], [[0x55], [0xAA, 0x01]], [0x12, 0x34, 0x56], window=False),
    "single_byte": case([2], [[0x80]], [0x01]),
    "late_words": case([0], [TX], RX, at=[0, 3000, 6000]),      # gaps between bytes longer than a byte
}
MUTANT_HALF = ("HALF     25", "HALF     27")
```

For each transaction the host words are `[spi_cmd(b, mode, last=(i == len(tx)-1)) for i, b in enumerate(tx)]`; the expected results are the MISO bytes in order. `at` is passed to the oracle harness as `host_at=lambda i: at[i]` and, in the RTL harness, as `await ClockCycles(dut.clk, at[i] - at[i-1])` between `host_push` calls.

**Step 3 — firmware (oracle test first).** Oracle test:

```python
def run_case(name, text=None):
    c = CASES[name]; modes, txs, miso, at = c["modes"], c["txs"], c["miso"], c["at"]
    words, equs = load("spi_master.s", text)
    P = CLK_HZ // SCK_HZ
    ref = SpiSlaveRef(CLK_HZ, SCK_HZ, modes, miso, miso_window=P // 8 if c["window"] else None)
    host = [spi_cmd(b, m, last=(i == len(tx) - 1)) for m, tx in zip(modes, txs) for i, b in enumerate(tx)]
    cycles = 400 * (len(host) + 2) + 2000 + (at[-1] if at else 0)
    pushes = run_model(words, equs["PRESCALE"], ref, cycles, host_words=host, host_at=(lambda i: at[i]) if at else None)
    return ref, pushes
```

(`SpiSlaveRef` takes `mode` as an int or a list of per-transaction modes; with a list, transaction `j` is checked against `mode[j]`.) Assertions: `ref.violations == []`; `[w for _, w in pushes] == miso[:len(host)]`; `ref.mosi_bytes == [b for tx in txs for b in tx]`; `len(ref.transactions) == len(txs)`. Sentinel test: `MUTANT_HALF` applied to `"mode0"` → `ref.violations` non-empty. Then write `firmware/spi_master.s` from this draft:

```
; SPI master, modes 0-3: SCK uo[1], MOSI uo[2], CS_n uo[3], MISO ui[1]. Bytes come from the host
; FIFO: command {CPOL[10], CPHA[9], LAST[8], byte[7:0]}; one result {miso[7:0]} per command.
; CPOL is applied when a transaction starts; CPHA is read from every word. Computed for 50 MHz.
.equ PRESCALE 0       ; one tick = one cycle
.equ HALF     25      ; ticks per SCK half period = 50e6 / 1e6 / 2
.equ CSLEAD   25      ; CS_n low -> first SCK edge   (>= HALF)
.equ CSLAG    25      ; last SCK edge -> CS_n high   (>= HALF)
.equ CSIDLE   25      ; CS_n high between transactions
  SET  UO, 0x08       ; CS_n idle high (uo resets to 0)
  LDI  R6, 0x02       ; MISO mask (ui[1])
idle:
  WAITF RXV, R0
  BTO  idle
  NOP
  POP  R2             ; first command of a transaction
  SETT R1, CSLEAD     ; first half-step
  LDI  R4, 0x00
  LDIH R4, 0x04       ; CPOL mask
  BITT R2, R4
  BNZ  cpol1
  NOP
  CLR  UO, 0x02       ; CPOL = 0: SCK idle low
  JMP  cs
  NOP
cpol1:
  SET  UO, 0x02       ; CPOL = 1: SCK idle high (one level change while CS_n is high, no glitch)
cs:
  CLR  UO, 0x08       ; CS_n low: transaction starts
byte:                 ; R2 = command, R1 = this byte's first half-step
  LDI  R7, 0x00
  LDIH R7, 0x03
  AND  R7, R2         ; R7 = command & {CPHA, LAST}
  LDI  R4, 0x00
  LDIH R4, 0x02       ; CPHA mask
  LDI  R5, 8          ; bit counter
  LDI  R3, 0          ; MISO accumulator
  BITT R7, R4         ; Z: CPHA = 0
  BZ   mosi           ; CPHA = 0: the first bit is set up with no edge
  WAITT R1            ; delay slot: wait for the first half-step either way
bitloop:
  WAITT R1
  TGL  UO, 0x02       ; shifting edge (CPHA = 1: leading; CPHA = 0: the previous bit's trailing edge)
mosi:
  SETR UO, 2, R2, 7   ; MOSI = bit 7
  SHL  R2
  ADDT R1, HALF
  WAITT R1
  TGL  UO, 0x02       ; sampling edge
  IN   R4, UI         ; synchronised MISO (its level about two cycles before the edge)
  AND  R4, R6
  SHR  R4             ; -> bit 0
  SHL  R3
  OR   R3, R4
  ADDT R1, HALF
  ADDI R5, -1
  BNZ  bitloop
  NOP
  LDI  R4, 0x00
  LDIH R4, 0x02
  BITT R7, R4         ; Z: CPHA = 0
  BNZ  pushr          ; CPHA = 1: SCK is idle after the last sampling edge
  NOP
  WAITT R1
  TGL  UO, 0x02       ; CPHA = 0: trailing edge of the last bit, back to idle
pushr:
  WAITF TXE, R0
  PUSH R3
  LDIH R4, 0x01       ; LAST mask (low byte of R4 is 0)
  BITT R7, R4
  BNZ  last
  NOP
next:
  WAITF RXV, R0       ; next byte of the transaction, SCK idle meanwhile
  BTO  next
  NOP
  POP  R2
  SETT R1, HALF       ; re-anchor: a slow host never leaves a deadline far behind
  JMP  byte
  NOP
last:
  ADDT R1, CSLAG
  WAITT R1
  SET  UO, 0x08       ; CS_n high
  ADDT R1, CSIDLE
  WAITT R1
  JMP  idle
  NOP
```

Oracle tests → PASS (fix the draft if needed and record it). Check every edge-to-edge interval the model saw is exactly `H` (print `ref.transactions` in the report): the draft places both `TGL`s one instruction after their `WAITT`, so the intervals must be equal; a 24/26 alternation means the loop structure was changed.

**Step 4 — cocotb suite.** `test/Makefile.spifw` (copy of `Makefile.uartrx` with `COCOTB_TEST_MODULES = test_spi_fw` and its header). `test/test_spi_fw.py` mirrors the oracle test: `boot(dut, "spi_master.s", fw_text)`, build the model, `cocotb.start_soon(run_model(...))` for the same cycle budget as the oracle, push the host words with `host_push` (for `late_words`, `await ClockCycles(dut.clk, 3000)` between them), start `drain`, await the model task, then the same four assertions plus `drained == [w for _, w in pushes]`. One generated test per case (the `make_test` pattern of Task 1) plus `spi_sentinel_mutant_is_rejected` (`MUTANT_HALF` on `"mode0"`: `ref.violations` non-empty). Expected: `TESTS=8 PASS=8 FAIL=0`.

**Step 5 — mutants (scratch copies):** S1 `HALF 27` (sentinel); S2 CPHA and CPOL masks swapped (`LDIH R4, 0x04` ↔ `0x02` in the two places and `0x03` kept: modes 1 and 2 must fail — MISO window or MOSI stability); S3 CPOL ignored (`SET UO, 0x02` → `NOP`: modes 2 and 3 fail the idle check); S4 LSB first (`SETR UO, 2, R2, 0` + `SHR R2`: `mosi_bytes` wrong); S5 `CSLEAD 2` (lead violation); S6 MISO sampled on the shifting edge (move `IN R4, UI` to just after the first `TGL`: window fails); S7 final CPHA=0 toggle removed (`TGL` after `WAITT R1` → `NOP`: SCK not idle at CS_n's rise in modes 0 and 2). Record the killing test per mutant.

**Step 6 — CI, docs, commit.** `test.yaml` step `SPI master firmware vs reference slave (test/Makefile.spifw)` with `results_spifw.xml`; `docs/info.md` subsection `### SPI master (firmware/spi_master.s)`: constants, the command and result words, mode table (CPOL/CPHA edges), what the model checks (idle level, lead/lag, intervals, MOSI setup/hold, MISO window), suite and test names, firmware size; `test/README.md`. Verify as in Task 1 Step 9 (plus `Makefile.uartrx`). Commit:

```bash
git add tools/refmodels/spi_slave_ref.py tests/test_fw_spi.py test/test_spi_fw.py test/Makefile.spifw firmware/spi_master.s .github/workflows/test.yaml docs/info.md test/README.md
git commit -m "feat(fw): SPI master firmware, modes 0-3, with a reference slave that checks phase, polarity, bit order and edge timing"
```

---

### Task 3: I2C master

**Files:**
- Create: `tools/refmodels/i2c_slave_ref.py`, `tests/test_fw_i2c.py`, `test/test_i2c_fw.py`, `test/Makefile.i2cfw`, `firmware/i2c_master.s`
- Modify: `.github/workflows/test.yaml`, `docs/info.md`, `test/README.md`

**Interfaces:**
- Consumes: Task 1's harnesses (as Task 2).
- Produces: `I2cSlaveRef(clk_hz, address, read_data=(), nack_data_after=None, stretch_after_byte=None)` with `step`, `violations`, `written` (bytes received), `events` (list of `("START", k)`, `("STOP", k)`, `("BYTE", k, value, acked, "W"|"R")`); helpers `i2c_cmd(data=0, start=False, stop=False, read=False, nack=False) -> int` and the result bits `NACK = 0x100, TIMEOUT = 0x200, STRETCHED = 0x400`.

**Step 1 — model (test-first).** `tools/refmodels/i2c_slave_ref.py`:

```python
"""I2C slave and master checker for standard mode, written from the bus definition (UM10204):
START = SDA falls while SCL high, STOP = SDA rises while SCL high, data sampled on SCL's rising
edge and stable while SCL is high, nine bits per byte (eight data MSB first, then ACK = SDA low).
The model computes the wired-AND bus from the master's pull-downs (uio_oe & ~uio_out, bits 0 = SDA
and 1 = SCL) and its own, and returns the bus levels as the chip's uio_in (other bits 1).

Standard-mode limits checked on the bus, in cycles from clk_hz (never from the firmware):
  period (rise to rise) >= 10.0 us; tLOW >= 4.7 us; tHIGH >= 4.0 us; tSU;STA >= 4.7 us (SDA and SCL
  both high before SDA falls); tHD;STA >= 4.0 us (SDA low before SCL falls); tSU;DAT >= 250 ns;
  tHD;DAT <= 3.45 us within a byte (the master may hold SCL low for longer between commands, which
  is master-side stretching and exempt); tSU;STO >= 4.0 us; tBUF >= 4.7 us; any other SDA change
  while SCL is high is a violation.
Slave: ACKs its own address (either direction), NACKs others; stores written bytes; serves
read_data on reads, changing SDA T_SLAVE = 5 cycles after SCL falls, and stops after the master's
NACK; nack_data_after = n NACKs the n-th written data byte; stretch_after_byte = (k, cycles) holds
SCL low for `cycles` after the ACK bit of byte k (0 = the address byte) -- longer than the master's
65,535-tick timeout is the timeout case; the slave then lets go and keeps listening for a START."""
```

Model tests in `tests/test_fw_i2c.py` with a hand-written perfect master generator (quarter period 125 cycles; START, one address byte, one data byte, STOP) — `violations == []`, `written == [data]`, events in order — and broken traces: tHIGH 150 cycles (violation), SDA changed while SCL high mid-byte (violation), STOP with SDA released 50 cycles after SCL rise (tSU;STO violation).

**Step 2 — helpers and case table** (in `tests/test_fw_i2c.py`):

```python
CLK_HZ = 50_000_000
NACK, TIMEOUT, STRETCHED = 0x100, 0x200, 0x400
def i2c_cmd(data=0, start=False, stop=False, read=False, nack=False):
    """Command word: data[7:0] (for a read: bit 0 = 1 answers with NACK), START[8], STOP[9], READ[10]."""
    return (1 if (read and nack) else data & 0xFF) | (0x100 if start else 0) | (0x200 if stop else 0) | (0x400 if read else 0)
ADDR = 0x50
def wr(addr): return (addr << 1) | 0
def rd(addr): return (addr << 1) | 1
def case(slave, words, expect, at=None):
    return {"slave": slave, "words": words, "expect": expect, "at": at}
CASES = {  # slave: I2cSlaveRef kwargs; words: host commands; expect: result words; at: cycle from which word i may be pushed
    "write2": case({}, [i2c_cmd(wr(ADDR), start=True), i2c_cmd(0xA5), i2c_cmd(0x3C, stop=True)], [wr(ADDR), 0xA5, 0x3C]),
    "read2":  case({"read_data": [0x11, 0x22]}, [i2c_cmd(rd(ADDR), start=True), i2c_cmd(read=True), i2c_cmd(read=True, nack=True, stop=True)], [rd(ADDR), 0x11, 0x22]),
    "write_restart_read": case({"read_data": [0x7E]}, [i2c_cmd(wr(ADDR), start=True), i2c_cmd(0x10), i2c_cmd(rd(ADDR), start=True), i2c_cmd(read=True, nack=True, stop=True)], [wr(ADDR), 0x10, rd(ADDR), 0x7E]),
    "addr_nack": case({}, [i2c_cmd(wr(0x51), start=True, stop=True)], [wr(0x51) | NACK]),
    "data_nack": case({"nack_data_after": 1}, [i2c_cmd(wr(ADDR), start=True), i2c_cmd(0x01), i2c_cmd(0x02, stop=True)], [wr(ADDR), 0x01 | NACK, 0x02 | NACK]),
    "stretch": case({"stretch_after_byte": (0, 1000)}, [i2c_cmd(wr(ADDR), start=True), i2c_cmd(0x5A, stop=True)], [wr(ADDR), 0x5A | STRETCHED]),
    "timeout": case({"stretch_after_byte": (0, 80_000)}, [i2c_cmd(wr(ADDR), start=True), i2c_cmd(0x5A, stop=True), i2c_cmd(wr(ADDR), start=True, stop=True)],
                    [wr(ADDR), 0x5A | TIMEOUT, wr(ADDR)], at=[0, 0, 90_000]),
}
MUTANT_Q = ("Q        128", "Q        96")
```

(`data_nack` with `nack_data_after=1`: the slave NACKs the first data byte and every later one — state it in the model docstring. In `stretch`, the stretch of 1,000 cycles starts when SCL falls after the address ACK, so it is the next command's first `scl_hi` that sees it: STRETCHED lands on `0x5A`'s result. In `timeout`, the master gives up during `0x5A`'s first bit, releases both lines and skips the STOP; the slave releases SCL at 80,000 cycles; the third command is pushed only at 90,000 cycles — a host retrying after the slave let go — and its START must succeed, be ACKed and carry no STRETCHED bit. Pushing it earlier would be legal too, but its START would then wait on the still-held SCL and report STRETCHED, which is not what this case is about.) Cycle budgets: 6,000 cycles per command, plus 100,000 for `timeout`.

**Step 3 — firmware (oracle test first).** Oracle test: `run_model(words, equs["PRESCALE"], ref, cycles, host_words=host)`; assert `ref.violations == []`, `[w for _, w in pushes] == expected`, and per case the slave side: `write2` → `written == [0xA5, 0x3C]` and events START, 3 BYTEs, STOP; `read2` → events include two "R" bytes with the second not acked; `write_restart_read` → two STARTs, one STOP. Sentinel: `MUTANT_Q` on `write2` → violations. Then write `firmware/i2c_master.s` from this draft:

```
; I2C master, standard mode: SDA uio[0], SCL uio[1], open drain (uio_out bits stay 0; OE set pulls
; low, OE clear releases). Commands from the host FIFO: {READ[10], STOP[9], START[8], data[7:0]}
; (for a read, data bit 0 = 1 answers the byte with NACK). One result per command:
; {STRETCHED[10], TIMEOUT[9], NACK[8], data[7:0]}. Computed for 50 MHz; the quarter-period grid
; below gives tLOW = tHIGH = 2Q = 5.12 us, tSU;STA = tHD;STA = tSU;STO = tBUF = 2Q, tHD;DAT = tSU;DAT = Q.
.equ PRESCALE 0       ; one tick = one cycle
.equ Q        128     ; quarter of the SCL period in ticks = ceil(50e6 / 100e3 / 4) + 3 (period 10.24 us, under 100 kHz)
main:
  WAITF RXV, R0
  BTO  main
  NOP
  POP  R2             ; command
  SETT R1, 0          ; the quarter-period grid starts now
  LDI  R6, 0          ; status bits
  LDI  R4, 0x00
  LDIH R4, 0x01       ; START
  BITT R2, R4
  BZ   nostart
  NOP
  CALL start
  NOP
nostart:
  LDIH R4, 0x04       ; READ
  BITT R2, R4
  BZ   write
  NOP
  CALL rbyte          ; R3 = byte read, then the ACK bit from command bit 0
  NOP
  JMP  stopq
  NOP
write:
  CALL wbyte          ; writes command[7:0]; R3 = echo; R6 |= NACK
  NOP
stopq:
  LDI  R4, 0x00
  LDIH R4, 0x02       ; STOP
  BITT R2, R4
  BZ   result
  NOP
  CALL stop
  NOP
result:
  OR   R3, R6
  WAITF TXE, R0
  PUSH R3
  JMP  main
  NOP
abort:                ; SCL held low past the timeout: release both lines, report, drop the command
  OE   0, 0x03
  LDI  R4, 0x00
  LDIH R4, 0x02       ; TIMEOUT
  OR   R6, R4
  JMP  result
  NOP
scl_hi:               ; release SCL, flag a stretch, wait for SCL high, R1 = the rise
  OE   0, 0x02
  DELAY 3             ; released level reaches the synchronised input 3 cycles after the OE; read it 5 after
  BPIN UIO, 1, 1, sclok
  NOP
  LDI  R4, 0x00
  LDIH R4, 0x04       ; STRETCHED
  OR   R6, R4
sclok:
  WAITP UIO, 1, HIGH, R0
  BTO  abort
  SETT R1, 0          ; delay slot: the high period counts from the observed rise
  RET
  NOP
wbit:                 ; SDA from Z (Z: pull low; else release), one SCL pulse; R1 = last SCL fall
  ADDT R1, Q
  WAITT R1
  BZ   sda0
  NOP
  OE   0, 0x01        ; SDA released (1)
  JMP  wbit2
  NOP
sda0:
  OE   1, 0x01        ; SDA low (0)
wbit2:
  ADDT R1, Q
  WAITT R1
  CALL scl_hi
  NOP
  ADDT R1, Q
  ADDT R1, Q
  WAITT R1
  OE   1, 0x02        ; SCL low
  RET
  NOP
rbit:                 ; release SDA, one SCL pulse, C = SDA in the middle of the high period
  ADDT R1, Q
  WAITT R1
  OE   0, 0x01
  ADDT R1, Q
  WAITT R1
  CALL scl_hi
  NOP
  ADDT R1, Q
  WAITT R1
  IN   R4, UIO
  SHR  R4             ; C = SDA
  ADDT R1, Q
  WAITT R1
  OE   1, 0x02        ; SCL low (flags untouched from here to the RET)
  RET
  NOP
wbyte:                ; write command[7:0] MSB first, read the ACK
  LDI  R3, 0xFF
  AND  R3, R2         ; R3 = data (the echo)
  MOV  R7, R3         ; shifting copy
  LDI  R5, 8
wloop:
  LDI  R4, 0x80
  BITT R7, R4         ; Z: bit 7 clear -> SDA low
  CALL wbit
  NOP                 ; (the slot must not touch the flags wbit reads)
  SHL  R7
  ADDI R5, -1
  BNZ  wloop
  NOP
  CALL rbit           ; ACK bit -> C
  NOP
  BNC  wret
  NOP
  LDI  R4, 0x00
  LDIH R4, 0x01       ; NACK
  OR   R6, R4
wret:
  RET
  NOP
rbyte:                ; R3 = byte read MSB first; then the ACK bit from command bit 0 (1 = NACK)
  LDI  R3, 0
  LDI  R5, 8
rloop:
  CALL rbit
  NOP
  BC   rone
  SHL  R3             ; delay slot: shift either way (the branch decided on rbit's C)
  JMP  rnext
  NOP
rone:
  ADDI R3, 1
rnext:
  ADDI R5, -1
  BNZ  rloop
  NOP
  LDI  R4, 0x01
  BITT R2, R4         ; Z: ACK requested -> wbit pulls SDA low
  CALL wbit
  NOP
  RET
  NOP
start:                ; (repeated) START: SDA high, SCL high, SDA low after 2Q, SCL low after 2Q
  ADDT R1, Q
  WAITT R1
  OE   0, 0x01
  ADDT R1, Q
  WAITT R1
  CALL scl_hi
  NOP
  ADDT R1, Q
  ADDT R1, Q
  WAITT R1
  OE   1, 0x01        ; SDA falls while SCL is high
  ADDT R1, Q
  ADDT R1, Q
  WAITT R1
  OE   1, 0x02
  RET
  NOP
stop:                 ; STOP: SDA low, SCL high, SDA released after 2Q, then tBUF
  ADDT R1, Q
  WAITT R1
  OE   1, 0x01
  ADDT R1, Q
  WAITT R1
  CALL scl_hi
  NOP
  ADDT R1, Q
  ADDT R1, Q
  WAITT R1
  OE   0, 0x01        ; SDA rises while SCL is high
  ADDT R1, Q
  ADDT R1, Q
  WAITT R1
  RET
  NOP
```

Notes the implementer must keep: `abort` is reached by a `BTO` from inside nested calls and never returns — the abandoned return addresses are harmless (the stack keeps the four most recent entries and the next `CALL`s overwrite them); the deepest live nesting is main → wbyte → wbit → scl_hi (4 entries, the stack's size) so no live entry is ever dropped. The branch range of `BTO abort` from `scl_hi` is well within ±255 words as laid out above. Oracle tests → PASS; record the word count.

**Step 4 — cocotb suite.** `test/Makefile.i2cfw` (`COCOTB_TEST_MODULES = test_i2c_fw`), `test/test_i2c_fw.py` mirroring the oracle test with `host_push` for the words, `drain`, the same assertions, one generated test per case plus `i2c_sentinel_mutant_is_rejected`. Expected `TESTS=8 PASS=8 FAIL=0`; the `timeout` case is the slow one (about 90,000 cycles).

**Step 5 — mutants (scratch copies):** I1 `Q 96` (sentinel: tLOW/tHIGH/period); I2 data set after the SCL release (in `wbit` move the SDA `OE` block to after `CALL scl_hi`: SDA changes while SCL high → START/STOP violation and wrong bytes); I3 tHD;STA removed (delete the two `ADDT R1, Q` before `OE 1, 0x02` in `start`); I4 stretching ignored (`scl_hi` → `OE 0, 0x02; DELAY 3; SETT R1, 0; RET; NOP`: `stretch` and `timeout` fail); I5 ACK never sampled (`BNC wret` → `JMP wret`: `addr_nack`, `data_nack` fail); I6 tSU;STO removed (delete the two `ADDT R1, Q` before `OE 0, 0x01` in `stop`); I7 STRETCHED never set (`OR R6, R4` in `scl_hi` → `NOP`: `stretch` fails). Record the killing test per mutant.

**Step 6 — CI, docs, commit.** `test.yaml` step `I2C master firmware vs reference slave (test/Makefile.i2cfw)` with `results_i2cfw.xml`; `docs/info.md` subsection `### I2C master (firmware/i2c_master.s)`: constants and the standard-mode figures they give, command and result words, stretching and timeout behaviour, what the model checks (the limits list), suite and test names, firmware size; `test/README.md`. Verify: all seven cocotb suites, pytest, `gen_isa.py --check`, `git diff sram-imem -- src isa formal tools/sim.py tools/host.py` empty, Verilator lint unchanged (no `src/` change). Commit:

```bash
git add tools/refmodels/i2c_slave_ref.py tests/test_fw_i2c.py test/test_i2c_fw.py test/Makefile.i2cfw firmware/i2c_master.s .github/workflows/test.yaml docs/info.md test/README.md
git commit -m "feat(fw): I2C master firmware with a reference slave that checks the standard-mode timing table, ACK/NACK, repeated START, stretching and timeout"
```

---

### Task 4: Documentation, counts and the branch state

**Files:**
- Modify: `README.md` ("What CI runs", Layout, Status), `test/README.md` (final wording), `HANDOFF.md`, `PLAN.md`, `docs/info.md` (status line), `docs/superpowers/specs/2026-10-16-protocol-firmware-design.md` (status line)

**Interfaces:** consumes the measured suite counts and wall-clocks from Tasks 1–3's reports; produces documents only (no code).

- [ ] **Step 1:** Measure: every cocotb suite's `TESTS=` count and wall-clock, `python -m pytest -q` count, each firmware's word count (`python tools/asm.py firmware/<f>.s | wc -l`), the mutant tables from the three task reports.
- [ ] **Step 2:** `README.md`: "What CI runs" lists the seven cocotb suites with counts and the pytest count; Layout mentions `tools/refmodels/` and the three firmware files; Status gains a 2026-10 row for plan C (what exists, that the models are spec-derived and mutant-checked in CI, the branch and that it is not merged). `test/README.md`: seven suites. `docs/info.md`: status sentence names the firmware. The spec's status line: "implemented on branch `protocol-fw`, pending owner review".
- [ ] **Step 3:** `HANDOFF.md`: state (branch, head, suite counts), "Where everything is" rows for the firmware, models and harnesses, "What is left" (owner: review and merge order of `sram-imem` then `protocol-fw`; the 40 MHz decision applies to the `.equ` blocks and `CLK_HZ`), the mutant tables condensed to one line per protocol. `PLAN.md`: status paragraph and a decision-log line (plan C executed; what the owner still decides).
- [ ] **Step 4:** Verify: pytest and `gen_isa.py --check` still pass (docs only); `git status --short` clean after the commit.
- [ ] **Step 5:** Commit: `git commit -m "docs: plan C state, suite counts, firmware table and handoff [skip ci]"` — without `[skip ci]` if any non-docs file changed.

---

## Self-review against the design doc

- §2 pin map → Global Constraints and every firmware header; `.equ` block and `PRESCALE` → Global Constraints, `constants()` (Task 1 Step 1), `boot()`/`load()`; model interface and two harnesses → Task 1 Steps 3 and 5; mutant sentinels → each task's in-suite sentinel test; drain/end-to-end → `drain()` and the `drained == pushes` assertion in every RTL test; `T` away from zero → `t0=0xFF00` in `run_model`.
- §3 UART behaviour and model options (baud error, probe, stop_low, glitch, gap), window with nominal 9.5 bits → Task 1 Steps 2 and 4, `CASES`; sentinel BIT 210 → `MUTANT_BIT`.
- §4 SPI word format, CPOL at transaction start / CPHA per word, firmware structure, model checks incl. window and first-bit exception → Task 2; sentinel HALF 27 → `MUTANT_HALF`; late words → `host_at`.
- §5 I2C words, grid, `scl_hi` with the five-cycle detection, abort path, model limits and slave options, cases incl. stretch and timeout → Task 3; sentinel Q 96 → `MUTANT_Q`.
- §6 docs and CI → Steps 8/6/6 of Tasks 1–3 and Task 4.
- Names used consistently: `UartRxRef`, `Frame`, `SpiSlaveRef`, `I2cSlaveRef`, `spi_cmd`, `i2c_cmd`, `load`, `run_model` (both harnesses), `boot`, `drain`, `host_push`, `status`, `firmware_text`, `MUTANT_BIT`/`MUTANT_HALF`/`MUTANT_Q`, `CASES`, `CLK_HZ`.
