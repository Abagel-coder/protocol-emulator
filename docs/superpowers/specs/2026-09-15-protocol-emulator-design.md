# Protocol Emulator ASIC — Design Proposal (v1, awaiting approval)

Date: 2026-09-15 (v0 morning, v1 evening after the prior-art and verification scans in `docs/research/`). Status: **proposal**. The warm-up UART transmitter exists; none of the core is implemented. Numbers marked *(estimate)* must be replaced by synthesis results in the first two weeks.

Changes from v0 are listed in §16.

## 1. Purpose

A small deterministic processor whose instruction set is built for pin I/O and exact cycle timing, so that UART, SPI, I2C — and, as stretch goals, low-speed USB and 10BASE-T Ethernet — are implemented as firmware loaded after fabrication. Target: IHP 130 nm SG13CMOS5L via Tiny Tapeout, 6x4 tiles.

The headline claim (see `docs/research/novelty-synthesis.md`): **the ISA's timing contract is a machine-checked theorem**, and the pin engines carry the line coding, CRC and bit-stuffing that make USB and Ethernet firmware protocols instead of hand-tuned tricks.

## 2. Constraints

| Constraint | Value |
|---|---|
| Area | 6x4 tiles = 1289.28 × 710.64 µm; ~24K cells nominal before overhead |
| Pins | 8 in, 8 out, 8 bidirectional, one clock, one active-low reset |
| Clock | 50 MHz timing target (template default); demo board supplies up to 66.5 MHz; the 10BASE-T demo runs the core at 40 or 60 MHz so the 20 MHz Manchester transition rate is an integer divide |
| Pads | outputs documented to ~33 MHz, inputs ~66 MHz (sky130 figures; verify for IHP) |
| Memory | 1 KB single-port SRAM macro available (146.88 × 336.46 µm each); flip-flops otherwise |
| Flow | LibreLane via the Tiny Tapeout cmos5l action; Verilog in `src/`; cocotb tests in `test/` |

## 3. Design principles

1. **Timing is a first-class ISA concept.** Firmware states *when* a pin changes, not how many instructions to pad. Hardware guarantees the cycle.
2. **Every instruction's latency is a function of its opcode only**, except the wait family, whose latency is the point. This makes timing static and formally checkable.
3. **Hard things at the pin, decisions in the core.** Serialisation, line coding, CRC and bit-stuffing run in small programmable pin engines at full clock rate; the scalar core makes protocol decisions at byte granularity.
4. **Safe by default.** After reset all bidirectional pins are inputs and the core is halted until the host starts it.
5. **One source of truth.** The ISA is described once, machine-readably, and everything (assembler, simulator, RTL decode constants, docs) is generated from it, with a CI check that nothing drifts.
6. **Every blocking instruction has a bounded wait.** No firmware can hang the core forever on a stuck bus; this is a proof obligation, not a convention.

## 4. Architecture overview

```
                 ┌───────────────────────────────────────────────────────────┐
  ui_in[7:4] ──▶ │ Host port (SPI slave, mode 0)  ──▶ control/status regs     │
  uo_out[7]  ◀── │        │                          instruction-memory writes │
                 │        ▼                                                    │
                 │  ┌───────────────┐   ┌──────────────────────────────────┐  │
                 │  │ Instruction   │──▶│ Core: 2-stage (fetch/execute)     │  │
                 │  │ memory        │   │ 8 × 16-bit regs, 16-bit ALU,      │  │
                 │  │ 1024 × 16     │   │ PC, flags, call stack (4 deep)    │  │
                 │  │ (2 SRAM       │   │ timebase T (16-bit + prescaler)   │  │
                 │  │  macros)      │   │ wait unit: deadline / delay /     │  │
                 │  └───────────────┘   │ pin-event / lane / flag, all with │  │
                 │                      │ timeouts                          │  │
                 │                      └───────┬───────────────┬──────────┘  │
                 │                              │ pin ops       │ lane ops     │
                 │                      ┌───────▼───────┐  ┌────▼──────────┐  │
                 │                      │ GPIO block    │  │ Pin engines   │  │
                 │                      │ sync inputs,  │  │ ("lanes") ×2  │  │
                 │                      │ out/oe regs,  │◀▶│ shift, clkdiv,│  │
                 │                      │ edge detect,  │  │ NRZ/NRZI+stuff│  │
                 │                      │ contention    │  │ /Manchester,  │  │
                 │                      │ monitors      │  │ CRC-32, start-│  │
                 │                      └───────┬───────┘  │ at-deadline,  │  │
                 │                              │          │ edge timestamp│  │
                 │                              │          │ FIFO          │  │
                 │                              │          └────┬──────────┘  │
                 │                    pin crossbar (any lane/reg ↔ any pin)    │
                 └──────────────────────────────┬──────────────────────────────┘
        ui_in[3:0] (inputs)  uo_out[6:0] (outputs)  uio[7:0] (bidirectional)
```

