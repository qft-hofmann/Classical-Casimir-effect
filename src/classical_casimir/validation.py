"""A small measured pilot, with independent analytic and conservation checks."""
from pathlib import Path
from dataclasses import asdict
import time
import numpy as np
from .model import PlaneWave, SolverOptions
from .geometry import sphere, two_spheres, SurfaceMesh
from .solver import solve
from .analytic import AnalyticSphere
from .forces import momentum_force, position_force
from .quadrature import sphere_quadrature
from .study import atomic_json, source_digest
from .backend import versions


def relative(a, b):
    return float(np.linalg.norm(np.asarray(a)-b)/max(np.linalg.norm(b), 1e-30))


def run_validation(destination):
    dest = Path(destination); dest.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    wave = PlaneWave(1.)
    theta, weights = sphere_quadrature(12)
    points = np.array([[2.1, 0, 0.2], [0, 2.3, 0.1], [0, 0, 2.4]])
    results = dict(schema_version=1, source_sha256=source_digest(), versions=versions(),
                   status="running", scope="Local pilot; full survey pending", spheres=[], pairs=[],
                   invariances=[], resonances=[], checks=[])
    def checkpoint():
        results["seconds"] = time.monotonic()-start
        atomic_json(dest/"validation.json", results)
    def check(name, passed, detail):
        results["checks"].append(dict(name=name, passed=bool(passed), detail=detail)); checkpoint()
    for bc in ("dirichlet", "neumann"):
        exact = AnalyticSphere(wave, bc)
        exact_force = exact.boundary_force()
        exact_momentum = momentum_force(exact, 24)["force"]
        check(f"{bc}: analytic stress/momentum", relative(exact_force, exact_momentum) < 1e-11,
              dict(stress=exact_force, momentum=exact_momentum))
        solutions = []
        for level in (1, 2, 3):
            solution = solve(sphere(refinement=level), wave, bc)
            solutions.append(solution)
            force = solution.component_forces()[0]
            mom = momentum_force(solution, 12)
            refined = momentum_force(solution, 16)
            row = dict(boundary=bc, refinement=level, force=force, exact_force=exact_force,
                       force_relative_error=relative(force, exact_force),
                       far_field_relative_error=relative(solution.far_field(theta), exact.far_field(theta)),
                       near_field_relative_error=relative(solution.scattered_field(points), exact.scattered_field(points)),
                       momentum=mom, momentum_refined=refined,
                       momentum_relative_error=relative(mom["force"], exact_force),
                       angular_difference=float(np.linalg.norm(mom["force"]-refined["force"])),
                       diagnostics=solution.diagnostics)
            results["spheres"].append(row); checkpoint()
            print(f"sphere {bc} level={level} force_error={row['force_relative_error']:.4g}", flush=True)
        rows = [row for row in results["spheres"] if row["boundary"] == bc]
        check(f"{bc}: sphere convergence", all(rows[i+1]["force_relative_error"] < rows[i]["force_relative_error"] for i in range(2)),
              [row["force_relative_error"] for row in rows])
        check(f"{bc}: normalization/sign", rows[-1]["force_relative_error"] < .2,
              "Coarse pilot threshold only; measured errors, not this threshold, describe accuracy.")
        base = solutions[1]
        f0 = base.component_forces()[0]
        shifted = solve(base.mesh.translated([.17, -.11, .23]), wave, bc)
        scaled = solve(base.mesh, PlaneWave(1., amplitude=2-1j), bc)
        rotation = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
        rotated = solve(SurfaceMesh(rotation@base.mesh.vertices, base.mesh.elements, base.mesh.labels),
                        PlaneWave(1., tuple(rotation@np.asarray(wave.direction))), bc)
        inv = dict(boundary=bc, translation_error=relative(shifted.component_forces()[0], f0),
                   amplitude_error=relative(scaled.component_forces()[0], 5*f0),
                   rotation_error=relative(rotated.component_forces()[0], rotation@f0))
        results["invariances"].append(inv)
        check(f"{bc}: invariances", max(inv[k] for k in ("translation_error", "amplitude_error", "rotation_error")) < 1e-6, inv)
        for level in (2, 3):
            pair = solve(two_spheres(gap=2., refinement=level), wave, bc)
            force = pair.component_forces()
            mom = momentum_force(pair, 20)
            row = dict(boundary=bc, refinement=level, gap=2., forces=force,
                       separation_force=float((force[1, 0]-force[0, 0])/2), momentum=mom,
                       total_momentum_difference=float(np.linalg.norm(force.sum(axis=0)-mom["force"])),
                       diagnostics=pair.diagnostics)
            row["position"] = position_force(pair, 2, step=.02, order=20, axes=(0,))
            row["position_discrepancy"] = float(abs(row["position"]["force"][0]-force[1, 0]))
            if level == 3:
                quad = solve(pair.mesh, wave, bc, SolverOptions(regular_order=6, singular_order=6))
                row["quadrature_force_difference"] = np.abs(quad.component_forces()-force)
                row["quadrature_diagnostics"] = quad.diagnostics
            results["pairs"].append(row); checkpoint()
            scale = max(np.linalg.norm(force), 1.)
            defect = max(abs(force[0, 0]+force[1, 0]), abs(force[0, 1]-force[1, 1]), abs(force[:, 2]).max())
            check(f"{bc}: pair symmetry level {level}", defect < 1e-6*scale, defect)
            print(f"pair {bc} level={level} separation_force={row['separation_force']:.6g}", flush=True)
        pair_rows = [row for row in results["pairs"] if row["boundary"] == bc]
        check(f"{bc}: force-identity refinement", pair_rows[1]["position_discrepancy"] < pair_rows[0]["position_discrepancy"]
              and pair_rows[1]["total_momentum_difference"] < pair_rows[0]["total_momentum_difference"],
              dict(position_discrepancies=[r["position_discrepancy"] for r in pair_rows],
                   momentum_discrepancies=[r["total_momentum_difference"] for r in pair_rows]))
        # These are real frequencies where a pure single-layer formulation can fail.
        resonant_k = np.pi if bc == "dirichlet" else 2.0815759778181
        near_res = solve(sphere(refinement=1), PlaneWave(resonant_k), bc)
        ref = AnalyticSphere(near_res.wave, bc)
        error = relative(near_res.far_field(theta), ref.far_field(theta))
        results["resonances"].append(dict(boundary=bc, k=resonant_k, far_field_relative_error=error,
                                          diagnostics=near_res.diagnostics))
        check(f"{bc}: interior-resonance smoke", error < .5, error)
    results["status"] = "passed" if all(x["passed"] for x in results["checks"]) else "failed"
    results["accuracy_note"] = "Empirical finite-refinement evidence, not certified error bounds. No full separation sweep has been run."
    checkpoint()
    return results

