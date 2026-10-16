import json, subprocess, sys, pathlib
HERE = pathlib.Path(__file__).parent
SCRIPT = HERE.parent / "test" / "check_metrics.py"
GOOD = HERE / "data" / "metrics_core_v01.json"

def run(path):
    return subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True)

def test_green_run_passes():
    r = run(GOOD); assert r.returncode == 0, r.stdout + r.stderr
    assert "setup" in r.stdout and "hold" in r.stdout

def test_negative_setup_slack_fails(tmp_path):
    m = json.load(open(GOOD)); key = [k for k in m if k.startswith("timing__setup__ws__corner:nom_slow")][0]
    m[key] = -0.1; p = tmp_path / "m.json"; json.dump(m, open(p, "w"))
    r = run(p); assert r.returncode != 0 and key in r.stdout

def test_route_drc_fails(tmp_path):
    m = json.load(open(GOOD)); m["route__drc_errors"] = 3; p = tmp_path / "m.json"; json.dump(m, open(p, "w"))
    r = run(p); assert r.returncode != 0 and "FAIL route__drc_errors" in r.stdout

def test_missing_key_fails(tmp_path):
    m = json.load(open(GOOD)); m.pop("timing__hold__ws", None); p = tmp_path / "m.json"; json.dump(m, open(p, "w"))
    r = run(p); assert r.returncode != 0 and "MISSING timing__hold__ws" in r.stdout
