"""Reproducible cases, atomic results, conservative collection, and sign brackets."""
from pathlib import Path
from dataclasses import asdict
import csv
import hashlib
import json
import math
import os
import platform
import time
import numpy as np
from .model import PlaneWave, SolverOptions
from .geometry import two_spheres, sphere, SurfaceMesh
from .solver import solve
from .forces import momentum_force, position_force, interaction_forces
from .backend import versions
from .quadrature import sphere_quadrature


def plain(value):
    if isinstance(value, np.ndarray):
        return plain(value.tolist())
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, complex):
        return [value.real, value.imag]
    if isinstance(value, dict):
        return {str(k):plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(x) for x in value]
    return value


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(plain(data), indent=2, sort_keys=True, allow_nan=False)+"\n")
    os.replace(temp, path)


def case_id(case):
    return hashlib.sha256(json.dumps(case, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()[:20]


def source_digest():
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode()); digest.update(path.read_bytes())
    return digest.hexdigest()


def read_manifest(path):
    data = json.loads(Path(path).read_text())
    if data.get("schema_version") != 1 or not isinstance(data.get("cases"), list):
        raise ValueError("invalid manifest")
    ids = [case_id(case) for case in data["cases"]]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate cases in manifest")
    return data


def complete_result(folder, case=None, code=None, runtime=None):
    """JSON is the completion marker; all required artifacts must match hashes."""
    folder = Path(folder)
    try:
        data = json.loads((folder/"result.json").read_text())
        if data.get("status") != "computed" or data.get("schema_version") != 1:
            return False
        if case is not None and data["case"] != case:
            return False
        if code is not None and data["source_sha256"] != code:
            return False
        if runtime is not None and data["versions"] != runtime:
            return False
        if case is not None and "mesh" in case:
            if hashlib.sha256(Path(case["mesh"]).read_bytes()).hexdigest() != data.get("input_mesh_sha256"):
                return False
        for name, digest in data["artifact_sha256"].items():
            if name not in ("arrays.npz", "mesh.npz"):
                return False
            if hashlib.sha256((folder/name).read_bytes()).hexdigest() != digest:
                return False
        return set(data["artifact_sha256"]) == {"arrays.npz", "mesh.npz"}
    except (OSError, ValueError, KeyError, TypeError):
        return False


def run_case(case, output, resume=True):
    output = Path(output)
    folder = output/case_id(case)
    runtime, code = versions(), source_digest()
    if resume and complete_result(folder, case, code, runtime):
        return dict(json.loads((folder/"result.json").read_text()), resumed=True)
    folder.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        if "mesh" in case:
            mesh = SurfaceMesh.load(case["mesh"])
        elif case.get("geometry", "two_spheres") == "sphere":
            mesh = sphere(case.get("radius", 1.), case.get("center", [0, 0, 0]), case.get("refinement", 1))
        elif case.get("geometry", "two_spheres") == "two_spheres":
            mesh = two_spheres(case.get("gap", 1.), case.get("radius", 1.), case.get("refinement", 1))
        else:
            raise ValueError("unsupported geometry; supply a mesh for arbitrary shapes")
        amplitude = case.get("amplitude", [1., 0.])
        amplitude = complex(*amplitude) if isinstance(amplitude, list) else amplitude
        wave = PlaneWave(case["k"], tuple(case.get("direction", [0, 1, 0])), amplitude)
        options = SolverOptions(**case.get("solver", {}))
        solution = solve(mesh, wave, case["boundary"], options)
        forces = solution.component_forces()
        force_only = case.get("force_only", False)
        center = mesh.vertices.mean(axis=1)[:, None]
        extent = float(np.max(np.linalg.norm(mesh.vertices-center, axis=0)))
        order = int(case.get("angular_order", max(16, np.ceil(2*wave.k*extent+12))))
        momentum = None if force_only else momentum_force(solution, order)
        angular_refined = None if force_only else momentum_force(solution, order+4)
        data = dict(schema_version=1, case=case, id=case_id(case), status="computed", validation="unassessed",
                    source_sha256=code, versions=runtime, host=platform.node(),
                    force_convention="Helmholtz force -integral(T n); n points into exterior",
                    component_labels=mesh.components, forces=forces, total_force=forces.sum(axis=0),
                    momentum=momentum, momentum_refined=angular_refined,
                    momentum_difference=None if force_only else forces.sum(axis=0)-angular_refined["force"],
                    angular_difference=None if force_only else abs(momentum["force"]-angular_refined["force"]),
                    diagnostics=solution.diagnostics)
        if force_only:
            data["assessment_scope"] = "Fixed-resolution force samples only; no convergence or independent force-identity checks."
        if "mesh" in case:
            data["input_mesh_sha256"] = hashlib.sha256(Path(case["mesh"]).read_bytes()).hexdigest()
        if not force_only and case.get("isolated", True):
            data.update(interaction_forces(solution, options))
        if len(forces) == 2 and "mesh" not in case:
            data["separation_force"] = float((forces[1, 0]-forces[0, 0])/2)
            if "interaction_forces" in data:
                delta = data["interaction_forces"]
                data["interaction_separation_force"] = float((delta[1, 0]-delta[0, 0])/2)
        if not force_only and case.get("position_check", False):
            data["position_check"] = position_force(solution, int(case.get("position_component", mesh.components[-1])),
                                                      case.get("translation_step", 0.01), order, options,
                                                      axes=tuple(case.get("position_axes", [0])))
        temp = folder/f"arrays.{os.getpid()}.npz"
        arrays = dict(forces=forces, coefficients=solution.density.coefficients)
        if not force_only:
            theta, weights = sphere_quadrature(order)
            arrays.update(far_field=solution.far_field(theta), directions=theta, weights=weights)
        np.savez_compressed(temp, **arrays)
        os.replace(temp, folder/"arrays.npz")
        temp = folder/f"mesh.{os.getpid()}.npz"
        mesh.save(temp); os.replace(temp, folder/"mesh.npz")
        data["seconds"] = time.monotonic()-started
        data["artifact_sha256"] = {name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in ("arrays.npz", "mesh.npz")}
        atomic_json(folder/"result.json", data)
        return plain(data)
    except Exception as error:
        atomic_json(folder/"failure.json", dict(case=case, error=repr(error), seconds=time.monotonic()-started))
        raise


def collect(manifest, output, destination):
    manifest = read_manifest(manifest) if not isinstance(manifest, dict) else manifest
    output, destination = Path(output), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    rows, pending, invalid = [], [], []
    for case in manifest["cases"]:
        key = case_id(case); folder = output/key
        if not complete_result(folder, case):
            (invalid if (folder/"result.json").exists() else pending).append(key)
            continue
        data = json.loads((folder/"result.json").read_text())
        rows.append(dict(id=key, boundary=case["boundary"], k=case["k"], gap=case.get("gap"),
                         refinement=case.get("refinement"), regular_order=case.get("solver", {}).get("regular_order", 4),
                         direction=json.dumps(case.get("direction", [0, 1, 0])),
                         separation_force=data.get("separation_force"), seconds=data["seconds"],
                         total_fx=data["total_force"][0], total_fy=data["total_force"][1], total_fz=data["total_force"][2],
                         momentum_mismatch=None if data["momentum_difference"] is None else float(np.linalg.norm(data["momentum_difference"])),
                         angular_difference=None if data["angular_difference"] is None else float(np.linalg.norm(data["angular_difference"])),
                         source_sha256=data["source_sha256"], backend=data["versions"]["bempp-cl"]))
    if rows:
        with (destination/"summary.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
    # Never infer missing data from plots or smooth/interpolate across missing cases.
    sources = sorted({row["source_sha256"] for row in rows})
    backends = sorted({row["backend"] for row in rows})
    status = dict(expected=len(manifest["cases"]), computed=len(rows), pending=pending, invalid=invalid,
                  all_cases_computed=not pending and not invalid,
                  source_digests=sources, backends=backends,
                  provenance_consistent=len(sources) <= 1 and len(backends) <= 1,
                  full_study_complete=False,
                  validation="Collection completeness only. Scientific validation and study completion require review of refinement and independent identities.")
    atomic_json(destination/"coverage.json", status)
    return status


def sign_brackets(samples):
    """Only bracket signs whose supplied empirical errors exclude zero.

    samples = [(gap, force, error), ...]; this does not certify root uniqueness.
    """
    samples = sorted(samples)
    brackets = []
    for left, right in zip(samples[:-1], samples[1:]):
        if min(left[2], right[2]) < 0:
            raise ValueError("negative uncertainty")
        if abs(left[1]) > left[2] and abs(right[1]) > right[2] and left[1]*right[1] < 0:
            brackets.append([left[0], right[0]])
    return brackets

