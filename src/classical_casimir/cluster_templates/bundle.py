"""Standard-library bundle builder; no scientific runtime needed to prepare."""
from pathlib import Path
import hashlib
import json
import math
import re
import shutil
import tarfile

# Maximum Euclidean triangle-edge length / radius of the actual sphere() meshes.
# Geometry regression tests check every supported level against generated vertices.
SPHERE_MESH_SIZES = (1.0514622242382672, .6180339887498949, .3249196962329064,
                     .16464716006392044, .0826039665339507, .04133725597395912,
                     .02067304414009293)


def sphere_mesh_parameters(refinement=None, mesh_size=None):
    """Choose the coarsest supported sphere mesh whose maximum edge is <= h/a."""
    if mesh_size is not None:
        if refinement is not None:
            raise ValueError("choose mesh-size or mesh-level, not both")
        if not math.isfinite(mesh_size) or mesh_size <= 0:
            raise ValueError("mesh-size must be finite and positive (maximum triangle edge h/a)")
        refinement = next((i for i,h in enumerate(SPHERE_MESH_SIZES) if h <= mesh_size),None)
        if refinement is None:
            raise ValueError("mesh-size is below the finest supported h/a="+format(SPHERE_MESH_SIZES[-1],".12g"))
    elif refinement is None:
        refinement = 3
    if type(refinement) is not int or refinement not in range(len(SPHERE_MESH_SIZES)):
        raise ValueError("mesh level must be an integer from 0 to 6")
    return dict(refinement=refinement, mesh_size=SPHERE_MESH_SIZES[refinement],
                triangles_per_sphere=20*4**refinement)

def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def load_luis_profile(root):
    """Resolve site defaults and optional local overrides using only the stdlib."""
    root = Path(root)
    profile = json.loads((root/"configs/luis.json").read_text())
    local = root/"configs/luis.local.json"
    if local.exists():
        override = json.loads(local.read_text())
        if not isinstance(override, dict) or set(override) - set(profile):
            raise ValueError("unknown LUIS profile override")
        profile.update(override)
    if set(profile) != {"environment_home_relative", "miniforge_module", "requirements_file"}:
        raise ValueError("invalid LUIS profile keys")
    for key in ("environment_home_relative", "requirements_file"):
        value = profile[key]
        if (not isinstance(value, str) or not value or Path(value).is_absolute()
                or any(part in ("", ".", "..") for part in value.split("/"))
                or any(c in value for c in "\r\n")):
            raise ValueError("invalid relative path in LUIS profile: " + key)
    if not isinstance(profile["miniforge_module"], str) or not re.fullmatch(r"Miniforge3(?:/[A-Za-z0-9_.+-]+)?", profile["miniforge_module"]):
        raise ValueError("invalid Miniforge module in LUIS profile")
    pins = root/profile["requirements_file"]
    if root.resolve() not in pins.resolve().parents or not pins.is_file():
        raise ValueError("LUIS requirements must be a file inside the checkout")
    return profile


