import importlib, pathlib, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]

def test_generator_writes_all_three_outputs(tmp_path):
    out = subprocess.run([sys.executable, "tools/gen_isa.py", "--out-dir", str(tmp_path)], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "isa_defs.py").exists()
    assert (tmp_path / "isa_defs.vh").exists()
    assert (tmp_path / "isa.md").exists()

def test_generated_python_matches_yaml():
    import tools.isa_defs as d
    assert d.CLASSES["WAIT"] == 7 and d.CLASSES["LANE"] == 13
    assert d.ALU_FN["BITT"] == 10 and d.BR_COND["BNTO"] == 5
    assert d.MNEMONICS["WAITP"]["operands"] == ["bank", "pin", "cond", "rt"]
    assert d.LAYOUTS["BR"]["simm9"] == (8, 0)
    assert d.REGS["R7"] == 7

def test_generated_verilog_has_defines():
    text = (ROOT / "src" / "isa_defs.vh").read_text()
    assert "`define ISA_CLS_WAIT 4'd7" in text
    assert "`define ISA_ALU_BITT 4'd10" in text
    assert "`define ISA_WP_RISE 2'd2" in text

def test_check_mode_detects_drift(tmp_path):
    out = subprocess.run([sys.executable, "tools/gen_isa.py", "--check"], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
