"""Standalone LUIS preflight. Standard library only; run with /usr/bin/python3 -I -B.

The cluster-provided storage variables are trusted configuration, not a security
sandbox. Checks prevent accidental writes; concurrent hostile path replacement is
outside their scope. See LUIS-CHECKS.md for manual and conditional obligations.
"""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys


def require(ok, message):
    if not ok:
        raise ValueError(message)


def require_login_host():
    # Match the local node name, not reverse DNS: the public SSH endpoint does
    # not specify the internal hostname/domain returned inside a login session.
    host = socket.gethostname()
    require(re.fullmatch(r"login[0-9]+", host.split(".")[0]) is not None,
            "run on a LUIS login node (login<number>), never a transfer/compute node; "
            "observed hostname: " + repr(host))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inside(path, root):
    return path != root and root in path.parents


def overlaps(a, b):
    return a == b or inside(a, b) or inside(b, a)


def run(args):
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=60).stdout


def safe_tree(path):
    # Do not follow links while walking. Even links to another approved directory
    # are rejected: logs/results must not alias another task or another bundle.
    if path.exists():
        for base, dirs, files in os.walk(path, followlinks=False):
            for name in dirs + files:
                p = Path(base) / name
                require(not p.is_symlink(), "symlink in bundle: " + str(p))
                require(not p.is_file() or p.stat().st_nlink == 1,
                        "hard-linked file in bundle: " + str(p))


def locations(bundle, private=True):
    roots = {}
    for name in ("BIGWORK", "HOME", *(["SOFTWARE"] if os.environ.get("SOFTWARE") else [])):
        value = os.environ.get(name, "")
        require(value.startswith("/"), name + " must be an absolute existing directory")
        root = Path(value).resolve(strict=True)
        require(root.is_dir() and root != Path("/"), "unsafe " + name)
        roots[name] = root
    for a, b in (("BIGWORK", "HOME"), ("SOFTWARE", "HOME"), ("BIGWORK", "SOFTWARE")):
        if a in roots and b in roots:
            require(not overlaps(roots[a], roots[b]), a + " overlaps " + b)
    if os.environ.get("PROJECT"):
        project = Path(os.environ["PROJECT"])
        require(project.is_absolute(), "PROJECT must be absolute")
        # PROJECT need not be mounted on compute nodes.
        project = project.resolve()
        for name in ("BIGWORK", "SOFTWARE"):
            if name in roots:
                require(not overlaps(roots[name], project), name + " overlaps PROJECT")
    original = Path(bundle).absolute()
    bundle = original.resolve(strict=True)
    require(inside(bundle, roots["BIGWORK"]), "bundle must be below BIGWORK")
    require(not any(c in str(bundle) for c in "\n\r,%"), "unsafe Slurm path characters")
    # Reject symlinks in the path below BIGWORK as well as within the bundle.
    current = original
    while current != current.parent and current != roots["BIGWORK"]:
        require(not current.is_symlink(), "symlink in bundle path: " + str(current))
        current = current.parent
    require(bundle.stat().st_uid == os.getuid(), "bundle must be owned by the current user")
    if private:
        require(bundle.stat().st_mode & 0o077 == 0, "bundle must be private (chmod 700)")
    return bundle, roots