def case_id(case):
    return hashlib.sha256(json.dumps(case, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()[:20]


def read_manifest(path):
    data = path if isinstance(path, dict) else json.loads(Path(path).read_text())
    # Copy before materializing meshes: callers retain their input manifest.
    data = json.loads(json.dumps(data, allow_nan=False))
    if data.get("schema_version") != 1 or not isinstance(data.get("cases"), list):
        raise ValueError("invalid manifest")
    keys = [case_id(case) for case in data["cases"]]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate cases in manifest")
    return data



def prepare(manifest, destination, project_root=None):
    data = read_manifest(manifest)
    dest = Path(destination)
    if dest.is_symlink():
        raise ValueError("bundle destination must not be a symlink")
    dest.mkdir(parents=True, exist_ok=True, mode=0o700)
    dest.chmod(0o700)
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[3]
    profile = load_luis_profile(root)
    # Materialize imported meshes; a cluster bundle must not refer to local paths.
    for case in data["cases"]:
        if "mesh" in case:
            source = Path(case["mesh"])
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            target = dest/"inputs"/(digest[:20]+source.suffix)
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(source, target)
            case["mesh"] = str(target.relative_to(dest))
    atomic_json(dest/"manifest.json", data)
    count = len(data["cases"])
    if count == 0:
        raise ValueError("cannot prepare an empty campaign")
    with tarfile.open(dest/"source.tar.gz", "w:gz") as archive:
        def source_filter(info):
            if "__pycache__" in info.name or ".egg-info" in info.name:
                return None
            if info.issym() or info.islnk():
                raise ValueError("source archives may not contain links: " + info.name)
            return info
        for name in ("src", "pyproject.toml", "README.md", "requirements-cluster.lock"):
            path = root/name
            if not path.exists():
                raise FileNotFoundError(path)
            archive.add(path, arcname=name, filter=source_filter)
    templates = Path(__file__).parent
    for path in templates.iterdir():
        if path.is_file() and path.suffix != ".pyc":
            shutil.copyfile(path, dest/path.name)
    shutil.copyfile(root/profile["requirements_file"], dest/"requirements-cluster.lock")
    atomic_json(dest/"site-profile.json", profile)
    checks = root/"docs/luis/script-checks.md"
    if checks.exists():
        shutil.copyfile(checks, dest/"LUIS-CHECKS.md")
        shutil.copyfile(root/"docs/luis/docs-coverage.md", dest/"luis-docs-coverage.md")
    batches = [dict(index=i//300, start=i, count=min(300, count-i))
               for i in range(0, count, 300)]
    scope = data.get("study_scope", {})
    distance_study = scope.get("kind") == "single-distance-study"
    defaults = dict(cpus_per_task=2, memory_gib=8 if distance_study else 32,
                    wall_minutes=45 if distance_study else 240)
    resources = data.get("execution_resources", defaults)
    for key, low, high in (("cpus_per_task", 1, 8), ("memory_gib", 4, 128), ("wall_minutes", 1, 240)):
        if type(resources[key]) is not int or not low <= resources[key] <= high:
            raise ValueError("invalid resource: " + key)
    cpus, memory, minutes = (resources[k] for k in ("cpus_per_task", "memory_gib", "wall_minutes"))
    atomic_json(dest/"run-parameters.json", dict(study_scope=scope, requested_resources=resources,
                                                excluded_nodes=data.get("excluded_nodes",[])))
    source_hash = hashlib.sha256((dest/"source.tar.gz").read_bytes()).hexdigest()
    immutable = ["manifest.json", "source.tar.gz", "requirements-cluster.lock", "run-parameters.json", "site-profile.json"]
    immutable += [str(p.relative_to(dest)) for p in (dest/"inputs").glob("*") if p.is_file()]
    immutable += [p.name for p in templates.iterdir() if p.is_file() and p.suffix != ".pyc"]
    hashes = {name: hashlib.sha256((dest/name).read_bytes()).hexdigest() for name in immutable}
    expected_versions = dict(line.split("==", 1) for line in
                             (dest/"requirements-cluster.lock").read_text().splitlines()
                             if line and not line.startswith("#"))
    application_sha256 = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (root/"src/classical_casimir").glob("*.py")}
    atomic_json(dest/"bundle.json", dict(policy_version=2, release=source_hash[:20],
                                       tasks=count, batches=batches, sha256=hashes, study_scope=scope,
                                       environment=dict(kind="existing-conda", home_relative=profile["environment_home_relative"]),
                                       expected_versions=expected_versions, application_sha256=application_sha256))
    # Runtime configuration only; no manual attestations or approval flags.
    atomic_json(dest/"operator-review.json", dict(
        release=source_hash[:20], configured_utc=None, miniforge_module=profile["miniforge_module"],
        partition=None, excluded_nodes=data.get("excluded_nodes",[]), pilot_job_ids=[],
        resources=dict(cpus_per_task=cpus, memory_gib=memory, wall_minutes=minutes)))
    (dest/"logs").mkdir(exist_ok=True)
    warning = ("One bounded distance curve after smoke; stop after collection/plotting for review. Resource ceilings are uncalibrated."
               if distance_study else "Uncalibrated ceilings. Production is blocked pending smoke and successful representative cluster pilots. Submit one batch per invocation; no automatic queue filling.")
    atomic_json(dest/"resource-plan.json", dict(tasks=count, batches=batches, cores_per_task=cpus,
                memory_gib=memory, wall_hours_per_task=minutes/60,
                pilot_required=not distance_study, smoke_required=True, study_scope=scope,
                theoretical_cpu_hour_ceiling=count*cpus*minutes/60,
                limits=dict(array_tasks=300), scheduling="Slurm; no array concurrency throttle",
                warning=warning,
                documentation="https://docs.cluster.uni-hannover.de/doku.php/guide/slurm_usage_guide"))
    pilot = root/"output/local/validation.json"
    if pilot.exists():
        measured = json.loads(pilot.read_text())
        baseline = {r["boundary"]:r for r in measured["pairs"] if r["refinement"] == 2}
        estimates = []
        for case in data["cases"]:
            if case["boundary"] not in baseline or "mesh" in case:
                continue
            reference = baseline[case["boundary"]]
            level = case.get("refinement", 1)
            dofs = 40*4**level if case["boundary"] == "dirichlet" else 20*4**level+4
            q = case.get("solver", {}).get("regular_order", 4)
            # Explicit extrapolation, not a fitted or validated cluster timing model.
            seconds = reference["diagnostics"]["seconds"]*(dofs/reference["diagnostics"]["dofs"])**2*(q/4)**4
            seconds *= 5 if case.get("position_check") else 2
            estimates.append(dict(id=case_id(case), model_seconds=seconds))
        atomic_json(dest/"timing-model.json", dict(
            model="Local k=1 pair solve time times dof-ratio squared and (quadrature-order/4)^4; factor 2 for other work, or 5 for position checks.",
            modeled_tasks=len(estimates), model_total_hours=sum(r["model_seconds"] for r in estimates)/3600,
            local_threads=2, requested_cluster_threads=2, tasks=estimates,
            caveat="Illustrative extrapolation only: hardware, JIT, far-field cost, frequency, and iteration counts are not calibrated. No assumed cluster speedup. Measure smoke and representative compute-node jobs before selecting resources."))
    (dest/"README.md").write_text((templates/"BUNDLE-README.md").read_text())
    return dict(tasks=count, destination=str(dest), submitted=False)


def distance_study_manifest(boundary="dirichlet", *, gap_min=.1, gap_max=20., points=150,
                            ka=1., direction=(0., 1., 0.), refinement=None, mesh_size=None,
                            regular_order=6, singular_order=6, rtol=1e-9, maxiter=300,
                            memory_gib=8.):
    """One fixed-resolution curve; further numerical studies require review."""
    if boundary not in ("dirichlet", "neumann"):
        raise ValueError("boundary must be dirichlet or neumann")
    if not all(math.isfinite(x) for x in (gap_min, gap_max, ka, rtol, memory_gib)):
        raise ValueError("distance-study parameters must be finite")
    if not 0 < gap_min < gap_max or ka <= 0:
        raise ValueError("require 0 < gap-min < gap-max and ka > 0")
    if type(points) is not int or not 2 <= points < 1000000:
        raise ValueError("points must be an integer from 2 to 999999")
    mesh = sphere_mesh_parameters(refinement,mesh_size)
    refinement = mesh["refinement"]
    if any(type(q) is not int or q not in range(1, 21) for q in (regular_order, singular_order)):
        raise ValueError("quadrature orders must be integers from 1 to 20")
    if not 0 < rtol < 1 or type(maxiter) is not int or maxiter < 1 or not 4 <= memory_gib <= 128:
        raise ValueError("invalid tolerance, maximum iterations or memory budget (4 to 128 GiB)")
    if len(direction) != 3 or not all(math.isfinite(x) for x in direction):
        raise ValueError("direction must be a finite nonzero 3-vector")
    norm = math.hypot(*direction)
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("direction must be a finite nonzero 3-vector")
    direction = [float(x/norm) for x in direction]
    gap_min, gap_max, ka = float(gap_min), float(gap_max), float(ka)
    gaps = [gap_min + (gap_max-gap_min)*(i/(points-1)) for i in range(points)]
    gaps[0], gaps[-1] = gap_min, gap_max
    if any(a >= b for a,b in zip(gaps, gaps[1:])):
        raise ValueError("gap range is too narrow to represent distinct sample points")
    cases = []
    for gap in gaps:
        cases.append(dict(boundary=boundary, k=ka, gap=gap, refinement=refinement,
                          direction=direction, isolated=False, force_only=True,
                          solver=dict(regular_order=regular_order, singular_order=singular_order,
                                      rtol=rtol, maxiter=maxiter, memory_gib=float(memory_gib))))
    return dict(schema_version=1, name="equal-spheres-"+boundary+"-distance-ka"+format(ka,"g"),
                status="prepared-not-run", study_scope=dict(
                    kind="single-distance-study", boundary=boundary, ka=ka,
                    direction=direction, gaps=gaps, samples=points,
                    gap_min=gap_min, gap_max=gap_max, sampling="linear", **mesh,
                    requested_mesh_size=None if mesh_size is None else float(mesh_size),
                    regular_order=regular_order, singular_order=singular_order,
                    rtol=rtol, maxiter=maxiter, memory_gib=float(memory_gib), convergence_checks=False,
                    stop_for_review=True), cases=cases)


def survey_manifest():
    cases = []
    for bc in ("dirichlet", "neumann"):
        for k in (.5, 1., 2., 5.):
            for i in range(1, 81):
                for level in (2, 3, 4):
                    cases.append(dict(boundary=bc, k=k, gap=round(i/10, 1), refinement=level,
                                      direction=[0., 1., 0.], isolated=True,
                                      solver=dict(regular_order=6, singular_order=6, memory_gib=32.)))
    # Parallel and oblique checks have the same mesh-refinement protocol.
    for bc in ("dirichlet", "neumann"):
        for k in (1., 5.):
            for gap in (.5, 2., 5.):
                for direction in ([1., 0., 0.], [2**-.5, 2**-.5, 0.]):
                    for level in (2, 3, 4):
                        cases.append(dict(boundary=bc, k=k, gap=gap, refinement=level,
                                          direction=direction, isolated=True,
                                          solver=dict(regular_order=6, singular_order=6, memory_gib=32.)))
    # Quadrature and displacement-step checks at well-separated representative points.
    for bc in ("dirichlet", "neumann"):
        for k in (1., 5.):
            cases.append(dict(boundary=bc, k=k, gap=2., refinement=3, direction=[0., 1., 0.],
                              position_check=True, position_axes=[0], translation_step=.02,
                              solver=dict(regular_order=8, singular_order=8, memory_gib=32.)))
    # Independent assembly-quadrature refinement on the finest spatial level.
    for case in list(cases):
        if case.get("refinement") == 4 and not case.get("position_check"):
            options = dict(case["solver"], regular_order=8, singular_order=8)
            cases.append(dict(case, solver=options))
    return dict(schema_version=1, name="equal-spheres-plane-wave-survey", status="prepared-not-run", cases=cases)