## 5. ISA v1 (16-bit instructions)

Registers: `R0–R7` (16-bit; `R0` reads as zero), `PC` (10-bit), `T` (16-bit free-running timebase, clocked by a programmable prescaler), flags `Z`, `C`, `TO` (last wait timed out), and a 4-entry hardware call stack. Instruction word: 4-bit opcode class + 12 bits of operands.

| Class | Instructions | Notes |
|---|---|---|
| Pin | `SET mask,val` · `CLR mask` · `TGL mask` · `SETR mask,Rn,bit` · `OE mask,val` · `IN Rd,pinsel` | Multi-pin writes in one cycle; output register updates on the cycle after execute |
| Wait | `WAITT Rn` · `DELAY imm` · `WAITP pin,cond,Rt` · `WAITL lane,Rt` · `WAITF flag,Rt` | `WAITT` is exact to the cycle and bounded by construction (16-bit wrap). Every other wait carries a timeout `Rt` (ticks of `T`); on expiry the wait ends and `TO` is set. Only class with data-dependent latency |
| Time | `SETT Rd,imm` (`Rd = T + imm`) · `ADDT Rd,imm` · `RDT Rd` | Deadline arithmetic: schedule the *next* edge relative to the *previous deadline*, so jitter never accumulates (same idiom as Propeller `WAITCNT` and FlexPRET `DU`; not claimed as novel) |
| Lane | `LCFG lane,Rn` · `LOUT lane,Rn,nbits` · `LIN lane,Rd,nbits` · `LARM lane,Rt` · `LCRC lane,Rd` · `LTS lane,Rd` | `LARM` makes the next `LOUT`/`LIN` on that lane begin exactly at `T == Rt` (start-at-deadline). `LTS` pops an edge timestamp (`T` value and level) from the lane's capture FIFO |
| ALU | `MOV` · `LDI` (8-bit imm + `LDIH`) · `ADD` · `SUB` · `AND` · `OR` · `XOR` · `SHL` · `SHR` · `ROR` · `CMP` · `BITT` | Single cycle |
| Flow | `JMP` · `BZ` · `BNZ` · `BC` · `BNC` · `BTO` · `BPIN pin,level` · `BFLAG flag` · `CALL` · `RET` · `HALT` | One delay slot after every branch so taken/not-taken cost the same |
| Host | `PUSH Rn` / `POP Rd` (host FIFO) · `IRQ` | Host reads/writes over the SPI port |

Flags readable by `WAITF`/`BFLAG`: per-lane `DONE`, `CAPV` (timestamp available), `LOST` (contention: pin driven high but sampled low), `STRETCH` (open-drain clock held low by another device), host FIFO `RXV`/`TXE`.

Pipeline: fetch (SRAM read, 1 cycle) → execute (1 cycle). Throughput one instruction per cycle. At 50 MHz that is 20 ns per instruction: a UART at 3 Mbaud has ~16 instructions per bit; I2C at 1 MHz has ~25 per half-clock; SPI at 12.5 MHz and USB at 1.5 Mbit/s use the lanes.

## 6. Timing model and formal contract

- `T` increments every `prescale` cycles (1–256). Deadline compares use wrap-safe signed difference, so a deadline may be up to 32767 ticks ahead.
- Canonical bit loop (UART TX at bit period `P` ticks):
  ```
      SETT  R1, 0          ; R1 = now
  loop:
      ADDT  R1, P          ; next deadline = previous deadline + P (no drift)
      SETR  TX, R2, 0      ; queue the level from R2 bit 0
      WAITT R1             ; hits the exact tick
      ...
  ```
