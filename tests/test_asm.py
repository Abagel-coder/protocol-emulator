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
    with pytest.raises(AsmError, match="simm9"): assemble("BZ far\n" + "NOP\n"*300 + "far: NOP", max_words=None)   # +301 is beyond simm9, not a size error
    with pytest.raises(AsmError): w("FOO R1")

def test_unsigned_field_boundaries():
    # imm8 is 8 bits: 255 fits, 256 does not. Without the check, 256 would silently set bit 8,
    # which is LDI's `hi` field -- turning `LDI R1, 256` into `LDIH R1, 0` (mutant A3).
    assert w("LDI R1, 255") == [(1<<12)|(1<<9)|255]
    with pytest.raises(AsmError, match="imm8=256"): w("LDI R1, 256")
    assert w("DELAY 511") == [(7<<12)|(1<<9)|511]
    with pytest.raises(AsmError, match="imm9=512"): w("DELAY 512")
    assert w("JMP 1023") == [(10<<12)|1023]
    with pytest.raises(AsmError): w("JMP 1024")
    with pytest.raises(AsmError): w("LDI R1, -1")

def test_signed_branch_offset_boundaries():
    # simm9: -256..+255 (both limits assemble; one past either raises -- mutant A2 moved `hi`).
    assert w("BZ 255") == [(9<<12)|(0<<9)|255]
    assert w("BZ -256") == [(9<<12)|(0<<9)|0x100]
    with pytest.raises(AsmError, match="simm9=256"): w("BZ 256")
    with pytest.raises(AsmError, match="simm9=-257"): w("BZ -257")
    # simm7 (BPIN) and simm6 (BFLAG) likewise.
    assert w("BPIN UI, 0, 1, 63")[0] & 0x7F == 63
    with pytest.raises(AsmError, match="simm7=64"): w("BPIN UI, 0, 1, 64")
    assert w("BFLAG RXV, 1, -32")[0] & 0x3F == 0x20
    with pytest.raises(AsmError, match="simm6=-33"): w("BFLAG RXV, 1, -33")

def test_program_size_limit():
    # the instruction memory is 512 words (src/pe_imem.v): address 511 is the last one, .org 512 names
    # an address that does not exist, and a 513th word is an error (silently aliasing modulo 512 on
    # the chip would be a trap)
    assert len(w(".org 511\nNOP")) == 512
    assert len(w("NOP\n" * 512)) == 512
    with pytest.raises(AsmError, match="line 1: .org 0x200 is outside the 512-word"): w(".org 512\nNOP")
    with pytest.raises(AsmError, match="line 513: program does not fit: address 0x200 is beyond the 512-word instruction memory"): w("NOP\n" * 513)
    # max_words=None lifts the limit to the 10-bit PC
    assert len(assemble("NOP\n" * 513, max_words=None)) == 513
    with pytest.raises(AsmError, match="beyond the 1024-word"): assemble(".org 1023\nNOP\nNOP", max_words=None)
    with pytest.raises(AsmError, match="line 1: .org 0x1388 is outside"): assemble(".org 5000\nNOP", max_words=None)

def test_word_directive_range_and_labels():
    assert w(".word 0xFFFF\n.word -1\n.word -32768") == [0xFFFF, 0xFFFF, 0x8000]
    with pytest.raises(AsmError, match="line 1: .word value 74565 does not fit"): w(".word 0x12345")
    with pytest.raises(AsmError, match="line 1: .word value -32769"): w(".word -32769")
    assert w("NOP\ntbl: NOP\n.word tbl") == [0, 0, 1]                      # a label in .word is its address

def test_directive_argument_errors_carry_line_numbers():
    # .org/.word/.equ argument problems used to escape as raw IndexError/ValueError (no line).
    with pytest.raises(AsmError, match="line 2: .org expects exactly one argument"): w("NOP\n.org")
    with pytest.raises(AsmError, match="line 1: .org address must be a number"): w(".org FOO")
    with pytest.raises(AsmError, match="line 2: .org address must be a number"): w(".equ BASE 4\n.org BASE")   # .org takes a literal in v0 (symbols: next plan)
    with pytest.raises(AsmError, match="line 3: .word expects exactly one argument"): w("NOP\nNOP\n.word")
    with pytest.raises(AsmError, match="line 1: unknown symbol 'nope'"): w(".word nope")
    with pytest.raises(AsmError, match="line 1: .equ value must be a number"): w(".equ X Y")
    with pytest.raises(AsmError, match="line 1: .equ expects NAME VALUE"): w(".equ X 1 2")

def test_addi_label_is_absolute_not_relative():
    # Only the branch classes (BR/BPIN/BFLAG) resolve a label pc-relatively; ADDI's simm9 is a
    # plain signed immediate, so `ADDI R1, tbl` loads tbl's address (2), not tbl - (pc + 1).
    words = w("NOP\nNOP\ntbl: NOP\nADDI R1, tbl")
    assert words[3] == (3<<12)|(1<<9)|2

def test_equ_malformed_raises():
    """Malformed .equ (missing value) must raise AsmError with line number."""
    with pytest.raises(AsmError): w(".equ NAME")
    with pytest.raises(AsmError): w(".equ NAME=5")

def test_equ_accepts_both_forms():
    """Accept both .equ NAME VALUE and .equ NAME, VALUE."""
    result1 = w(".equ X 10\n.word X")
    assert result1 == [10]
    result2 = w(".equ Y, 20\n.word Y")
    assert result2 == [20]

def test_duplicate_label_raises():
    """Duplicate label definitions must raise AsmError naming the label and line."""
    with pytest.raises(AsmError) as exc_info:
        w("top:\n  NOP\ntop:\n  NOP")
    assert "top" in str(exc_info.value).lower() or "duplicate" in str(exc_info.value).lower()

def test_org_backwards_raises():
    """Moving .org backwards (to lower address) must raise AsmError."""
    with pytest.raises(AsmError):
        w(".org 10\n  NOP\n.org 5\n  NOP")

def test_org_clobber_raises():
    """Encoding a word at an address already used must raise AsmError. Addresses only ever
    move forwards, so this is the same check as test_org_backwards_raises (pass 1's
    backward-.org check, the only one left: the pass-2 duplicate was dead code)."""
    with pytest.raises(AsmError, match="line 3: .org 0x0 moves backwards from 0x1"):
        w(".org 0\n  NOP\n.org 0\n  NOP")

def test_constants_returns_the_equ_table():
    from tools.asm import constants
    assert constants(".equ A 5\n.equ B, 0x10\nlbl:\n  NOP\n") == {"A": 5, "B": 16}
    assert constants("NOP\n") == {}
