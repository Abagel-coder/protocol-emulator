#!/usr/bin/env python3
"""Fail the gds workflow on a bad hardening result. The Tiny Tapeout flow goes green on negative
slack, so this is the project's only timing check: usage `check_metrics.py runs/wokwi/final/metrics.json`.
Prints every checked value; checks every key and exits 1 if any failed (violation, missing key or non-numeric value)."""
import json, sys

CHECKS = [  # (key, predicate, description)
    ("timing__setup__ws__corner:nom_slow_1p08V_125C", lambda v: v >= 0, "worst setup slack, slow corner, ns"),
    ("timing__setup__ws__corner:nom_typ_1p20V_25C",   lambda v: v >= 0, "worst setup slack, typical corner, ns"),
    ("timing__hold__ws",                               lambda v: v >= 0, "worst hold slack, ns"),
    ("route__drc_errors",                              lambda v: v == 0, "detailed-routing DRC errors"),
    ("antenna__violating__nets",                       lambda v: v == 0, "antenna-violating nets"),
    ("design__lvs_error__count",                       lambda v: v == 0, "LVS errors"),
]

def main(path):
    with open(path) as f:
        m = json.load(f)
    bad = 0
    for key, ok, what in CHECKS:
        if key not in m:
            print(f"MISSING {key} ({what})"); bad += 1; continue
        v = m[key]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v != v:
            print(f"FAIL {key} = {v!r} ({what}): not a number"); bad += 1; continue
        verdict = "ok" if ok(v) else "FAIL"
        print(f"{verdict:4} {key} = {v} ({what})"); bad += verdict == "FAIL"
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
