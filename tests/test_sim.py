from tools.asm import assemble
from tools.sim import Sim

def run(src, cycles, **kw):
    s = Sim(assemble(src), **kw); return s, s.run(cycles)

def test_pin_write_visible_next_cycle():
    s, tr = run("SET UO, 0x01\nHALT\nNOP", 4)
    assert [t[1] for t in tr] == [0, 1, 1, 1]      # written in cycle 0, visible from cycle 1

def test_blink_period_is_10_cycles():
    src = open("firmware/blink.s").read()
    s, tr = run(src, 64)
    uo = [t[1] & 1 for t in tr]
    # Total loop = TGL(1) + DELAY 6(7) + JMP(1) + delay-slot NOP(1) = 10 cycles.
    edges = [i for i in range(1, 64) if uo[i] != uo[i-1]]
    assert edges[0] == 1 and all(b - a == 10 for a, b in zip(edges, edges[1:]))

def test_delay_slot_executes_after_jmp():
    s, tr = run("JMP 3\nSET UO, 0x02\nSET UO, 0x04\nHALT\nNOP", 6)
    assert tr[2][1] == 0x02 and tr[3][1] == 0x02          # slot executed, address 2 skipped

def test_waitt_exact_and_no_drift():
    src = "SETT R1, 0\nloop:\n ADDT R1, 5\n TGL UO, 0x01\n WAITT R1\n JMP loop\n NOP"
    s, tr = run(src, 60)
    uo = [t[1] & 1 for t in tr]
    edges = [i for i in range(1, 60) if uo[i] != uo[i-1]]
    # edges[0] is the first toggle after the one-time SETT/ADDT warm-up (3 cycles);
    # "no drift" means the steady-state period stays exactly 5 thereafter.
    assert all(b - a == 5 for a, b in zip(edges[1:], edges[2:]))

def test_waitp_timeout_sets_TO():
    s = Sim(assemble("WAITP UI, 0, HIGH, R2\nHALT\nNOP"))
    s.regs[2] = 3; s.run(10)
    assert s.halted and s.flags["TO"] == 1

def test_waitp_release_on_rise():
    s = Sim(assemble("WAITP UI, 0, RISE, R0\nSET UO, 0x01\nHALT\nNOP"))
    s.run(5); s.set_inputs(ui=1, uio_in=0); tr = s.run(6)
    assert s.flags["TO"] == 0 and tr[-1][1] == 1

def test_alu_flags_and_r0_zero():
    s = Sim(assemble("LDI R1, 0xFF\nLDIH R1, 0xFF\nLDI R2, 1\nADD R1, R2\nMOV R0, R2\nHALT\nNOP"))
    s.run(4)  # through ADD R1, R2: check its flags before MOV (which also sets Z) overwrites them
    assert s.regs[1] == 0 and s.flags["Z"] == 1 and s.flags["C"] == 1
    s.run(4)  # MOV R0, R2 then HALT: rd=0 writes are discarded
    assert s.regs[0] == 0

def test_call_ret_stack():
    s = Sim(assemble("CALL 4\nNOP\nSET UO, 0x02\nHALT\nSET UO, 0x01\nRET\nNOP\nNOP")); tr = s.run(10)
    assert s.halted and tr[-1][1] == 0x03

def test_uart_tx_firmware_bit_timing():
    s = Sim(assemble(open("firmware/uart_tx.s").read()), prescale=2); tr = s.run(11 * 434 + 20)
    tx = [t[1] & 1 for t in tr]
    edges = [i for i in range(1, len(tx)) if tx[i] != tx[i-1]]
    # 0x55 = 01010101: start 0, then 1,0,1,0,1,0,1,0, stop 1 -> an edge every bit
    assert all(b - a == 434 for a, b in zip(edges, edges[1:])), edges[:12]
    assert s.halted
