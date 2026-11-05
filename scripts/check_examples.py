"""Check the published scientific exports without BEM or cluster access."""
import csv
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(root=ROOT):
    curve = root/"examples/dirichlet-ka1"
    provenance = json.loads((curve/"provenance.json").read_text())
    for name, expected in provenance["files_sha256"].items():
        assert hashlib.sha256((curve/name).read_bytes()).hexdigest() == expected, name
    rows = json.loads((curve/"samples.json").read_text())
    cases = json.loads((curve/"manifest.json").read_text())["cases"]
    with (curve/"forces.csv").open() as stream:
        csv_rows = list(csv.DictReader(stream))
    assert len(rows) == len(cases) == len(csv_rows) == provenance["samples"] == 150
    gaps = [case["gap"] for case in cases]
    assert gaps == sorted(set(gaps)) and gaps[0] == .1 and gaps[-1] == 20.
    assert all(math.isclose(b-a,19.9/149,abs_tol=1e-13) for a,b in zip(gaps,gaps[1:]))
    for row, case, values in zip(rows, cases, csv_rows):
        assert row["case"] == case
        assert row["id"] == hashlib.sha256(json.dumps(case,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()[:20]
        assert row["source_sha256"] == provenance["source_sha256"] and row["versions"] == provenance["versions"]
        assert case["boundary"] == "dirichlet" and case["k"] == 1. and case["refinement"] == 3
        assert case["direction"] == [0.,1.,0.] and case["force_only"] and not case["isolated"]
        assert case["solver"]["regular_order"] == case["solver"]["singular_order"] == 6
        assert set(row["artifact_sha256"]) == {"arrays.npz","mesh.npz"}
        force = (row["forces"][1][0]-row["forces"][0][0])/2
        assert math.isfinite(force) and force == row["separation_force"]
        assert [float(v) for v in values.values()] == [case["gap"],*row["forces"][0],*row["forces"][1],force]
    pilot = root/"examples/pilot"
    provenance_pilot = json.loads((pilot/"provenance.json").read_text())
    for name, key in (("validation.json","validation_sha256"),("budget.json","budget_sha256")):
        assert hashlib.sha256((pilot/name).read_bytes()).hexdigest() == provenance_pilot[key]
    data = json.loads((pilot/"validation.json").read_text())
    assert data["status"] == "passed" and all(item["passed"] for item in data["checks"])
    source_pilot = json.loads((pilot/"source-files.json").read_text())["files"]
    for name in ("analytic.py","backend.py","forces.py","geometry.py","model.py","quadrature.py","solver.py"):
        digest = hashlib.sha256((root/"src/classical_casimir"/name).read_bytes()).hexdigest()
        assert digest == source_pilot[name] == provenance["source_files_sha256"][name], name
    return {"curve_samples":len(rows),"pilot_checks":len(data["checks"]),"numerical_kernels_unchanged":True}


if __name__ == "__main__":
    print(json.dumps(check(),indent=2))
