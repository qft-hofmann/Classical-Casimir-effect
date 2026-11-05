"""Refinement envelopes and plots that do not silently fill missing results."""
from collections import defaultdict
from pathlib import Path
import json
import numpy as np
from .study import read_manifest, complete_result, case_id, sign_brackets, atomic_json


def refinement_groups(manifest, output):
    data = read_manifest(manifest)
    groups = defaultdict(list)
    for case in data["cases"]:
        folder = Path(output)/case_id(case)
        if not complete_result(folder, case):
            continue
        result = json.loads((folder/"result.json").read_text())
        if result.get("separation_force") is None:
            continue
        # All options except mesh level must agree for a spatial convergence sequence.
        base = {key:value for key, value in case.items() if key != "refinement"}
        key = json.dumps(dict(base=base, source=result["source_sha256"], versions=result["versions"]), sort_keys=True)
        groups[key].append((case, result))
    return groups


def envelopes(manifest, output):
    rows = []
    groups = refinement_groups(manifest, output)
    for group in groups.values():
        group.sort(key=lambda x:x[0]["refinement"])
        case, result = group[-1]
        consecutive = len(group) >= 3 and [x[0]["refinement"] for x in group[-3:]] == list(range(case["refinement"]-2, case["refinement"]+1))
        mesh_error, quadrature_error, error = None, None, None
        if consecutive:
            f = [x[1]["separation_force"] for x in group[-3:]]
            mesh_error = max(abs(f[2]-f[1]), abs(f[1]-f[0]))
            base = {k:v for k, v in case.items() if k != "solver"}
            q = case.get("solver", {})
            for candidates in groups.values():
                for c, r in candidates:
                    if ({k:v for k, v in c.items() if k != "solver"} == base
                        and r["source_sha256"] == result["source_sha256"] and r["versions"] == result["versions"]
                        and c.get("solver", {}).get("regular_order", 4) > q.get("regular_order", 4)
                        and c.get("solver", {}).get("singular_order", 4) > q.get("singular_order", 4)):
                        difference = abs(r["separation_force"]-result["separation_force"])
                        quadrature_error = max(quadrature_error or 0, difference)
            if quadrature_error is not None and result["angular_difference"] is not None:
                error = mesh_error+quadrature_error+float(np.linalg.norm(result["angular_difference"]))
        rows.append(dict(case=case, force=result["separation_force"], empirical_error=error,
                         mesh_error=mesh_error, quadrature_error=quadrature_error,
                         source_sha256=result["source_sha256"], versions=result["versions"],
                         sign="unresolved" if error is None or abs(result["separation_force"]) <= error else
                         ("repulsive" if result["separation_force"] > 0 else "attractive")))
    return rows


def refinement_manifest(manifest, output):
    original = read_manifest(manifest)
    groups = defaultdict(list)
    for row in envelopes(manifest, output):
        if row["empirical_error"] is None:
            continue
        case = row["case"]
        base = {k:v for k, v in case.items() if k not in ("gap", "refinement")}
        key = json.dumps(dict(base=base, source=row["source_sha256"], versions=row["versions"]), sort_keys=True)
        groups[key].append(row)
    cases = []
    existing = {case_id(case) for case in original["cases"]}
    for group in groups.values():
        samples = [(row["case"]["gap"], row["force"], row["empirical_error"]) for row in group]
        for left, right in sign_brackets(samples):
            if right-left <= .01:
                continue
            base = group[0]["case"]
            for level in range(base["refinement"]-2, base["refinement"]+1):
                case = dict(base, gap=round((left+right)/2, 10), refinement=level)
                if case_id(case) not in existing:
                    cases.append(case); existing.add(case_id(case))
            fine = dict(base, gap=round((left+right)/2, 10))
            fine["solver"] = dict(base.get("solver", {}),
                                  regular_order=base.get("solver", {}).get("regular_order", 4)+2,
                                  singular_order=base.get("solver", {}).get("singular_order", 4)+2)
            if case_id(fine) not in existing:
                cases.append(fine); existing.add(case_id(fine))
    return dict(schema_version=1, name="empirical-sign-bracket-midpoints", cases=cases,
                warning="Prepared midpoint cases only. Envelopes measure mesh variation, not rigorous error or root uniqueness.")


def plot_results(manifest, output, destination):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    dest = Path(destination); dest.mkdir(parents=True, exist_ok=True)
    rows = envelopes(manifest, output)
    if not rows:
        atomic_json(dest/"plot-status.json", dict(status="no computed separation forces", plots=[]))
        return dict(plots=[], status="no computed separation forces")
    curves = defaultdict(list)
    for row in rows:
        case = row["case"]
        key = json.dumps({k:v for k, v in case.items() if k not in ("gap", "refinement")}, sort_keys=True)
        curves[key].append(row)
    fig, ax = plt.subplots(figsize=(7, 4))
    for key, curve in curves.items():
        curve.sort(key=lambda r:r["case"]["gap"])
        case = curve[0]["case"]
        x = np.array([r["case"]["gap"] for r in curve])
        y = np.array([r["force"] for r in curve]) / case["k"]**2
        ax.scatter(x, y, s=12, label=f"{case['boundary']}, ka={case['k']:g}")
        valid = [r for r in curve if r["empirical_error"] is not None]
        if valid:
            ax.errorbar([r["case"]["gap"] for r in valid], [r["force"]/case["k"]**2 for r in valid],
                        yerr=[r["empirical_error"]/case["k"]**2 for r in valid], fmt="none", alpha=.5)
    ax.axhline(0, color="black", lw=.6)
    title = ("Fixed-resolution distance sweep; convergence not assessed"
             if all(row["case"].get("force_only") for row in rows)
             else "Computed samples; bars show empirical refinement variation")
    ax.set(xlabel="surface gap g/a", ylabel="Helmholtz separation force", title=title)
    ax.legend(fontsize=7); fig.tight_layout()
    fig.savefig(dest/"separation-forces.png", dpi=180); plt.close(fig)
    atomic_json(dest/"envelopes.json", rows)
    return dict(plots=[str(dest/"separation-forces.png")], computed_samples=len(rows),
                note="No lines across missing cases; unrefined signs are unresolved.")

