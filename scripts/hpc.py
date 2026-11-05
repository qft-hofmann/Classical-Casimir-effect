"""Clone-to-run LUIS workflow. Bootstrap uses only the Python standard library."""
import argparse
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

ARRAY_GUARD_OLD_SHA256 = "3155138482d271815b8682feae0fa5a16b10193875142de00871dfc3580994e8"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True  # bootstrap imports precede storage validation
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def source_files(root):
    files = [root/p for p in ("run-hpc.sh", "scripts/hpc.py", "pyproject.toml", "README.md", "requirements-cluster.lock")]
    files += [p for p in (root/"src/classical_casimir").rglob("*")
              if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]
    files += list((root/"docs/luis").glob("*.md"))
    profile = load(root/"src/classical_casimir/cluster_templates/bundle.py", "fingerprint_builder").load_luis_profile(root)
    files += [root/"configs/luis.json", root/profile["requirements_file"]]
    if (root/"configs/luis.local.json").exists():
        files.append(root/"configs/luis.local.json")
    return sorted(set(files))


def fingerprint(root):
    value = hashlib.sha256()
    for path in source_files(root):
        if path.is_symlink():
            raise ValueError("source file is a symlink: " + str(path))
        value.update(str(path.relative_to(root)).encode())
        value.update(path.read_bytes())
    return value.hexdigest()[:20]


def number(question, default, low, high):
    value = input(question + " [" + str(default) + "]: ").strip() if sys.stdin.isatty() else ""
    result = int(value) if value else default
    if not low <= result <= high:
        raise ValueError("value must be between " + str(low) + " and " + str(high))
    return result


def representative_cases(manifest):
    """Both boundary conditions: moderate reference and hardest spatial/quadrature settings."""
    result = []
    for boundary in ("dirichlet", "neumann"):
        for k, gap, level, order in ((1., 2., 2, 6), (5., .1, 4, 8)):
            found = [i for i, c in enumerate(manifest["cases"]) if
                     c["boundary"] == boundary and c["k"] == k and c["gap"] == gap
                     and c["refinement"] == level and c["direction"] == [0., 1., 0.]
                     and c["solver"]["regular_order"] == order]
            if len(found) != 1:
                raise ValueError("representative case is not unique")
            result.append(found[0])
    return result


def accounting_status(text, job, start, count, indices=None, allow_failed=False):
    expected = {str(job)+"_"+str(i) for i in (indices if indices is not None else range(start, start+count))}
    rows = {}
    for line in text.splitlines():
        fields = line.strip().split("|")
        if len(fields) >= 3 and fields[0] in expected:
            rows[fields[0]] = fields[1:3]
    nonterminal = {"PENDING", "RUNNING", "COMPLETING", "CONFIGURING", "SUSPENDED", "REQUEUED", "RESIZING"}
    bad = {key: value for key, value in rows.items()
           if value[0] not in nonterminal and value != ["COMPLETED", "0:0"]}
    if bad and not allow_failed:
        raise ValueError("Slurm task failure: " + json.dumps(bad) + "; inspect logs/accounting before --retry-failed")
    return set(rows) == expected and all(value[0] not in nonterminal if allow_failed
                                        else value == ["COMPLETED", "0:0"] for value in rows.values())