def context(bundle):
    bundle, roots = locations(bundle)
    # Only inspect fixed entry points here. Walking the whole result tree in
    # every array element would itself create avoidable Lustre metadata load.
    for p in bundle.iterdir():
        require(not p.is_symlink(), "symlink in bundle: " + str(p))
        require(not p.is_file() or p.stat().st_nlink == 1, "hard-linked bundle file: " + str(p))
    cfg = json.loads((bundle / "bundle.json").read_text())
    require(cfg["policy_version"] == 2, "unsupported policy version; regenerate this bundle")
    for name, expected in cfg["sha256"].items():
        p = (bundle / name).resolve(strict=True)
        require(inside(p, bundle) and digest(p) == expected, "bundle integrity failed: " + name)
        if p.suffix in (".sh", ".slurm"):
            require(b"\r" not in p.read_bytes(), "CRLF script: " + name)
    user = run(["id", "-un"]).strip()
    require(re.fullmatch(r"[A-Za-z0-9_.-]+", user), "unsafe username")
    selected = cfg.get("environment", {})
    relative = selected.get("home_relative")
    require(selected.get("kind") == "existing-conda" and isinstance(relative, str)
            and relative and not Path(relative).is_absolute()
            and all(part not in ("", ".", "..") for part in relative.split("/"))
            and not any(c in relative for c in "\r\n"), "invalid existing environment path")
    prefix = roots["HOME"] / relative
    require(inside(prefix.resolve(), roots["HOME"]), "existing environment escapes HOME")
    # Reuse this user-selected installation read-only, without walking/copying it.
    require(not (bundle / "environment.json").is_symlink(), "environment record is a link")
    for name in ("runtime", "logs", "source", "results", "smoke-results"):
        require(not (bundle / name).is_symlink(), "unsafe output directory: " + name)
    for parent, names in ((bundle / "runtime", ("cache", "config", "data", "state", "run", "tmp", "numba", "matplotlib", "pip", "uv", "conda-pkgs", "conda-envs")),):
        for name in names:
            require(not (parent / name).is_symlink(), "unsafe cache/config path")
    return bundle, cfg, prefix, user


def environment(bundle, cfg, prefix):
    runtime = bundle / "runtime"
    paths = {
        "CASIMIR_ENV": prefix, "CASIMIR_BUNDLE": bundle,
        "CONDA_ENVS_PATH": runtime / "conda-envs", "CONDA_PKGS_DIRS": runtime / "conda-pkgs",
        "CONDARC": bundle / "condarc", "PIP_CONFIG_FILE": "/dev/null",
        "PIP_CACHE_DIR": runtime / "pip", "UV_CACHE_DIR": runtime / "uv",
        "XDG_CACHE_HOME": runtime / "cache", "XDG_CONFIG_HOME": runtime / "config",
        "XDG_DATA_HOME": runtime / "data", "XDG_STATE_HOME": runtime / "state",
        "XDG_RUNTIME_DIR": runtime / "run", "TMPDIR": runtime / "tmp",
        "TMP": runtime / "tmp", "TEMP": runtime / "tmp",
        "NUMBA_CACHE_DIR": runtime / "numba", "MPLCONFIGDIR": runtime / "matplotlib",
        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "CONDA_REGISTER_ENVS": "false", "CONDA_NUMBER_CHANNEL_NOTICES": "0",
        "CONDA_REPORT_ERRORS": "false", "CONDA_AUTO_UPDATE_CONDA": "false",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1",
        "MPLBACKEND": "Agg", "NUMBA_CPU_NAME": "generic",
    }
    return {k: str(v) for k, v in paths.items()}


def allocation():
    job = os.environ.get("SLURM_JOB_ID", "")
    require(re.fullmatch(r"[0-9]+", job), "a Slurm allocation is required")
    require(not re.match(r"^(login|transfer)", socket.gethostname().split(".")[0]),
            "computation on login/transfer nodes is forbidden")
    array = os.environ.get("SLURM_ARRAY_JOB_ID")
    task = os.environ.get("SLURM_ARRAY_TASK_ID")
    selector = job
    if array is not None or task is not None:
        require(re.fullmatch(r"[0-9]+", array or "") and re.fullmatch(r"[0-9]+", task or ""),
                "invalid Slurm array identity")
        selector = array + "_" + task
    # A numeric job ID that equals ArrayJobId selects the WHOLE array. Query
    # this element explicitly, and never combine fields from different records.
    # https://slurm.schedmd.com/job_array.html
    info = run(["scontrol", "show", "job", selector, "--oneliner"])
    records = [dict(re.findall(r"(\w+)=(\S+)", line)) for line in info.splitlines() if line.strip()]
    require(len(records) == 1, "expected one allocation record for " + selector)
    fields = records[0]
    require(fields.get("JobId") == job, "allocation job ID mismatch for " + selector)
    if array is not None:
        require(fields.get("ArrayJobId") == array and fields.get("ArrayTaskId") == task,
                "allocation array identity mismatch for " + selector)
    require(fields.get("JobState") == "RUNNING",
            "allocation " + selector + " is not RUNNING: " + str(fields.get("JobState")))
    require(fields.get("UserId", "").endswith("(" + str(os.getuid()) + ")"),
            "allocation belongs to another user")
    require(int(fields.get("NumNodes", "0")) == 1, "this solver requires one node")
    require(os.environ.get("SLURM_NTASKS") == "1", "this solver requires one task")
    cpus = int(os.environ.get("SLURM_CPUS_PER_TASK", "0"))
    require(1 <= cpus <= 8 and int(fields.get("NumCPUs", "0")) == cpus,
            "CPU allocation mismatch (including memory-induced CPU expansion)")
    return job, cpus


