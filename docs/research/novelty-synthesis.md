# Novelty Synthesis — what the three research scans mean for the design (2026-09-15)

Inputs: [prior-art-academic.md](prior-art-academic.md), [prior-art-industry.md](prior-art-industry.md), [verification-novelty.md](verification-novelty.md). This memo turns them into decisions. Items marked **decide** need the user's approval; they are folded into the v1 design spec as proposals.

## 1. What is *not* novel (stop claiming it)

- **Deadline waits with drift-free accumulation.** Our `SETT`/`ADDT`/`WAITT` idiom is functionally the same as Propeller 1's `WAITCNT D,S` (2006), Ip & Edwards' `dead`/`deadi` (2006), PTARM's deadline instruction (2008) and FlexPRET's `DU` (2014). Two competition entries (BitLoom, 2AM Logic's spec) also have or plan it. It stays in the design because it is right, but it is table stakes, not a headline.
- **Sequencer + shifter split.** PIO, PRU's shift modes, FlexIO, Propeller 2 smart pins and PSoC UDBs all split a small sequencer from fast shift/timer hardware. "Lanes" are a known shape.
- **Python reference models + constrained random.** BitLoom already ships this with bounded SAT proofs on FIFOs.

## 2. What *is* novel (the evidence)

| Claim | Why it is defensible | Source |
|---|---|---|
| A **machine-checked timing contract** for a protocol engine ISA (static per-opcode latency, exact deadline release, proven by k-induction, published as an artifact) | No formal semantics or proof exists for RP2040 PIO, Propeller smart pins or XMOS timed ports; PIO/PRU users hand-count cycles; BitLoom's proofs are 24-cycle bounded FIFO checks only | academic §4.2, §4.10; industry §2; verification §3.1 |
| **Line-coding + CRC + bit-stuffing in the pin engine**, tied to the proven timebase | Every deadline-ISA machine (PRET family) has no serialisation hardware; every serialisation engine (PIO, P2 smart pins, XS1 ports, FlexIO) has no CRC or bit-stuffing; can2040 and V-USB do it by hand in software | academic §4.1; industry §5.3 |
| **Bus-contention / clock-stretch primitive** (driven-vs-sampled compare on open-drain pins, flag visible to `WAITF`) | NXP AN5133 states FlexIO I2C does not support clock stretching or multi-master arbitration; can2040 hand-codes arbitration as a `jmp pin` fall-through | industry §2 FlexIO, §5.2 |
| **Hardware edge-timestamp capture** (latch `T` on a pin edge into a small FIFO) for clock recovery | Named as the hardest problem by every community USB/CAN/Ethernet-on-PIO project (espthernet's hand-tuned tables, pico_eth's missing link-pulse detection, can2040's edge windows) | industry §5.4 |
| **Provable liveness: every blocking instruction has a bounded wait** | Propeller 1's datasheet documents `WAITPEQ`/`WAITPNE` can hang forever; nobody proves an ISA-wide "no permanent hang" invariant | academic §4.3 |
| **Firmware Ethernet on a time-predictable core** | The one time-predictable architecture with Ethernet (Patmos/T-CREST) ships a fixed hardware MAC and explicitly rejects the PRET approach | academic §2.6 |
| **Verification that closes the loop with numbers**: mutation score (MCY), gate-level equivalence (EQY), the same cocotb tests replayed on silicon (microcotb), single-source ISA with a CI drift check | A 2026 mutation-testing audit found most public RTL test suites fail 95 % mutation kill despite "passing tests"; no competitor reports a mutation score or replays sim tests on hardware | verification §2.5, §2.10, §2.15, §3 |

## 3. Decisions

| # | Decision | Status |
|---|---|---|
| N1 | Headline: "the timing contract is a theorem": publish formal ISA semantics + proofs as a first-class deliverable | **decide** (recommended yes) |
| N2 | Lanes get programmable line coding (NRZ, NRZI+bit-stuff for USB, CAN-style stuffing, Manchester) and a 32-bit programmable CRC | **decide** (recommended yes; USB first, Manchester second, CAN stuffing only if time) |
| N3 | Add the contention/clock-stretch monitor (per open-drain pin, ~50 cells each) | **decide** (recommended yes; unlocks I2C slave, multi-master, CAN arbitration) |
| N4 | Add edge-timestamp capture: 4-deep FIFO of (`T`, pin, level) per lane, ~200 cells each | **decide** (recommended yes; needed for USB-LS RX and any Ethernet RX) |
| N5 | Every wait instruction takes a timeout; proof obligation "no permanent hang" | **decide** (recommended yes; ISA change: `WAITP`/`WAITL`/`WAITF` gain a timeout register or immediate) |
| N6 | Lane start-at-deadline: a lane op may be armed to begin at `T == Rt`, fusing per-port timers (XMOS) with the global deadline (PRET) | **decide** (recommended yes; ~40 cells per lane, small proof) |
| N7 | On-chip trace ring buffer | **defer** to v1: competes with instruction memory for SRAM; revisit after the first area report |
| N8 | Two cores sharing instruction memory | **drop**: least differentiated (PIO has 8–12 state machines, PRU has two cores) |
| N9 | 100BASE-TX via RMII at 50 MHz | **out of scope**: needs an external PHY and pins we don't have; note as future work in the write-up |
| N10 | Verification stack: SBY k-induction (timing, reset/pin safety, liveness), MCY mutation score, EQY RTL-vs-netlist, cocotb-coverage crosses, microcotb replay on FPGA/silicon, single-source ISA generator with CI diff check, AI-assisted drafting reported with acceptance rates | **decide** (recommended yes, in that priority order) |

## 4. Numbers that constrain the design

| Protocol | Rate | Core cycles per bit at 50 MHz | Implication |
|---|---|---|---|
| UART 115200 / 3 Mbaud | 115.2 kbit/s / 3 Mbit/s | 434 / 16.7 | core alone is fine |
| SPI 12.5 MHz | 12.5 Mbit/s | 4 | lane required |
| I2C 400 kHz / 1 MHz | 400 kbit/s / 1 Mbit/s | 125 / 50 | core alone is fine; stretch monitor needed for slaves |
| USB low speed | 1.5 Mbit/s, ±1.5 % clock tolerance, stuff bit after six 1s | 33.3 | lane with NRZI + stuffing; RX needs edge timestamps |
| CAN 1 Mbit/s | 1 Mbit/s, sample point ~75 % | 50 | contention monitor + stuffing |
| 10BASE-T | 10 Mbit/s Manchester, transitions at 20 MHz; link pulses every 16 ± 8 ms | 5 per bit, 2.5 per half-bit | not an integer at 50 MHz: run the core at 40 or 60 MHz for the Ethernet demo, or give the lane a 2.5× fractional divider with accepted jitter; TX only unless edge capture works |
| RMII 100BASE-TX | 50 MHz reference, 2 bits/clock | 0.5 | out of scope |

## 5. What this changes in the schedule

Nothing in the next two weeks: the core, the timebase and the host port come first regardless. The lane work in weeks 3–4 (Sep 27 onward) now has a definite feature list (N2–N6) and an order: NRZ shift → CRC → NRZI/stuffing (USB) → edge timestamps → Manchester. The formal work starts with the static-timing and reset-safety proofs in week 2 of the core, since they are the headline.