class Workflow:
    def __init__(self, root, retry_failed=False, configure=False, full_survey=False, boundary="dirichlet",
                 recover_array=None, study_parameters=None, resource_requests=None, resume_run=None, excluded_nodes=None):
        self.root = Path(root)
        templates = self.root/"src/classical_casimir/cluster_templates"
        self.policy = load(templates/"policy.py", "hpc_policy")
        self.builder = load(templates/"bundle.py", "hpc_bundle")
        self.retry_failed = retry_failed
        self.configure = configure
        self.full_survey = full_survey
        self.boundary = boundary
        self.recover_array_path = recover_array
        self.resume_run_path = resume_run
        self.exclusion_override = excluded_nodes is not None
        self.excluded_nodes = sorted(set(excluded_nodes or []))
        self.policy.require(all(re.fullmatch(r"[A-Za-z0-9_.-]+", node) for node in self.excluded_nodes),
                            "excluded nodes must be plain node names")
        self.policy.require(boundary in ("dirichlet", "neumann"), "unsupported boundary condition")
        self.resource_overrides = dict(resource_requests or {})
        self.requested_resources = dict(cpus_per_task=2, memory_gib=32 if full_survey else 8,
                                       wall_minutes=240 if full_survey else 45)
        self.requested_resources.update(self.resource_overrides)
        self.policy.resources(dict(resources=self.requested_resources))
        parameters = dict(study_parameters or {})
        parameters.setdefault("memory_gib", self.requested_resources["memory_gib"])
        self.manifest = None if full_survey else self.builder.distance_study_manifest(boundary, **parameters)
        self.policy.require(not full_survey or self.requested_resources["memory_gib"] >= 32,
                            "the full survey's solver budgets require at least 32 GiB/task")
        self.plan = "full-survey" if full_survey else "distance-"+boundary+"-ka"+format(self.manifest["study_scope"]["ka"],"g")
        effective_scope = None if full_survey else dict(self.manifest["study_scope"])
        if effective_scope is not None:
            effective_scope.pop("requested_mesh_size",None)
        request = dict(study_scope=effective_scope,
                       resources=self.requested_resources, excluded_nodes=self.excluded_nodes)
        self.request_id = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]
        self.state = {}

    def locate(self):
        self.root, _ = self.policy.locations(self.root, private=False)
        self.policy.require_login_host()
        saved_run = self.recover_array_path or self.resume_run_path
        if saved_run is None:
            self.bundle = self.root/"hpc-runs"/(fingerprint(self.root)+"-"+self.plan+"-"+self.request_id)
        else:
            requested = Path(saved_run)
            self.bundle = requested if requested.is_absolute() else self.root/requested
            self.policy.require(self.bundle.is_dir() and self.bundle.parent.resolve() == (self.root/"hpc-runs").resolve(),
                                "recovery requires an existing run directly below this checkout's hpc-runs")
        self.policy.require(not (self.root/"hpc-runs").is_symlink() and not self.bundle.is_symlink(),
                            "hpc-runs must not be a symlink")

    def prepare(self):
        self.root.chmod(0o700)
        self.bundle.parent.mkdir(exist_ok=True, mode=0o700)
        if not self.bundle.exists():
            manifest = self.builder.survey_manifest() if self.full_survey else self.manifest
            manifest["execution_resources"] = self.requested_resources
            manifest["excluded_nodes"] = self.excluded_nodes
            self.builder.prepare(manifest, self.bundle, self.root)
        # An incomplete previous preparation is not overwritten silently.
        self.bundle, self.cfg, self.prefix, self.user = self.policy.context(self.bundle)
        if self.resume_run_path is not None:
            self.policy.require(self.cfg.get("study_scope", {}).get("kind") == "single-distance-study",
                                "--resume-run requires a saved distance study")
            scope = self.cfg["study_scope"]
            self.boundary = scope["boundary"]
            self.plan = "distance-"+self.boundary+"-ka"+format(scope["ka"],"g")
        self.policy.require(not (self.bundle/"workflow.json").is_symlink(), "unsafe workflow state")
        self.state_path = self.bundle/"workflow.json"
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text())
        self.policy.require(not self.state or self.state["release"] == self.cfg["release"], "state release mismatch")
        self.state.setdefault("release", self.cfg["release"])
        self.state.setdefault("stages", {})
        self.policy.require(self.state.get("plan", self.plan) == self.plan, "state belongs to another execution plan")
        self.state["plan"] = self.plan
        # Recover a submission even if the connection died between sbatch and
        # saving workflow state. The lower-level submitter records it first.
        submissions = self.bundle/"submissions.jsonl"
        if submissions.exists():
            for line in submissions.read_text().splitlines():
                record = json.loads(line)
                if record.get("workflow_stage"):
                    stage = dict(job=record["job"].split(";")[0], start=record["start"], count=record["count"])
                    if "indices" in record:
                        stage["indices"] = record["indices"]
                    self.state["stages"].setdefault(record["workflow_stage"], stage)
        for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE", "PIP_TARGET", "PIP_PREFIX", "PIP_ROOT", "PIP_USER"):
            os.environ.pop(key, None)
        os.environ.update(self.policy.environment(self.bundle, self.cfg, self.prefix))
        os.chdir(self.bundle)
        print("Plan: " + self.plan + " ("+str(self.cfg["tasks"])+" cases)", flush=True)
        print("Work directory: " + str(self.bundle), flush=True)
        if not self.full_survey:
            scope = self.cfg["study_scope"]
            mesh = self.builder.sphere_mesh_parameters(refinement=scope["refinement"])
            print("Gap g/a: " + format(min(scope["gaps"]),"g") + " to " + format(max(scope["gaps"]),"g")
                  + "; direction=" + str(scope["direction"]) + "; mesh h/a=" + format(mesh["mesh_size"],".9g")
                  + " (level " + str(scope["refinement"]) + ", " + str(mesh["triangles_per_sphere"]) + " triangles/sphere)"
                  + "; quadrature=" + str(scope["regular_order"]) + "/" + str(scope["singular_order"]), flush=True)

    def save(self):
        self.builder.atomic_json(self.state_path, self.state)

    def shell(self, name, *args):
        # Environment inspection and source staging output goes to logs/setup.log.
        subprocess.run(["bash", str(self.bundle/name), *args], check=True)

    def review(self):
        """Save preflight and resource configuration without manual attestations."""
        try:
            if self.configure:
                raise ValueError("operator requested renewed configuration")
            existing = self.policy.review(self.bundle, self.cfg)
            self.policy.require(existing.get("configured_utc") or existing.get("reviewed_utc"),
                                "initial preflight/configuration has not run")
            self.policy.require(all(existing["resources"][k] == v for k,v in self.resource_overrides.items()),
                                "command-line resources differ from the saved configuration")
            self.policy.require(not self.exclusion_override or existing.get("excluded_nodes",[]) == self.excluded_nodes,
                                "command-line node exclusions differ from the saved configuration")
            return existing
        except (ValueError, KeyError):
            pass
        self.shell("preflight.sh")
        data = json.loads((self.bundle/"operator-review.json").read_text())
        previous_profile = self.profile(data)
        if self.exclusion_override:
            data["excluded_nodes"] = self.excluded_nodes
        print((self.bundle/"preflight/quota.txt").read_text())
        print("Current hardware, Slurm association/QoS and partition reports: " + str(self.bundle/"preflight"))
        if (self.bundle/"environment.json").exists():
            chosen = data["miniforge_module"]
            selection = "saved run"
        else:
            requested_module = data["miniforge_module"]
            self.policy.require(re.fullmatch(r"Miniforge3(?:/[A-Za-z0-9_.+-]+)?", requested_module),
                                "invalid configured Miniforge module")
            chosen = self.policy.run(["bash", "-lc",
                'set -euo pipefail; module purge; module load ' + shlex.quote(requested_module) + '; printf "%s\\n" "$LOADEDMODULES"']).strip()
            self.policy.require(re.fullmatch(r"Miniforge3/[A-Za-z0-9_.+-]+", chosen),
                                "default Miniforge3 must be the only loaded module")
            selection = "cluster default selected automatically" if requested_module == "Miniforge3" else "site profile"
        print("Miniforge module: " + chosen + " (" + selection + ")")
        data["miniforge_module"] = chosen
        self.policy.require(data["partition"] is None or data["partition"] in
                            ("mpp.share", "amo", "taurus", "haku", "lena"), "unsupported partition")
        if data["partition"] is None:
            print("Partition: automatic; Slurm selects eligible nodes from the resource requests.")
        else:
            print("Partition pinned in operator-review.json: " + data["partition"])
        r = data["resources"]
        print("Choose CPU, memory and time requests; Slurm checks feasibility before submission.")
        minimum_memory = max(case.get("solver", {}).get("memory_gib",4) for case in
                             json.loads((self.bundle/"manifest.json").read_text())["cases"])
        for key, label, low, high in (("memory_gib", "GiB/task", minimum_memory, 128),
                                      ("cpus_per_task", "CPUs/task", 1, 8),
                                      ("wall_minutes", "Minutes/task", 1, 240)):
            if key in self.resource_overrides:
                r[key] = self.resource_overrides[key]
                print(label + ": " + str(r[key]) + " (command line)")
            elif self.resume_run_path is not None and not self.configure:
                print(label + ": " + str(r[key]) + " (saved run)")
            else:
                r[key] = number(label, r[key], low, high)
        self.policy.require(r["memory_gib"] >= minimum_memory, "requested memory is below the manifest solver budget")
        print("All cases in the array are submitted together; Slurm manages concurrency and queue limits.")
        print("The compute-node smoke job will test the binaries and BEM/JIT execution on its allocated node.")
        data["configured_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        if self.profile(data) != previous_profile:
            data["pilot_job_ids"] = []
        self.builder.atomic_json(self.bundle/"operator-review.json", data)
        self.configure = False
        return data

    def setup(self):
        if (self.bundle/"environment.json").exists():
            self.policy.ready(self.bundle, self.prefix, self.cfg)
            return
        if (self.bundle/"logs/setup.log").exists():
            stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            (self.bundle/"logs/setup.log").rename(self.bundle/"logs"/("setup-failed-"+stamp+".log"))
        self.shell("setup.sh")
        self.policy.ready(self.bundle, self.prefix, self.cfg)

    def wait(self, record, allow_failed=False):
        """One bounded query per minute, only for this array; never queue filling."""
        job = record["job"]
        missing = 0
        print("Waiting for Slurm job " + job + " (checks once per minute; Ctrl-C leaves jobs running).", flush=True)
        while True:
            try:
                queue = self.policy.run(["squeue", "--noheader", "--jobs", job, "--format=%i"])
            except subprocess.CalledProcessError as error:
                if "invalid job id" not in (error.stderr or "").lower():
                    raise
                queue = ""  # completed jobs may already be purged from squeue
            if not queue.strip():
                out = self.policy.run(["sacct", "--array", "-X", "-n", "-P", "-j", job,
                                       "--starttime=now-12weeks", "--endtime=now",
                                       "--format=JobID%64,State,ExitCode"])
                if accounting_status(out, job, record["start"], record["count"],record.get("indices"),allow_failed):
                    failed = []
                    expected = {job+"_"+str(i):i for i in record.get("indices",range(record["start"],record["start"]+record["count"]))}
                    for line in out.splitlines():
                        fields = line.strip().split("|")
                        if len(fields) >= 3 and fields[0] in expected and fields[1:3] != ["COMPLETED","0:0"]:
                            failed.append(expected[fields[0]])
                    return sorted(set(failed))
                missing += 1
                self.policy.require(missing <= 10, "accounting is incomplete; rerun later instead of resubmitting")
            time.sleep(60)

    def stage(self, key, mode, index=None, task_index=None, task_indices=None):
        stages = self.state["stages"]
        if key in stages:
            try:
                self.wait(stages[key])
                return stages[key]
            except ValueError as error:
                recorded_retry = mode == "study" and key+"-retry" in stages
                if (not self.retry_failed and not recorded_retry) or "Slurm task failure:" not in str(error):
                    raise
                if mode == "study":
                    failed = self.wait(stages[key],allow_failed=True)
                    print("Retrying only failed task indices: " + ", ".join(map(str,failed)),flush=True)
                    return self.stage(key+"-retry",mode,index,task_indices=failed)
                print("Retry explicitly requested for failed stage " + key, flush=True)
        self.review()
        # A failed feasibility check or submission stops without automatic retry.
        job = self.policy.submit(self.bundle, self.cfg, self.prefix, self.user, mode, index,
                                 False, workflow_stage=key, task_index=task_index,task_indices=task_indices)
        start, count = (0, 1)
        if mode == "pilot":
            start = index
        elif mode in ("campaign", "study"):
            start, count = (self.cfg["batches"][index][k] for k in ("start", "count"))
        if task_index is not None:
            start, count = task_index, 1
        if task_indices is not None:
            start,count = min(task_indices),len(task_indices)
        stages[key] = dict(job=job.split(";")[0], start=start, count=count)
        if task_indices is not None:
            stages[key]["indices"] = sorted(task_indices)
        self.save()
        self.wait(stages[key])
        return stages[key]

    def recover_array(self):
        """Repair the known array-ID guard failure, keeping this frozen run's data."""
        self.policy.require(not self.full_survey, "array-guard recovery is limited to the initial distance study")
        self.policy.validate_distance_study(self.bundle, self.cfg)
        original = self.state["stages"]["distance-study-0"]
        self.policy.require(original["start"] == 0 and original["count"] == self.cfg["tasks"],
                            "unexpected original distance-study mapping")
        job = original["job"]
        self.policy.require(re.fullmatch(r"[0-9]+", job), "invalid original array job ID")
        accounting = self.policy.run(["sacct", "--array", "-X", "-n", "-P", "-j", job,
                                      "--starttime=now-12weeks", "--endtime=now",
                                      "--format=JobID%64,State,ExitCode"])
        expected = {job+"_"+str(i): i for i in range(original["count"])}
        rows = {}
        for line in accounting.splitlines():
            fields = line.strip().split("|")
            if len(fields) >= 3 and fields[0] in expected:
                self.policy.require(fields[0] not in rows, "duplicate original accounting record")
                rows[fields[0]] = fields[1:3]
        self.policy.require(rows.keys() == expected.keys(), "original array accounting is incomplete; rerun later")
        failed = []
        for identity, status in rows.items():
            if status == ["COMPLETED", "0:0"]:
                continue
            self.policy.require(status == ["FAILED", "2:0"],
                                "recovery requires all original tasks finished, with only known guard failures: " + identity)
            error = self.bundle/"logs"/(identity+".err")
            self.policy.require(not error.is_symlink() and error.read_text().strip() ==
                                "LUIS preflight: allocation is not RUNNING", "not the known array guard failure: " + identity)
            failed.append(expected[identity])
        self.policy.require(failed, "original array has no matching guard failure to repair")
        self.review()
        self.setup()
        self.policy.smoke_passed(self.bundle, self.cfg)
        old_hash = ARRAY_GUARD_OLD_SHA256
        target = self.bundle/"policy.py"
        replacement = (self.root/"src/classical_casimir/cluster_templates/policy.py").read_bytes()
        new_hash = hashlib.sha256(replacement).hexdigest()
        observed = self.policy.digest(target)
        record_path = self.bundle/"array-guard-repair.json"
        backup = self.bundle/"policy-before-array-guard.py"
        if observed == old_hash:
            self.policy.require(self.cfg["sha256"]["policy.py"] == old_hash, "unexpected original guard hash")
            previous = target.read_bytes()
            if backup.exists():
                self.policy.require(not backup.is_symlink() and self.policy.digest(backup) == old_hash,
                                    "array-guard backup differs from the known original")
            else:
                backup.write_bytes(previous)
            self.builder.atomic_json(record_path, dict(
                release=self.cfg["release"], original_array=job, failed_indices=sorted(failed),
                old_policy_sha256=old_hash, new_policy_sha256=new_hash,
                repaired_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                scope="Runtime allocation guard and bounded task retry only; source, manifest, environment and results retained."))
            # Keep a backup and roll back on ordinary interruptions. Only this
            # allowlisted runtime guard changes; the scientific source stays frozen.
            temporary = self.bundle/"policy-array-repair.tmp"
            try:
                temporary.write_bytes(replacement)
                temporary.replace(target)
                self.cfg["sha256"]["policy.py"] = new_hash
                self.builder.atomic_json(self.bundle/"bundle.json", self.cfg)
            except BaseException:
                target.write_bytes(previous)
                self.cfg["sha256"]["policy.py"] = old_hash
                self.builder.atomic_json(self.bundle/"bundle.json", self.cfg)
                raise
        else:
            self.policy.require(record_path.is_file(), "not a supported array-guard repair")
            recorded = json.loads(record_path.read_text())
            self.policy.require(recorded["old_policy_sha256"] == old_hash and recorded["new_policy_sha256"] == observed
                                and recorded["release"] == self.cfg["release"] and recorded["original_array"] == job,
                                "array-guard repair record mismatch")
        self.policy.context(self.bundle)
        print("Recovering original run; retry task indices: " + ", ".join(map(str, sorted(failed))), flush=True)
        for index in sorted(failed):
            self.stage("distance-study-0-retry-"+str(index), "study", 0, task_index=index)
        self.stage("postprocess", "postprocess")
        self.finish()

    def efficiency(self, records):
        for record in records:
            # IDs name one array element, so seff sees a completed job only.
            job = record["job"] + "_" + str(record["start"])
            print(self.policy.run(["sacct", "-j", job, "--starttime=now-12weeks", "--endtime=now",
                                   "--format=JobID,Elapsed,AllocCPUS,TotalCPU,ReqMem,MaxRSS,State,ExitCode"]))
            print(self.policy.run(["seff", job]))

    def production_review(self, pilots):
        self.efficiency(pilots)
        data = self.review()
        required = [r["job"]+"_"+str(r["start"]) for r in pilots]
        for job in required:
            self.policy.completed(job)
        data.update(pilot_job_ids=required)
        self.builder.atomic_json(self.bundle/"operator-review.json", data)

    @staticmethod
    def profile(data):
        return (data["partition"], tuple(data.get("excluded_nodes",[])), *(data["resources"][key] for key in
                ("cpus_per_task", "memory_gib", "wall_minutes")))

    def run(self, stop_after):
        self.review()
        self.setup()
        self.stage("smoke", "smoke")
        self.policy.smoke_passed(self.bundle, self.cfg)
        if stop_after == "smoke":
            return
        if not self.full_survey:
            self.policy.require(stop_after != "pilots", "pilot-only execution belongs to --full-survey")
            for batch in self.cfg["batches"]:
                self.stage("distance-study-"+str(batch["index"]), "study", batch["index"])
            self.stage("postprocess", "postprocess")
            self.finish()
            return  # hard stop; no pilots, refinement submissions or broader sweep
        manifest = json.loads((self.bundle/"manifest.json").read_text())
        while True:
            tested_profile = self.profile(self.review())
            profile_id = hashlib.sha256(json.dumps(tested_profile).encode()).hexdigest()[:12]
            pilots = [self.stage("pilot-"+str(index)+"-"+profile_id, "pilot", index)
                      for index in representative_cases(manifest)]
            if stop_after == "pilots":
                self.efficiency(pilots)
                return
            self.production_review(pilots)
            data = json.loads((self.bundle/"operator-review.json").read_text())
            if self.profile(data) == tested_profile:
                break
            print("Resource/partition changes require pilots under the new requests before production.")
        for batch in self.cfg["batches"]:
            self.stage("batch-"+str(batch["index"]), "campaign", batch["index"])
        self.stage("postprocess", "postprocess")
        self.finish()

    def finish(self):
        coverage = json.loads((self.bundle/"collected/coverage.json").read_text())
        self.policy.require(coverage.get("all_cases_computed") is True
                            and coverage.get("provenance_consistent") is True
                            and coverage.get("expected") == self.cfg["tasks"]
                            and coverage.get("computed") == self.cfg["tasks"],
                            "collection reports pending/invalid cases or mixed provenance; inspect coverage.json")
        self.builder.atomic_json(self.bundle/"study-review.json", dict(
            plan=self.plan, cases=self.cfg["tasks"], study_scope=self.cfg.get("study_scope", {}),
            collection_complete=True, scientific_validation="requires review",
            stop_for_review=True, full_survey_selected=self.full_survey,
            convergence_checks_performed=self.full_survey,
            coverage="collected/coverage.json", sample_metadata="figures/envelopes.json",
            figure="figures/separation-forces.png"))
        print("All manifest cases collected. Figures: " + str(self.bundle/"figures"))
        print("Convergence/sign uncertainty remains recorded in the numerical outputs.")
        if not self.full_survey:
            print("Stopped after one separation-distance study. Review these results before deciding further work.")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="run-hpc.sh", description=__doc__,
        epilog="Example: bash run-hpc.sh --boundary dirichlet --ka 1 --gap-min 0.1 --gap-max 20 --points 150 --cpus 2 --memory-gib 8 --minutes 15")
    parser.add_argument("--status", action="store_true", help="show state without setup or submission")
    parser.add_argument("--prepare-only", action="store_true", help="create/check bundle without runtime staging or submission")
    parser.add_argument("--stop-after", choices=("smoke", "pilots", "all"), default="all")
    parser.add_argument("--retry-failed", action="store_true", help="explicitly retry a failed stage once after diagnosis")
    parser.add_argument("--recover-array", metavar="RUN", help="repair the known array-ID guard failure in an existing distance run and retry only its failed tasks")
    parser.add_argument("--resume-run", metavar="RUN", help="resume a saved distance study, retaining its frozen source and results; combine with --retry-failed after diagnosis")
    parser.add_argument("--exclude", action="append", metavar="NODE[,NODE...]", help="exclude these nodes for this run; repeat or separate node names with commas")
    parser.add_argument("--configure", action="store_true", help="refresh preflight and resource settings")
    parser.add_argument("--boundary", choices=("neumann", "dirichlet"), default=None,
                        help="boundary condition for a distance study (default: dirichlet)")
    parser.add_argument("--gap-min", type=float, help="minimum surface gap g/a, inclusive (default: 0.1)")
    parser.add_argument("--gap-max", type=float, help="maximum surface gap g/a, inclusive (default: 20)")
    parser.add_argument("--points", "--steps", type=int, help="number of equally spaced sample points, including endpoints (default: 150)")
    parser.add_argument("--ka", type=float, help="dimensionless wavenumber ka for unit-radius spheres (default: 1)")
    parser.add_argument("--direction", type=float, nargs=3, metavar=("X","Y","Z"), help="illumination direction, normalized automatically (default: 0 1 0)")
    mesh = parser.add_mutually_exclusive_group()
    mesh.add_argument("--mesh-size", type=float, metavar="H_OVER_A", help="maximum triangle-edge length h/a; select the coarsest supported mesh satisfying this bound")
    mesh.add_argument("--mesh-level", dest="refinement", type=int, help="icosahedral sphere refinement, 0 to 6 (default: 3, h/a about 0.164647)")
    parser.add_argument("--regular-order", type=int, help="regular quadrature order, 1 to 20 (default: 6)")
    parser.add_argument("--singular-order", type=int, help="singular quadrature order, 1 to 20 (default: 6)")
    parser.add_argument("--rtol", type=float, help="linear solver relative tolerance (default: 1e-9)")
    parser.add_argument("--maxiter", type=int, help="maximum linear solver iterations (default: 300)")
    parser.add_argument("--cpus", type=int, help="CPUs/task, 1 to 8; skips its resource prompt")
    parser.add_argument("--memory-gib", type=int, help="GiB/task and distance-study solver budget, 4 to 128; skips its resource prompt")
    parser.add_argument("--minutes", type=int, help="minutes/task, 1 to 240; skips its resource prompt")
    parser.add_argument("--full-survey", action="store_true",
                        help="explicitly select the separate 2,660-case campaign; never selected by default")
    args = parser.parse_args(argv)
    study_parameters = {key:getattr(args,key) for key in
                        ("gap_min","gap_max","points","ka","direction","refinement","mesh_size","regular_order","singular_order","rtol","maxiter")
                        if getattr(args,key) is not None}
    resource_requests = {key:value for key,value in dict(cpus_per_task=args.cpus, memory_gib=args.memory_gib,
                                                        wall_minutes=args.minutes).items() if value is not None}
    if args.stop_after == "pilots" and not args.full_survey:
        parser.error("--stop-after pilots requires explicit --full-survey; default is one distance study")
    if args.full_survey and (args.boundary is not None or study_parameters):
        parser.error("distance-study parameters cannot be combined with --full-survey")
    if args.recover_array and (study_parameters or resource_requests or args.boundary is not None):
        parser.error("--recover-array uses the saved run parameters; do not provide new study/resource parameters")
    if args.resume_run and (args.recover_array or args.full_survey or study_parameters or args.boundary is not None):
        parser.error("--resume-run uses saved study parameters; only resource/placement overrides are allowed")
    if args.recover_array and (args.full_survey or args.stop_after != "all"):
        parser.error("--recover-array finishes an existing initial distance study; do not combine with --full-survey/--stop-after")
    os.umask(0o077)
    workflow = Workflow(Path(__file__).absolute().parents[1], args.retry_failed, args.configure,
                        full_survey=args.full_survey, boundary=args.boundary or "dirichlet", recover_array=args.recover_array,
                        study_parameters=study_parameters, resource_requests=resource_requests,resume_run=args.resume_run,
                        excluded_nodes=None if args.exclude is None else [node for group in args.exclude for node in group.split(",")])
    workflow.locate()  # host, canonical roots and ownership before ANY mutation
    if args.status:
        path = workflow.bundle/"workflow.json"
        print(path.read_text() if path.exists() else "No workflow state yet: " + str(workflow.bundle))
        return 0
    workflow.prepare()
    if args.prepare_only:
        return 0
    lock_path = workflow.bundle/".workflow.lock"
    workflow.policy.require(not lock_path.is_symlink(), "unsafe workflow lock")
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.recover_array:
            workflow.recover_array()
        else:
            workflow.run(args.stop_after)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nController stopped. Submitted Slurm jobs continue; rerun run-hpc.sh to resume.", file=sys.stderr)
        sys.exit(130)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print("HPC workflow stopped: " + str(error), file=sys.stderr)
        print("Inspect hpc-runs/*/logs and preflight reports; rerun the same command after resolving the issue.", file=sys.stderr)
        sys.exit(2)