- Properties to prove with SymbiYosys (k-induction where possible; each is a numbered theorem in the write-up):
  1. **Deadline exactness:** `WAITT` releases in the cycle where `T == Rn`, never earlier or later.
  2. **Static timing:** for every non-wait instruction, `PC` advances every cycle; latency depends only on the opcode.
  3. **Reset safety:** `uio_oe == 0` from reset until the first `OE` instruction executes.
  4. **Glitch-free pins:** each pin output register changes at most once per cycle and only as the result of an executed pin instruction or a lane.
  5. **Liveness:** every wait instruction completes within its timeout plus a constant; there is no reachable state in which the core is blocked forever.
  6. **Handshakes:** host FIFO and lane FIFOs never lose or duplicate a word; the timestamp FIFO reports overrun rather than silently dropping.

## 7. Pin engines ("lanes")

Each lane *(estimate: 600–800 cells)*:

- 16-bit shift register, bit counter, fractional clock divider (16.8, as in PIO), MSB/LSB-first, idle level.
- Line coder: NRZ; NRZI with USB-style bit-stuffing (insert a 0 after six 1s, and the matching de-stuffer on receive); Manchester (IEEE 802.3 polarity); CAN-style stuffing (five identical bits) if time permits.
- CRC unit: 32-bit programmable polynomial, init and final XOR, reflected or not (covers CRC-5/CRC-16 for USB, CRC-32 for Ethernet, CRC-15 for CAN).
- **Start-at-deadline:** `LARM` latches a `T` value; the next transfer begins on that exact tick, so a byte can be scheduled ahead of time and the core is free to compute meanwhile.
- **Edge-timestamp capture:** a 4-deep FIFO of (`T`, level) latched on selected edges of the lane's input pin, with an overrun flag. This is the clock-recovery primitive for USB and Ethernet receive, and a general timing analyser for the write-up.
- Lanes connect to pins through a crossbar so any lane drives/samples any pin.

Contention monitors live in the GPIO block, one per bidirectional pin: when a pin is driven high through the open-drain emulation (`oe` low, expecting a pull-up) but sampled low, `LOST` or `STRETCH` is raised depending on the pin's configured role (data or clock). This is what I2C slave mode, multi-master I2C and CAN arbitration need, and what FlexIO documents as unsupported.

Start with 2 lanes; add up to 4 if area allows.

## 8. Memory

- **Instruction memory:** two `RM_IHPSG13_1P_1024x8_c2_bm_bist` macros side by side = 1024 × 16-bit, roughly a fifth of the 6x4 block. Fallback if the macro does not harden on cmos5l: 64–128 × 16-bit flip-flop memory. The trial run is in progress.
- **Data:** the register file plus lane buffers. No data RAM in v1. A trace ring buffer (decision N7) is deferred until the first area report.
- The SRAM has a one-cycle synchronous read, which is exactly the fetch stage.

## 9. Host interface and pin map (v1)

| Pins | Use |
|---|---|
| `ui_in[4]`, `ui_in[5]`, `ui_in[6]`, `uo_out[7]` | Host SPI: SCK, MOSI, CS_n, MISO |
| `ui_in[7]` | RUN (level): 0 = halt and allow loading, 1 = run |
| `ui_in[3:0]` | protocol inputs (UART RX, SPI MISO when master, clocks when slave) |
| `uo_out[6:0]` | protocol outputs (UART TX, SPI SCK/MOSI, status) |
| `uio[7:0]` | bidirectional protocol pins (I2C SDA/SCL via open-drain emulation, USB D+/D−, SPI slave lines, JTAG/SWD, CAN TX/RX through a transceiver) |

Host register map: instruction memory write (auto-increment), control (reset PC, run, single-step), status (PC, halted, flags, `TO`), host FIFO in/out, GPIO snapshot, timestamp FIFO drain. The demo board's RP2040 (MicroPython SDK) or any MCU with SPI can drive it.

## 10. Reset and safety

On `rst_n` low: all `uio_oe = 0`, outputs 0, lanes idle, core halted, `PC = 0`, `T = 0`. Unused/undefined opcodes execute as `NOP`. Illegal lane configurations are clamped. `HALT` stops the core and raises a host-visible flag. A wait that times out sets `TO` and continues; firmware decides what to do.

## 11. Verification plan (ranked; the judged deliverable)

