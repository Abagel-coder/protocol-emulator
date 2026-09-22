import pathlib, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
GEN = [sys.executable, "tools/gen_isa.py"]

def test_generator_writes_all_three_outputs(tmp_path):
    out = subprocess.run(GEN + ["--out-dir", str(tmp_path)], cwd=ROOT, capture_output=True, text=True)
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

def test_checked_in_outputs_are_up_to_date():
    out = subprocess.run(GEN + ["--check"], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr

def test_check_mode_detects_drift(tmp_path):
    """`--check` must fail (exit 1, naming the file) when any generated output differs from
    what isa.yaml produces, and pass on a fresh set. The earlier version of this test only ran
    `--check` on the clean tree, so a generator that never reported drift (`rc = 0` always,
    mutant M1) passed it."""
    assert subprocess.run(GEN + ["--out-dir", str(tmp_path)], cwd=ROOT, capture_output=True).returncode == 0
    clean = subprocess.run(GEN + ["--check", "--out-dir", str(tmp_path)], cwd=ROOT, capture_output=True, text=True)
    assert clean.returncode == 0 and clean.stdout == "", clean.stdout
    for name, edit in (("isa_defs.vh", lambda s: s.replace("`define ISA_WP_RISE 2'd2", "`define ISA_WP_RISE 2'd3")),
                       ("isa_defs.py", lambda s: s.replace("'BITT': 10", "'BITT': 11")),
                       ("isa.md", lambda s: s + "\n")):
        original = (tmp_path / name).read_text()
        corrupted = edit(original)
        assert corrupted != original
        (tmp_path / name).write_text(corrupted)
        out = subprocess.run(GEN + ["--check", "--out-dir", str(tmp_path)], cwd=ROOT, capture_output=True, text=True)
        assert out.returncode == 1, (name, out.returncode, out.stdout)
        assert name in out.stdout, (name, out.stdout)          # the unified diff names the drifted file
        (tmp_path / name).write_text(original)
    (tmp_path / "isa.md").unlink()                             # a missing output is drift too
    out = subprocess.run(GEN + ["--check", "--out-dir", str(tmp_path)], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 1 and "isa.md" in out.stdout, out.stdout
