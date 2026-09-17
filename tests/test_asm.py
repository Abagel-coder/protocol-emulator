import pytest
from tools.asm import assemble, AsmError

def w(text): return assemble(text)

def test_nop_halt_encoding():
    assert w("NOP\nHALT") == [0x0000, 0x0001]

def test_ldi_and_alu():
    # LDI R1,0x5A -> class1 rd=1 hi=0 imm=0x5A ; ADD R2,R1 -> class2 rd=2 rs=1 fn=1
    assert w("LDI R1, 0x5A\nADD R2, R1") == [(1<<12)|(1<<9)|0x5A, (2<<12)|(2<<9)|(1<<6)|(1<<2)]

def test_pin_ops_and_setr():
    assert w("SET UO, 0x01\nCLR UIO, 0x80\nOE 1, 0x03\nSETR UO, 0, R2, 0") == [
        (4<<12)|(0<<10)|(0<<8)|0x01, (4<<12)|(1<<10)|(1<<8)|0x80, (4<<12)|(3<<10)|(1<<8)|0x03, (5<<12)|(2<<9)|(0<<8)|(0<<5)|0]

def test_waits():
    assert w("WAITT R1\nDELAY 100\nWAITP UI, 3, RISE, R4\nWAITF RXV, R0") == [
        (7<<12)|(0<<9)|(1<<6), (7<<12)|(1<<9)|100, (7<<12)|(2<<9)|(4<<6)|(0<<5)|(3<<2)|2, (7<<12)|(3<<9)|(0<<6)|0]

def test_relative_branch_and_labels():
    prog = "top:\n  LDI R1, 1\n  BNZ top\n  NOP\n  JMP top"
    words = w(prog)
    # BNZ at address 1: simm9 = 0 - (1+1) = -2 -> 0x1FE
    assert words[1] == (9<<12)|(1<<9)|0x1FE
    assert words[3] == (10<<12)|0

def test_org_equ_word():
    assert w(".equ PERIOD 42\n.org 2\n.word PERIOD\nSETT R1, PERIOD") == [0, 0, 42, (8<<12)|(1<<9)|(0<<8)|42]

def test_range_errors():
    with pytest.raises(AsmError): w("LDI R1, 300")
    with pytest.raises(AsmError): w("BZ far\n" + "NOP\n"*300 + "far: NOP")
    with pytest.raises(AsmError): w("FOO R1")