| # | Technique | Evidence produced |
|---|---|---|
| 1 | SymbiYosys k-induction proofs of §6 properties 1–2 | proof logs, engine, wall-clock; "the timing contract is a theorem" |
| 2 | SymbiYosys proofs of §6 properties 3–6 (reset safety, glitch-free pins, liveness, handshakes) | proof logs |
| 3 | MCY mutation score over the whole cocotb + differential suite | kill rate, surviving-mutant list, before/after for every test added |
| 4 | Differential testing: RTL vs Python ISA simulator on constrained-random programs, with cocotb-coverage crosses (opcode × wait mode × lane mode) | coverage database and closure plot |
| 5 | Protocol reference models with timing-tolerance checks (UART, SPI all modes, I2C incl. stretching/repeated start/NACK/arbitration, USB-LS packets incl. stuffing and CRC, 10BASE-T frames incl. link pulses) | pass/fail per tolerance corner |
| 6 | EQY equivalence of RTL vs the LibreLane gate-level netlist, plus the template's gate-level simulation | equivalence log; pre-tapeout gate |
| 7 | microcotb replay of the identical cocotb tests on the FPGA breakout and, later, on silicon | identical test IDs passing in sim, gate level and hardware |
| 8 | Single-source ISA generator (YAML → assembler, simulator, RTL decode constants, docs) with a CI job that regenerates and diffs | "spec and implementation cannot drift" |
| 9 | AI-assisted drafting of properties, adversarial firmware and stimuli, each checked in with prompt, model and outcome, reported as acceptance rate and mutation-score delta | auditable numbers, never "we used AI" |

## 12. Area and timing budget *(estimates, replace with yosys numbers)*

| Block | Cells (est.) |
|---|---|
| Core (regs, ALU, decode, PC, stack) | 3,000–3,500 |
| Timebase + wait unit with timeouts | 400 |
| GPIO block + crossbar + 8 contention monitors | 900 |
| 2 lanes incl. line coders, CRC-32, start-at-deadline, timestamp FIFOs | 1,400–1,800 |
| Host SPI port + registers + FIFOs | 700 |
| Total logic | ~7–8K of ~24K, plus 2 SRAM macros |

The margin pays for clock tree and routing at 60 % density and leaves room for 4 lanes. The second-core idea from v0 is dropped (decision N8).

## 13. Alternatives considered

| Approach | Verdict |
|---|---|
| A. PIO clone with tweaks (several competitors) | Low risk, low novelty; equal-length code paths push timing work onto the programmer |
| B. General-purpose small CPU plus fixed UART/SPI/I2C blocks (the PSoC UDB / Patmos pattern) | Contradicts the brief; fixed blocks cannot do the stretch protocols |
| **C. Time-triggered core + programmable lanes with proofs (this proposal)** | Moderate risk, highest novelty; timing is provable; stretch protocols become feasible at the pad limits |

## 14. Open questions

1. Do the SRAM macros harden on the cmos5l flow? (Trial running; determines §8.)
2. Actual IHP pad toggle limits — determines whether 10BASE-T TX is realistic.
3. Timeout encoding: register (`Rt`) costs an operand field; an immediate in ticks may be enough for most waits. Decide when writing the ISA YAML.
4. Whether the contention monitor should be per pin (8 × ~50 cells) or per lane input (2 × ~50 cells) — decide from the first area report.

## 15. Positioning against prior art (for the write-up)

Same as: Propeller `WAITCNT`, FlexPRET `DU`, Ip & Edwards' deadline instruction (drift-free deadline waits); PIO/FlexIO/P2 smart pins (sequencer + shifter split). New: the timing contract is proved rather than counted; lanes carry line coding, stuffing and CRC that no engine ships; a contention primitive that FlexIO explicitly lacks and can2040 hand-codes; edge timestamps for clock recovery; an ISA-wide liveness proof that closes Propeller's documented hang; and a verification loop that reports mutation scores, gate-level equivalence and silicon replay of the same tests. Full citations in `docs/research/`.

## 16. Changes from v0

- Principle 6 (bounded waits) added; all waits except `WAITT` take a timeout; `TO` flag and `BTO` added (N5).
- Lanes gain USB-style bit-stuffing/de-stuffing, optional CAN stuffing, a 32-bit programmable CRC, start-at-deadline (`LARM`) and a 4-deep edge-timestamp FIFO (`LTS`, `CAPV`) (N2, N4, N6).
- GPIO block gains contention monitors and the `LOST`/`STRETCH` flags (N3).
- Verification plan re-ranked around proofs, mutation score, equivalence and hardware replay (N10).
- Second core dropped (N8); trace buffer deferred (N7); RMII out of scope (N9).
- Area estimate raised from ~6–7K to ~7–8K cells.
