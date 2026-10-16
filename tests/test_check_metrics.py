import json, subprocess, sys, pathlib
HERE = pathlib.Path(__file__).parent
SCRIPT = HERE.parent / "test" / "check_metrics.py"
GOOD = HERE / "data" / "metrics_core_v01.json"

def load():
    with open(GOOD) as f:
        return json.load(f)

def dump(m, p):
    with open(p, "w") as f:
        json.dump(m, f)

def run(path):
    return subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True)

def test_green_run_passes():
    r = run(GOOD); assert r.returncode == 0, r.stdout + r.stderr
    assert "setup" in r.stdout and "hold" in r.stdout

def test_negative_setup_slack_fails(tmp_path):
    m = load(); key = [k for k in m if k.startswith("timing__setup__ws__corner:nom_slow")][0]
    m[key] = -0.1; p = tmp_path / "m.json"; dump(m, p)
    r = run(p); assert r.returncode != 0 and key in r.stdout

def test_route_drc_fails(tmp_path):
    m = load(); m["route__drc_errors"] = 3; p = tmp_path / "m.json"; dump(m, p)
    r = run(p); assert r.returncode != 0 and "FAIL route__drc_errors" in r.stdout

def test_missing_key_fails(tmp_path):
    m = load(); m.pop("timing__hold__ws", None); p = tmp_path / "m.json"; dump(m, p)
    r = run(p); assert r.returncode != 0 and "MISSING timing__hold__ws" in r.stdout

def test_null_value_fails(tmp_path):
    m = load(); m["timing__hold__ws"] = None; p = tmp_path / "m.json"; dump(m, p)
    r = run(p); assert r.returncode != 0 and "timing__hold__ws" in r.stdout

def test_bool_value_fails(tmp_path):
    m = load(); m["route__drc_errors"] = False; p = tmp_path / "m.json"; dump(m, p)
    r = run(p); assert r.returncode != 0 and "FAIL route__drc_errors" in r.stdout