def ready(bundle, prefix, cfg):
    require(not (bundle / "environment.json").is_symlink(), "environment marker is a link")
    marker = json.loads((bundle / "environment.json").read_text())
    require(marker["release"] == cfg["release"], "environment release mismatch")
    require(marker.get("prefix") == str(prefix.resolve()) and marker.get("versions") == cfg["expected_versions"],
            "environment record does not match the selected legacy profile")
    require((prefix / "bin/python").is_file(), "existing bempp Python is missing")
    package = bundle / "source/src/classical_casimir"
    require(inside(package.resolve(), bundle), "staged application escapes bundle")
    for directory in (bundle / "source", package.parent, package):
        require(directory.is_dir() and not directory.is_symlink(), "unsafe staged source directory")
    for name, expected in cfg["application_sha256"].items():
        source = package / name
        require(source.is_file() and not source.is_symlink() and source.stat().st_nlink == 1
                and inside(source.resolve(), package.resolve())
                and digest(source) == expected, "staged application changed: " + name)


def completed(job):
    require(re.fullmatch(r"[0-9]+(?:_[0-9]+)?", str(job)), "invalid job ID")
    out = run(["sacct", "-X", "-n", "-P", "-j", str(job),
               "--starttime=now-12weeks", "--endtime=now",
               "--format=JobID%64,State,ExitCode"])
    rows = [line.strip().split("|") for line in out.splitlines() if line.strip()]
    matching = [r for r in rows if r[0] == str(job)]
    require(len(matching) == 1 and matching[0][1:3] == ["COMPLETED", "0:0"],
            "job has not completed successfully in sacct: " + str(job))


def review(bundle, cfg, production=False):
    data = json.loads((bundle / "operator-review.json").read_text())
    require(data["release"] == cfg["release"], "configuration is for another release")
    require(re.fullmatch(r"Miniforge3(?:/[A-Za-z0-9_.+-]+)?", data.get("miniforge_module", ""))
            and "CHOOSE" not in data["miniforge_module"], "invalid Miniforge3 module configuration")
    if production:
        require(data.get("pilot_job_ids"), "successful representative pilot job IDs are required")
        for job in data["pilot_job_ids"]:
            completed(job)
    return data


def smoke_passed(bundle, cfg):
    proof = json.loads((bundle / "smoke-proof.json").read_text())
    check = json.loads((bundle / "smoke-results/smoke-check.json").read_text())
    require(proof["release"] == cfg["release"] and check["passed"] is True,
            "run the smoke job for this bundle first")
    require(check["versions"] == cfg["expected_versions"], "smoke runtime must match the selected legacy profile")
    require(proof["check_sha256"] == digest(bundle / "smoke-results/smoke-check.json"),
            "smoke check changed after execution")
    completed(proof["job_id"])


def resources(data):
    r = data["resources"]
    for key, low, high in (("cpus_per_task", 1, 8), ("memory_gib", 4, 128),
                           ("wall_minutes", 1, 240)):
        require(type(r[key]) is int and low <= r[key] <= high, "invalid resource: " + key)
    return r


