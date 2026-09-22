import pytest
from tools.host import encode_write_imem, encode_write_ctrl, encode_write_prescale, CMD_WRITE_IMEM, CMD_WRITE_CTRL, CMD_WRITE_PRESCALE

def test_encoders_byte_layout():
    # docs/info.md protocol table: WRITE_IMEM = 0x01, address hi (2 bits) then lo, then words hi/lo.
    assert encode_write_imem(0x2AB, [0x4801, 0x0000]) == bytes([CMD_WRITE_IMEM, 0x02, 0xAB, 0x48, 0x01, 0x00, 0x00])
    assert encode_write_ctrl(run=True) == bytes([CMD_WRITE_CTRL, 0x01])
    assert encode_write_ctrl(run=False, reset=True) == bytes([CMD_WRITE_CTRL, 0x02])
    assert encode_write_ctrl(run=True, reset=True) == bytes([CMD_WRITE_CTRL, 0x03])
    assert encode_write_prescale(255) == bytes([CMD_WRITE_PRESCALE, 0xFF])

def test_encoders_reject_out_of_range_instead_of_masking():
    # A 17-bit word, an 11-bit address or a 9-bit prescale used to be masked silently, loading a
    # corrupted program (or the wrong divider) with no error.
    with pytest.raises(ValueError, match=r"words\[1\]"): encode_write_imem(0, [0x1234, 0x10000])
    with pytest.raises(ValueError, match="addr"): encode_write_imem(1024, [0])
    with pytest.raises(ValueError, match="addr"): encode_write_imem(-1, [0])
    with pytest.raises(ValueError, match="prescale"): encode_write_prescale(256)
    with pytest.raises(ValueError, match="prescale"): encode_write_prescale(-1)
    with pytest.raises(ValueError): encode_write_imem(0, [1.5])
    assert encode_write_imem(1023, [0xFFFF]) == bytes([CMD_WRITE_IMEM, 0x03, 0xFF, 0xFF, 0xFF])   # the limits themselves are fine