def validate_distance_study(bundle, cfg):
    """One explicitly selected parameter set, with only the gap changing."""
    scope = cfg.get("study_scope", {})
    require(scope.get("kind") == "single-distance-study" and scope.get("convergence_checks") is False
            and scope.get("stop_for_review") is True, "study mode requires a fixed-resolution distance-study scope")
    manifest = json.loads((bundle / "manifest.json").read_text())
    cases = manifest["cases"]
    require(1 <= len(cases) < 1000000 and cfg["tasks"] == len(cases), "distance study task count mismatch")
    batches = [dict(index=i//300, start=i, count=min(300,len(cases)-i)) for i in range(0,len(cases),300)]
    require(cfg["batches"] == batches, "distance study batch mapping mismatch")
    gaps = [c["gap"] for c in cases]
    require(scope.get("gaps") == gaps and len(set(gaps)) == len(cases)
            and scope.get("samples", len(cases)) == len(cases), "distance study sample count/gaps mismatch")
    base = {k:v for k,v in cases[0].items() if k != "gap"}
    for c in cases:
        q = c.get("solver", {})
        direction = c.get("direction", [])
        require({k:v for k,v in c.items() if k != "gap"} == base,
                "distance study must keep all parameters except the gap fixed")
        require(c["boundary"] in ("dirichlet", "neumann") and math.isfinite(c["k"]) and c["k"] > 0
                and c.get("radius", 1.) == 1. and len(direction) == 3
                and all(math.isfinite(x) for x in direction) and math.isclose(math.hypot(*direction),1.,abs_tol=1e-12)
                and math.isfinite(c["gap"]) and c["gap"] > 0
                and type(c.get("refinement")) is int and c["refinement"] in range(7)
                and c.get("geometry", "two_spheres") == "two_spheres"
                and "mesh" not in c and not c.get("position_check")
                and c.get("force_only") is True and c.get("isolated") is False
                and all(type(q.get(key)) is int and q[key] in range(1,21) for key in ("regular_order","singular_order"))
                and math.isfinite(q.get("rtol",1e-9)) and 0 < q.get("rtol",1e-9) < 1
                and type(q.get("maxiter",300)) is int and q.get("maxiter",300) > 0
                and math.isfinite(q.get("memory_gib",0)) and 4 <= q.get("memory_gib",0) <= 128,
                "invalid fixed-resolution distance-study case")
    first = cases[0]
    for key, value in dict(boundary=first["boundary"], ka=first["k"], direction=first["direction"],
                           refinement=first["refinement"], regular_order=first["solver"]["regular_order"],
                           singular_order=first["solver"]["singular_order"]).items():
        require(scope.get(key) == value, "distance-study scope mismatch: " + key)


def submit(bundle, cfg, prefix, user, mode, index, dry_run, workflow_stage=None, task_index=None, task_indices=None):
    require_login_host()
    require((task_index is None and task_indices is None) or mode == "study", "task retry is only supported for the distance study")
    require(task_index is None or task_indices is None, "choose one retry selection")
    ready(bundle, prefix, cfg)
    data = review(bundle, cfg, production=mode == "campaign")
    r = resources(data)
    partition = data["partition"]
    excluded = data.get("excluded_nodes",[])
    require(isinstance(excluded,list) and all(isinstance(node,str) and re.fullmatch(r"[A-Za-z0-9_.-]+",node) for node in excluded),
            "invalid excluded node names")
    selected = task_indices if task_index is None else [task_index]
    # None leaves eligible partition selection to the LUIS submission policy.
    # Retain support for deliberate shared-CPU pins in operator-review.json.
    require(partition is None or partition in ("mpp.share", "amo", "taurus", "haku", "lena"),
            "partition must be null (automatic) or a documented shared CPU partition")
    if mode in ("smoke", "postprocess"):
        require(index is None, mode + " takes no index")
        start, count, cpus, mem, minutes = 0, 1, 2, 4, (10 if mode == "smoke" else 30)
        if mode == "postprocess":
            smoke_passed(bundle, cfg)
    elif mode == "pilot":
        smoke_passed(bundle, cfg)
        require(index is not None and 0 <= index < cfg["tasks"], "pilot needs a global task index")
        start, count = index, 1
        cpus, mem, minutes = r["cpus_per_task"], r["memory_gib"], r["wall_minutes"]
    else:
        require(mode in ("campaign", "study"), "unknown submission mode")
        smoke_passed(bundle, cfg)
        require(index is not None and 0 <= index < len(cfg["batches"]), "array needs a batch index")
        if mode == "study":
            validate_distance_study(bundle, cfg)
        start, count = cfg["batches"][index]["start"], cfg["batches"][index]["count"]
        if selected is not None:
            require(isinstance(selected,list) and 1 <= len(selected) <= 300
                    and all(type(i) is int and start <= i < start+count for i in selected)
                    and len(set(selected)) == len(selected), "retry tasks outside selected study batch or duplicated")
            selected = sorted(selected)
            start,count = min(selected),len(selected)
        cpus, mem, minutes = (r[k] for k in ("cpus_per_task", "memory_gib", "wall_minutes"))
    require(1 <= count <= 300 and start + count <= cfg["tasks"], "array limit/mapping error")
    require(start + count < 1000000, "array index limit exceeded")
    if mode in ("pilot", "campaign", "study"):
        manifest_cases = json.loads((bundle / "manifest.json").read_text())["cases"]
        cases = [manifest_cases[i] for i in selected] if selected is not None else manifest_cases[start:start+count]
        minimum = max(c.get("solver", {}).get("memory_gib", 4) for c in cases)
        require(mem >= minimum, "requested memory is below the manifest solver memory budget")
    safe_tree(bundle / "logs")
    # Current cluster configuration and quota reports are inspected by the
    # operator. checkquota's documented interface has no machine-readable contract.
    quota = run(["checkquota"])
    print(quota, end="", flush=True)
    array = ",".join(map(str,selected)) if selected is not None and len(selected)>1 else str(start)+"-"+str(start+count-1)
    args = ["sbatch", "--parsable", "--export=ALL", "--no-requeue", "--nodes=1", "--ntasks=1",
            "--cpus-per-task=" + str(cpus), "--mem=" + str(mem) + "G",
            "--time=" + str(minutes),
            "--array=" + array,
            "--job-name=casimir-" + mode, "--chdir=" + str(bundle),
            "--output=" + str(bundle / "logs/%A_%a.out"),
            "--error=" + str(bundle / "logs/%A_%a.err"),
            str(bundle / ({"smoke": "smoke.slurm", "postprocess": "postprocess.slurm"}.get(mode, "campaign.slurm")))]
    if partition is not None:
        args.insert(-1, "--partition=" + partition)
    if excluded:
        args.insert(-1,"--exclude="+",".join(sorted(set(excluded))))
    # Explicit arguments beat SBATCH_* variables and prevent inherited wrappers.
    for key in list(os.environ):
        if key.startswith("SBATCH_"):
            del os.environ[key]
    os.environ["CASIMIR_SUBMIT_MODE"] = mode
    run(["sbatch", "--test-only"] + args[2:])
    if dry_run:
        print(shlex.join(args))
        return
    # Serializes this bundle's submissions. No automatic retries or queue polling.
    with (bundle / ".submit.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        (bundle / "logs").mkdir(exist_ok=True)
        job = run(args).strip()
        require(re.fullmatch(r"[0-9]+(?:;[A-Za-z0-9_.-]+)?", job), "unrecognized sbatch job ID")
        with (bundle / "submissions.jsonl").open("a") as record:
            entry = dict(job=job, mode=mode, start=start, count=count,
                         argv=args, release=cfg["release"], workflow_stage=workflow_stage)
            if selected is not None:
                entry["indices"] = selected
            record.write(json.dumps(entry) + "\n")
        print(job)
        return job


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("check", "env", "login", "init", "init-setup", "submit", "allocation", "interactive", "smoke-proof", "module", "task-check"))
    p.add_argument("--bundle", required=True)
    p.add_argument("--mode", choices=("smoke", "study", "pilot", "campaign", "postprocess"))
    p.add_argument("--index", type=int)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    os.umask(0o077)
    bundle, cfg, prefix, user = context(a.bundle)  # no writes before this passes
    if a.command == "check":
        print(json.dumps(dict(bundle=str(bundle), environment=str(prefix), tasks=cfg["tasks"])))
    elif a.command == "login":
        require_login_host()
    elif a.command == "env":
        for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE", "PIP_TARGET", "PIP_PREFIX",
                    "PIP_ROOT", "PIP_USER"):
            print("unset " + key)
        for key, value in environment(bundle, cfg, prefix).items():
            print("export " + key + "=" + shlex.quote(value))
    elif a.command in ("init", "init-setup"):
        safe_tree(bundle / "preflight")
        paths = [bundle / "runtime"]
        if a.command == "init-setup":
            safe_tree(bundle / "source")
            safe_tree(bundle / "logs")
        for path in paths:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ("cache", "config", "data", "state", "run", "tmp", "numba", "matplotlib", "pip", "uv", "conda-pkgs", "conda-envs"):
            (bundle / "runtime" / name).mkdir(mode=0o700, exist_ok=True)
    elif a.command == "allocation":
        allocation()
        ready(bundle, prefix, cfg)
        require(os.environ.get("CASIMIR_SUBMIT_MODE") in ("smoke", "study", "pilot", "campaign"),
                "use submit.sh; direct sbatch is unsupported")
    elif a.command == "module":
        # Queued jobs reuse the automatically recorded module selection.
        print(review(bundle, cfg)["miniforge_module"])
    elif a.command == "interactive":
        allocation()
        ready(bundle, prefix, cfg)
        safe_tree(bundle / "collected")
        safe_tree(bundle / "figures")
    elif a.command == "task-check":
        index = int(os.environ.get("SLURM_ARRAY_TASK_ID", "-1"))
        require(0 <= index < cfg["tasks"], "task index outside manifest")
        mode = os.environ.get("CASIMIR_SUBMIT_MODE")
        require(mode in ("smoke", "study", "pilot", "campaign"), "unknown submission mode")
        # Check only this case's files, keeping per-job metadata work bounded.
        output = bundle / ("smoke-results" if mode == "smoke" else "results")
        if mode == "pilot":
            array_job = os.environ.get("SLURM_ARRAY_JOB_ID", "")
            require(re.fullmatch(r"[0-9]+", array_job), "pilot array job ID required")
            require(not (bundle / "pilot-results").is_symlink(), "unsafe pilot output root")
            output = bundle / "pilot-results" / array_job
        require(not output.is_symlink(), "output directory is a symlink")
        if mode == "smoke":
            safe_tree(output)
        else:
            case = json.loads((bundle / "manifest.json").read_text())["cases"][index]
            key = hashlib.sha256(json.dumps(case, sort_keys=True, separators=(",", ":"),
                                           allow_nan=False).encode()).hexdigest()[:20]
            require(not (output / key).is_symlink(), "case output directory is a symlink")
            safe_tree(output / key)
        lock = bundle / "locks" / (("smoke" if mode == "smoke" else "task") + "-" + str(index) + ".lock")
        require(not lock.is_symlink() and (not lock.exists() or lock.stat().st_nlink == 1),
                "unsafe task lock")
    elif a.command == "submit":
        require(a.mode is not None, "submission mode required")
        submit(bundle, cfg, prefix, user, a.mode, a.index, a.dry_run)
    elif a.command == "smoke-proof":
        job, _ = allocation()
        check = bundle / "smoke-results/smoke-check.json"
        require(json.loads(check.read_text())["passed"] is True, "smoke failed")
        array_job = os.environ.get("SLURM_ARRAY_JOB_ID", "")
        require(re.fullmatch(r"[0-9]+", array_job), "array job ID is required")
        (bundle / "smoke-proof.json").write_text(json.dumps(dict(
            release=cfg["release"], job_id=array_job + "_" + os.environ["SLURM_ARRAY_TASK_ID"],
            check_sha256=digest(check)), indent=2) + "\n")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print("LUIS preflight: " + str(error), file=sys.stderr)
        sys.exit(2)
