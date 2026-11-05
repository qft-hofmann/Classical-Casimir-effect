"""Bootstrap and orchestration checks; simulated jobs do not validate BEM numerics."""
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def clone(tmp_path, monkeypatch):
    previous = os.umask(0o077)
    for name in ("HOME", "BIGWORK", "SOFTWARE", "PROJECT"):
        path = tmp_path/name
        path.mkdir()
        monkeypatch.setenv(name, str(path))
    root = tmp_path/"BIGWORK/repository"
    root.mkdir()
    for name in ("run-hpc.sh", "README.md", "pyproject.toml", "requirements-cluster.lock"):
        shutil.copyfile(ROOT/name, root/name)
    for name in ("src/classical_casimir", "docs", "scripts", "configs"):
        shutil.copytree(ROOT/name, root/name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    spec = importlib.util.spec_from_file_location("test_hpc_entry", root/"scripts/hpc.py")
    hpc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hpc)
    monkeypatch.setattr(socket, "gethostname", lambda: "login03")
    monkeypatch.chdir(root)
    yield root, hpc
    os.umask(previous)


def test_bootstrap_has_no_third_party_dependencies(tmp_path):
    target = ROOT/"src/classical_casimir/cluster_templates/bundle.py"
    code = "import runpy,sys; m=runpy.run_path(sys.argv[1]); assert len(m['distance_study_manifest']()['cases'])==150; assert 'numpy' not in sys.modules"
    result = subprocess.run(["/usr/bin/python3", "-I", "-S", "-B", "-c", code, str(target)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    result = subprocess.run(["bash", str(ROOT/"run-hpc.sh"), "--help"], capture_output=True, text=True)
    assert result.returncode == 0 and "--prepare-only" in result.stdout


def test_prepare_fresh_clone_without_environment(clone):
    root, hpc = clone
    wf = hpc.Workflow(root)
    wf.builder.survey_manifest = lambda: pytest.fail("default preparation must never create the full survey")
    wf.locate(); wf.prepare()
    assert wf.cfg["tasks"] == 150 and len(wf.cfg["batches"]) == 1
    assert wf.cfg["study_scope"]["boundary"] == "dirichlet"
    assert "max_concurrent" not in json.loads((wf.bundle/"operator-review.json").read_text())["resources"]
    assert not (wf.prefix/"bin/python").exists()
    assert not (root/"configs/survey.json").exists()  # generated without installation
    assert json.loads((wf.bundle/"resource-plan.json").read_text())["pilot_required"] is False
    assert list(Path(os.environ["HOME"]).iterdir()) == []


def test_clone_in_home_rejected_before_writes(clone):
    root, hpc = clone
    target = Path(os.environ["HOME"])/"repository"
    shutil.copytree(root, target)
    before = set(target.rglob("*"))
    with pytest.raises(ValueError, match="BIGWORK"):
        hpc.Workflow(target).locate()
    assert set(target.rglob("*")) == before


@pytest.mark.parametrize("host", ["login03", "login03.cluster.uni-hannover.de", "login03.internal"])
def test_login_preparation_does_not_depend_on_reverse_dns(clone, monkeypatch, host):
    root, hpc = clone
    monkeypatch.setattr(socket, "gethostname", lambda: host)
    monkeypatch.setattr(socket, "getfqdn", lambda: pytest.fail("login checks must not query reverse DNS"))
    wf = hpc.Workflow(root)
    wf.locate(); wf.prepare()
    assert wf.cfg["tasks"] == 150
    assert not (wf.prefix/"bin/python").exists()
    assert list(Path(os.environ["HOME"]).iterdir()) == []


@pytest.mark.parametrize("host", ["transfer", "transfer01.internal", "taurus001", "workstation", "login03-other"])
def test_nonlogin_host_rejected_before_writes(clone, monkeypatch, host):
    root, hpc = clone
    monkeypatch.setattr(socket, "gethostname", lambda: host)
    monkeypatch.setattr(socket, "getfqdn", lambda: "login03.cluster.uni-hannover.de")
    with pytest.raises(ValueError, match="observed hostname: " + repr(host)):
        hpc.Workflow(root).locate()
    assert not (root/"hpc-runs").exists()
    assert list(Path(os.environ["SOFTWARE"]).iterdir()) == []
    assert list(Path(os.environ["HOME"]).iterdir()) == []


def test_fingerprint_stable_across_git_metadata_but_changes_with_source(clone):
    root, hpc = clone
    original = hpc.fingerprint(root)
    (root/".git").mkdir()
    (root/".git/ignored-metadata").write_text("different checkout metadata")
    assert hpc.fingerprint(root) == original
    with (root/"scripts/hpc.py").open("a") as f: f.write("\n# changed workflow\n")
    assert hpc.fingerprint(root) != original


@pytest.mark.parametrize("text,good", [
    ("12_0|COMPLETED|0:0|\n12_1|COMPLETED|0:0|", True),
    ("12_0|COMPLETED|0:0|", False),
    ("12_[0-1]|COMPLETED|0:0|", False),
    ("12_0|RUNNING|0:0|\n12_1|COMPLETED|0:0|", False),
])
def test_accounting_needs_every_array_element(clone, text, good):
    _, hpc = clone
    assert hpc.accounting_status(text, "12", 0, 2) is good


def simulated_workflow(clone, monkeypatch, fail_smoke=False, full_survey=False, fail_study=False, legacy_distance=False,
                       study_parameters=None, resource_requests=None):
    root, hpc = clone
    wf = hpc.Workflow(root, full_survey=full_survey, study_parameters=study_parameters, resource_requests=resource_requests)
    if legacy_distance:
        historical = wf.builder.distance_study_manifest()
        historical["cases"] = [dict(historical["cases"][0], gap=round(i/10,1)) for i in range(1,81)]
        historical["study_scope"]["gaps"] = [case["gap"] for case in historical["cases"]]
        for key in ("samples", "gap_min", "gap_max", "sampling", "mesh_size", "requested_mesh_size", "triangles_per_sphere"):
            historical["study_scope"].pop(key, None)
        wf.manifest = historical
    wf.locate(); wf.prepare()
    (wf.prefix/"bin").mkdir(parents=True)
    (wf.prefix/"bin/python").write_text("existing interpreter")
    wf.legacy_python_before = (wf.prefix/"bin/python").read_bytes()
    jobs, sleeps, submissions, setups = {}, [], [], []
    monkeypatch.setattr(hpc.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(hpc, "number", lambda question, default, low, high: default)

    def review():
        data = json.loads((wf.bundle/"operator-review.json").read_text())
        data.update(configured_utc=dt.datetime.now(dt.timezone.utc).isoformat(), miniforge_module="Miniforge3/test")
        wf.builder.atomic_json(wf.bundle/"operator-review.json", data)
        return data
    monkeypatch.setattr(wf, "review", review)

    def shell(name, *args):
        assert name == "setup.sh"
        setups.append(name)
        with tarfile.open(wf.bundle/"source.tar.gz") as archive:
            archive.extractall(wf.bundle/"source", filter="data")
        wf.builder.atomic_json(wf.bundle/"environment.json", dict(
            release=wf.cfg["release"], prefix=str(wf.prefix), versions=wf.cfg["expected_versions"]))
    monkeypatch.setattr(wf, "shell", shell)

    def run(args):
        if args[0] == "id": return wf.user+"\n"
        if args[0] == "checkquota": return "quota for operator review\n"
        if args[0] == "squeue":
            assert "--jobs" in args, "controller may monitor its jobs, not manage the user's queue"
            record = jobs[args[args.index("--jobs")+1]]
            record["queries"] += 1
            return "running\n" if record["queries"] == 1 else ""
        if args[0] == "sacct":
            job = args[args.index("-j")+1]
            if "_" in job:
                base, index = job.split("_")
                record = jobs[base]
                record["accounted"] = True
                return job+"|COMPLETED|0:0|\n"
            record = jobs[job]
            record["accounted"] = True
            failed = (fail_smoke and record["mode"] == "smoke") or (fail_study and record["mode"] == "study")
            state = "FAILED|1:0" if failed else "COMPLETED|0:0"
            return "".join(job+"_"+str(i)+"|"+state+"|\n" for i in record.get("indices",range(record["start"],record["start"]+record["count"])))
        if args[0] == "seff": return "CPU and memory efficiency report\n"
        assert args[0] == "sbatch", args
        if "--test-only" in args: return ""
        assert all(record["accounted"] for record in jobs.values()), "next job queued before the previous one completed"
        selection = next(a.split("=",1)[1] for a in args if a.startswith("--array="))
        if "-" in selection:
            start,last = map(int,selection.split("-"))
            indices = list(range(start,last+1))
        else:
            indices = list(map(int,selection.split(",")))
        mode = next(a.split("casimir-",1)[1] for a in args if a.startswith("--job-name="))
        job = str(100+len(jobs))
        jobs[job] = dict(start=min(indices),count=len(indices),indices=indices,mode=mode,queries=0,accounted=False)
        submissions.append(args)
        if mode == "smoke":
            path = wf.bundle/"smoke-results/smoke-check.json"
            wf.builder.atomic_json(path, dict(passed=True, versions=wf.cfg["expected_versions"]))
            wf.builder.atomic_json(wf.bundle/"smoke-proof.json", dict(release=wf.cfg["release"], job_id=job+"_0", check_sha256=wf.policy.digest(path)))
        if mode == "postprocess":
            wf.builder.atomic_json(wf.bundle/"collected/coverage.json", dict(
                expected=wf.cfg["tasks"], computed=wf.cfg["tasks"],
                all_cases_computed=True, provenance_consistent=True, full_study_complete=False))
        return job+"\n"
    monkeypatch.setattr(wf.policy, "run", run)
    return wf, jobs, sleeps, submissions, setups


def test_full_workflow_and_resume_never_resubmit_completed_jobs(clone, monkeypatch):
    wf, jobs, sleeps, submissions, setups = simulated_workflow(clone, monkeypatch, full_survey=True)
    wf.run("all")
    assert len(submissions) == 15  # smoke + 4 pilots + 9 batches + collect/plot
    assert all(not a.startswith("--partition=") for args in submissions for a in args)
    assert len(setups) == 1 and set(sleeps) == {60}
    assert all(j["count"] <= 300 for j in jobs.values())
    assert [j["mode"] for j in jobs.values()] == ["smoke"]+["pilot"]*4+["campaign"]*9+["postprocess"]
    assert (wf.prefix/"bin/python").read_bytes() == wf.legacy_python_before
    assert list(Path(os.environ["SOFTWARE"]).iterdir()) == []
    wf.run("all")
    assert len(submissions) == 15 and len(setups) == 1


def test_failed_smoke_stops_before_pilots(clone, monkeypatch):
    wf, jobs, sleeps, submissions, setups = simulated_workflow(clone, monkeypatch, fail_smoke=True)
    with pytest.raises(ValueError, match="Slurm task failure"):
        wf.run("all")
    assert len(submissions) == 1 and "smoke" in json.loads(wf.state_path.read_text())["stages"]
    with pytest.raises(ValueError, match="Slurm task failure"):
        wf.run("all")
    assert len(submissions) == 1  # failure does not trigger implicit retry


def test_new_resource_profile_requires_fresh_pilots(clone, monkeypatch):
    wf, jobs, sleeps, submissions, setups = simulated_workflow(clone, monkeypatch, full_survey=True)
    wf.run("pilots")
    assert len(submissions) == 5
    data = json.loads((wf.bundle/"operator-review.json").read_text())
    data["resources"]["cpus_per_task"] = 4
    wf.builder.atomic_json(wf.bundle/"operator-review.json", data)
    wf.run("all")
    assert len(submissions) == 19  # four fresh pilots, nine arrays, postprocess
    assert len([j for j in jobs.values() if j["mode"] == "pilot"]) == 8


def test_default_stops_after_one_distance_curve_and_resumes_without_expansion(clone, monkeypatch):
    wf, jobs, sleeps, submissions, setups = simulated_workflow(clone, monkeypatch)
    monkeypatch.setattr(wf, "production_review", lambda pilots: pytest.fail("default must not enter full-survey review"))
    monkeypatch.setattr(wf.builder, "survey_manifest", lambda: pytest.fail("full survey must remain unselected"))
    wf.run("all")
    assert [j["mode"] for j in jobs.values()] == ["smoke", "study", "postprocess"]
    assert all(not a.startswith("--partition=") for args in submissions for a in args)
    study_jobs = [j for j in jobs.values() if j["mode"] == "study"]
    assert [j["count"] for j in study_jobs] == [150]
    study_args = next(args for args in submissions if "--job-name=casimir-study" in args)
    assert "--array=0-149" in study_args
    assert "--cpus-per-task=2" in study_args and "--mem=8G" in study_args
    assert len(setups) == 1 and set(sleeps) == {60}
    summary = json.loads((wf.bundle/"study-review.json").read_text())
    assert summary["stop_for_review"] is True and summary["full_survey_selected"] is False
    assert summary["scientific_validation"] == "requires review"
    assert summary["convergence_checks_performed"] is False
    assert summary["study_scope"]["boundary"] == "dirichlet"
    assert summary["study_scope"]["ka"] == 1.
    assert summary["study_scope"]["samples"] == 150 and summary["study_scope"]["gap_max"] == 20.
    coverage = json.loads((wf.bundle/"collected/coverage.json").read_text())
    assert coverage["full_study_complete"] is False  # scientific completion is never fabricated
    wf.run("all")
    assert len(submissions) == 3


def test_failed_distance_study_stops_before_postprocessing_or_expansion(clone, monkeypatch):
    wf, jobs, sleeps, submissions, setups = simulated_workflow(clone, monkeypatch, fail_study=True)
    with pytest.raises(ValueError, match="Slurm task failure"):
        wf.run("all")
    assert [j["mode"] for j in jobs.values()] == ["smoke", "study"]


@pytest.mark.parametrize("retry_fails_again",[False,True])
def test_resume_retries_only_sparse_failures_and_preserves_completed_data(clone,monkeypatch,retry_fails_again):
    wf,jobs,sleeps,submissions,setups = simulated_workflow(clone,monkeypatch)
    failed = [38,39,40,42,56,57,58,59]
    delegate = wf.policy.run
    def run(args):
        if args[0] == "sacct" and args[args.index("-j")+1] == "101":
            jobs["101"]["accounted"] = True
            return "".join(f"101_{i}|"+("FAILED|1:0|\n" if i in failed else "COMPLETED|0:0|\n") for i in range(150))
        if retry_fails_again and args[0] == "sacct" and args[args.index("-j")+1] == "102":
            jobs["102"]["accounted"] = True
            return "".join(f"102_{i}|"+("FAILED|1:0|\n" if i == 59 else "COMPLETED|0:0|\n") for i in failed)
        return delegate(args)
    monkeypatch.setattr(wf.policy,"run",run)
    with pytest.raises(ValueError,match="Slurm task failure"):
        wf.run("all")
    retained = wf.bundle/"results/completed/result.json"
    retained.parent.mkdir(parents=True)
    retained.write_text("completed sample")
    names = ["source.tar.gz","manifest.json","environment.json","smoke-proof.json"]
    snapshots = {name:(wf.bundle/name).read_bytes() for name in names}
    data = json.loads((wf.bundle/"operator-review.json").read_text())
    data["excluded_nodes"] = ["compute-test-03"]
    wf.builder.atomic_json(wf.bundle/"operator-review.json",data)
    wf.retry_failed = True
    wf.resume_run_path = wf.bundle
    original = wf.bundle
    with (wf.root/"scripts/hpc.py").open("a") as stream:
        stream.write("\n# later controller update\n")
    wf.locate(); wf.prepare()
    assert wf.bundle == original
    if retry_fails_again:
        with pytest.raises(ValueError,match="Slurm task failure"):
            wf.run("all")
    wf.run("all")
    count = 5 if retry_fails_again else 4
    assert len(submissions) == count  # original smoke/study, sparse retries, postprocessing
    assert "--array=38,39,40,42,56,57,58,59" in submissions[2]
    assert "--exclude=compute-test-03" in submissions[2]
    if retry_fails_again:
        assert "--array=59-59" in submissions[3]
    assert wf.state["stages"]["distance-study-0-retry"]["indices"] == failed
    assert retained.read_text() == "completed sample"
    assert all((wf.bundle/name).read_bytes() == content for name,content in snapshots.items())
    wf.retry_failed = False
    wf.run("all")
    assert len(submissions) == count  # recorded retries resume without renewed permission


def test_resume_restores_saved_scientific_parameters_without_retyping(clone):
    root,hpc = clone
    original = hpc.Workflow(root,boundary="neumann",study_parameters=dict(ka=2.,gap_max=30.,points=175))
    original.locate(); original.prepare(); original.save()
    before = (original.bundle/"manifest.json").read_bytes()
    resumed = hpc.Workflow(root,resume_run=original.bundle)
    resumed.locate(); resumed.prepare()
    assert resumed.plan == "distance-neumann-ka2" and resumed.cfg["tasks"] == 175
    assert (resumed.bundle/"manifest.json").read_bytes() == before


def test_large_requested_curve_uses_sequential_arrays_of_at_most_300(clone,monkeypatch):
    wf,jobs,sleeps,submissions,setups = simulated_workflow(clone,monkeypatch,
                                                        study_parameters=dict(points=451,gap_max=50.))
    wf.run("all")
    assert [(j["start"],j["count"]) for j in jobs.values() if j["mode"] == "study"] == [(0,300),(300,151)]
    assert all(j["accounted"] for j in jobs.values())
    assert len(submissions) == 4 and set(sleeps) == {60}
    summary = json.loads((wf.bundle/"study-review.json").read_text())
    assert summary["cases"] == 451 and summary["convergence_checks_performed"] is False


def guard_failure_workflow(clone, monkeypatch, problem=None):
    wf, jobs, sleeps, submissions, setups = simulated_workflow(clone, monkeypatch, legacy_distance=True)
    wf.run("smoke")
    original_job = "200"
    original = dict(job=original_job, start=0, count=80)
    wf.state["stages"]["distance-study-0"] = original
    wf.save()
    (wf.bundle/"logs/200_79.err").write_text(
        "different error\n" if problem == "different_error" else "LUIS preflight: allocation is not RUNNING\n")
    old_policy = b'"""Previous runtime allocation guard fixture."""\n'
    old_hash = hashlib.sha256(old_policy).hexdigest()
    monkeypatch.setattr(clone[1], "ARRAY_GUARD_OLD_SHA256", old_hash)
    (wf.bundle/"policy.py").write_bytes(old_policy)
    wf.cfg["sha256"]["policy.py"] = old_hash
    wf.builder.atomic_json(wf.bundle/"bundle.json", wf.cfg)
    jobs[original_job] = dict(mode="study", start=0, count=80, queries=0, accounted=False)
    delegate = wf.policy.run
    def run(args):
        if args[0] == "sacct" and args[args.index("-j")+1] == original_job:
            jobs[original_job]["accounted"] = True
            return "".join(f"200_{i}|" + ("FAILED|2:0|\n" if i == 79 else
                          "RUNNING|0:0|\n" if problem == "still_running" and i == 78 else "COMPLETED|0:0|\n")
                           for i in range(79 if problem == "missing_accounting" else 80))
        return delegate(args)
    monkeypatch.setattr(wf.policy, "run", run)
    return wf, jobs, submissions, old_policy


def test_recovery_preserves_frozen_run_and_retries_only_failed_element(clone, monkeypatch):
    wf, jobs, submissions, previous_policy = guard_failure_workflow(clone, monkeypatch)
    paths = [wf.bundle/p for p in ("source.tar.gz", "manifest.json", "environment.json", "smoke-proof.json")]
    retained = wf.bundle/"results/completed/result.json"
    retained.parent.mkdir(parents=True)
    retained.write_text("retained numerical result")
    paths.append(retained)
    before = {p: p.read_bytes() for p in paths}
    wf.recover_array()
    assert all(p.read_bytes() == content for p, content in before.items())
    assert (wf.bundle/"policy-before-array-guard.py").read_bytes() == previous_policy
    assert wf.state["stages"]["distance-study-0"]["job"] == "200"
    assert wf.state["stages"]["distance-study-0-retry-79"]["start"] == 79
    assert wf.state["stages"]["distance-study-0-retry-79"]["count"] == 1
    assert [j["mode"] for j in jobs.values()] == ["smoke", "study", "study", "postprocess"]
    assert "--array=79-79" in submissions[-2]
    assert len(submissions) == 3  # original smoke, one retry, collection/plot
    assert len([j for j in jobs.values() if j["mode"] == "smoke"]) == 1
    wf.policy.context(wf.bundle)  # repaired guard and all retained hashes verify
    with (wf.root/"src/classical_casimir/cluster_templates/policy.py").open("a") as stream:
        stream.write("\n# later checkout update must retain an already repaired guard\n")
    wf.recover_array()
    assert len(submissions) == 3  # repeat recovery resumes, never duplicates jobs
    assert (wf.prefix/"bin/python").read_bytes() == wf.legacy_python_before


@pytest.mark.parametrize("problem", ["still_running", "missing_accounting", "different_error", "unknown_guard"])
def test_recovery_rejects_unfinished_or_unrecognized_failures(clone, monkeypatch, problem):
    wf, jobs, submissions, previous_policy = guard_failure_workflow(clone, monkeypatch, problem)
    if problem == "unknown_guard":
        (wf.bundle/"policy.py").write_text("unrecognized guard")
    with pytest.raises(ValueError):
        wf.recover_array()
    assert len(submissions) == 1
    assert not (wf.bundle/"array-guard-repair.json").exists()
    if problem != "unknown_guard":
        assert (wf.bundle/"policy.py").read_bytes() == previous_policy


def test_recovery_selects_existing_run_after_checkout_changes(clone, monkeypatch):
    root, hpc = clone
    wf = hpc.Workflow(root)
    wf.locate(); wf.prepare()
    wf.save()
    original = wf.bundle
    with (root/"scripts/hpc.py").open("a") as stream:
        stream.write("\n# controller updated\n")
    normal = hpc.Workflow(root); normal.locate()
    assert normal.bundle != original
    recovered = hpc.Workflow(root, recover_array=original)
    recovered.locate(); recovered.prepare()
    assert recovered.bundle == original
    assert recovered.cfg["release"] == wf.cfg["release"]
    with pytest.raises(ValueError, match="existing run"):
        hpc.Workflow(root, recover_array=Path(os.environ["HOME"])).locate()


def test_plan_and_boundary_get_separate_resume_directories(clone):
    root, hpc = clone
    initial = hpc.Workflow(root); initial.locate()
    alternative = hpc.Workflow(root, boundary="neumann"); alternative.locate()
    broad = hpc.Workflow(root, full_survey=True); broad.locate()
    assert len({initial.bundle, alternative.bundle, broad.bundle}) == 3
    assert initial.plan == "distance-dirichlet-ka1"


def test_pilots_flag_cannot_implicitly_select_large_plan(clone):
    _, hpc = clone
    with pytest.raises(SystemExit) as error:
        hpc.main(["--stop-after", "pilots"])
    assert error.value.code == 2


def test_submission_recovered_after_disconnect_before_workflow_save(clone, monkeypatch):
    wf, jobs, sleeps, submissions, setups = simulated_workflow(clone, monkeypatch)
    wf.run("smoke")
    wf.state_path.unlink()
    root, hpc = clone
    resumed = hpc.Workflow(root)
    resumed.locate(); resumed.prepare()
    assert resumed.state["stages"]["smoke"]["job"] == "100"


@pytest.mark.parametrize("requests", [{}, dict(cpus_per_task=4,memory_gib=16,wall_minutes=15)])
def test_default_module_and_resources_need_no_yes_no_checks(clone, monkeypatch, requests):
    root, hpc = clone
    wf = hpc.Workflow(root, resource_requests=requests)
    wf.locate(); wf.prepare()
    def preflight(name):
        assert name == "preflight.sh"
        (wf.bundle/"preflight").mkdir()
        (wf.bundle/"preflight/quota.txt").write_text("CURRENT QUOTA REPORT")
    monkeypatch.setattr(wf, "shell", preflight)
    def live(args):
        assert args[0] == "bash", "preflight already saved all partition reports"
        assert "module load Miniforge3;" in args[-1]
        return "Miniforge3/24.11.3-0"
    monkeypatch.setattr(wf.policy, "run", live)
    monkeypatch.setattr(hpc.sys.stdin,"isatty",lambda:True)
    answers = iter([""]*3 if not requests else [])
    def answer(question):
        assert question.startswith(("GiB/task", "CPUs/task", "Minutes/task"))
        assert "yes/no" not in question and "Miniforge" not in question
        return next(answers)
    monkeypatch.setattr("builtins.input", answer)
    data = wf.review()
    assert data["configured_utc"]
    assert data["miniforge_module"] == "Miniforge3/24.11.3-0"
    assert data["partition"] is None
    assert "max_concurrent" not in data["resources"]
    assert "cpu_architecture_compatible" not in data
    assert "account_qos_partition_limits_checked" not in data
    assert "representative_pilots_and_efficiency_reviewed" not in data
    assert "research_and_teaching_only" not in data
    if requests:
        assert data["resources"] == requests


def test_entire_run_works_without_a_terminal_or_any_input(clone,monkeypatch):
    root,hpc = clone
    wf,jobs,sleeps,submissions,setups = simulated_workflow(clone,monkeypatch,
        resource_requests=dict(cpus_per_task=2,memory_gib=8,wall_minutes=15))
    monkeypatch.setattr(wf,"review",hpc.Workflow.review.__get__(wf))
    shell = wf.shell
    def preflight(name,*args):
        if name != "preflight.sh":
            return shell(name,*args)
        (wf.bundle/"preflight").mkdir(exist_ok=True)
        (wf.bundle/"preflight/quota.txt").write_text("quota report")
    monkeypatch.setattr(wf,"shell",preflight)
    delegate = wf.policy.run
    def run(args):
        if args[0] == "bash":
            assert "module load Miniforge3;" in args[-1]
            return "Miniforge3/23.11.0-0\n"  # default need not be the newest version
        return delegate(args)
    monkeypatch.setattr(wf.policy,"run",run)
    monkeypatch.setattr(hpc.sys.stdin,"isatty",lambda:False)
    monkeypatch.setattr("builtins.input",lambda question:pytest.fail("unexpected input: "+question))
    monkeypatch.setattr(hpc,"Workflow",lambda *args,**kwargs:wf)
    assert hpc.main(["--cpus","2","--memory-gib","8","--minutes","15"]) == 0
    assert len(submissions) == 3 and len(setups) == 1
    data = json.loads((wf.bundle/"operator-review.json").read_text())
    assert data["miniforge_module"] == "Miniforge3/23.11.0-0"
    assert all(j["accounted"] for j in jobs.values())


def test_failed_setup_log_is_retained_without_confirmation(clone,monkeypatch):
    wf,jobs,sleeps,submissions,setups = simulated_workflow(clone,monkeypatch)
    (wf.bundle/"logs/setup.log").write_text("old setup failure")
    monkeypatch.setattr("builtins.input",lambda question:pytest.fail("unexpected input: "+question))
    wf.run("smoke")
    retained = list((wf.bundle/"logs").glob("setup-failed-*.log"))
    assert len(retained) == 1 and retained[0].read_text() == "old setup failure"
    assert len(setups) == 1 and len(submissions) == 1


@pytest.mark.parametrize("point_flag", ["--points", "--steps"])
def test_command_line_prepares_custom_run_and_repeats_without_overwriting(clone, point_flag):
    root, hpc = clone
    args = ["--boundary","neumann","--ka","2","--gap-min",".25","--gap-max","40",point_flag,"175",
            "--direction","1","1","0","--mesh-level","2","--regular-order","4","--singular-order","7",
            "--rtol","1e-8","--maxiter","500","--cpus","4","--memory-gib","16","--minutes","15",
            "--exclude","compute-test-03","--prepare-only"]
    assert hpc.main(args) == 0
    bundle = next((root/"hpc-runs").iterdir())
    manifest = json.loads((bundle/"manifest.json").read_text())
    cfg = json.loads((bundle/"bundle.json").read_text())
    parameters = json.loads((bundle/"run-parameters.json").read_text())
    cases = manifest["cases"]
    assert len(cases) == 175 and cases[0]["gap"] == .25 and cases[-1]["gap"] == 40.
    assert all(case["boundary"] == "neumann" and case["k"] == 2. and case["refinement"] == 2 for case in cases)
    assert cases[0]["direction"] == pytest.approx([2**-.5,2**-.5,0])
    assert cases[0]["solver"] == dict(regular_order=4,singular_order=7,rtol=1e-8,maxiter=500,memory_gib=16.)
    assert parameters["requested_resources"] == dict(cpus_per_task=4,memory_gib=16,wall_minutes=15)
    assert parameters["excluded_nodes"] == ["compute-test-03"]
    assert parameters["study_scope"]["samples"] == 175
    policy = hpc.load(bundle/"policy.py","custom_run_policy")
    policy.validate_distance_study(bundle,cfg)
    before = {path.name:path.read_bytes() for path in bundle.iterdir() if path.is_file()}
    assert hpc.main(args) == 0
    assert all((bundle/name).read_bytes() == content for name,content in before.items())
    assert len(list((root/"hpc-runs").iterdir())) == 1
    assert list(Path(os.environ["HOME"]).iterdir()) == []


def test_run_identity_includes_effective_parameters_and_resources(clone):
    root,hpc = clone
    default = hpc.Workflow(root); default.locate()
    equivalent = hpc.Workflow(root, study_parameters=dict(gap_max=20.,points=150,direction=[0,2,0]),
                              resource_requests=dict(cpus_per_task=2,memory_gib=8,wall_minutes=45))
    equivalent.locate()
    assert equivalent.bundle == default.bundle
    bounded_mesh = hpc.Workflow(root, study_parameters=dict(mesh_size=.2))
    bounded_mesh.locate()
    assert bounded_mesh.bundle == default.bundle
    assert bounded_mesh.manifest["study_scope"]["requested_mesh_size"] == .2
    for options in (dict(study_parameters=dict(gap_max=40.)),dict(study_parameters=dict(points=151)),
                    dict(study_parameters=dict(ka=2.)),dict(study_parameters=dict(mesh_size=.4)),
                    dict(resource_requests=dict(cpus_per_task=4))):
        other = hpc.Workflow(root,**options); other.locate()
        assert other.bundle != default.bundle


@pytest.mark.parametrize("args", [["--gap-max","nan"],["--points","1"],["--direction","0","0","0"],
                                  ["--mesh-level","7"],["--mesh-size","nan"],["--mesh-size","0"],
                                  ["--mesh-size",".001"],["--regular-order","21"],["--cpus","0"]])
def test_invalid_command_line_parameters_fail_without_creating_run(clone,args):
    root,hpc = clone
    with pytest.raises(ValueError):
        hpc.main(args+["--prepare-only"])
    assert not (root/"hpc-runs").exists()


@pytest.mark.parametrize("requested,level", [(.7,1), (.4,2), (.2,3), (.1,4)])
def test_command_line_mesh_size_selects_bound_and_records_attained_size(clone, requested, level):
    root, hpc = clone
    assert hpc.main(["--mesh-size",str(requested),"--prepare-only"]) == 0
    bundle = next((root/"hpc-runs").iterdir())
    manifest = json.loads((bundle/"manifest.json").read_text())
    scope = json.loads((bundle/"run-parameters.json").read_text())["study_scope"]
    assert {c["refinement"] for c in manifest["cases"]} == {level}
    assert scope["requested_mesh_size"] == requested
    builder = hpc.load(bundle/"bundle.py","mesh_builder")
    assert scope["mesh_size"] <= requested < builder.SPHERE_MESH_SIZES[level-1]
    assert scope["triangles_per_sphere"] == 20*4**level
    assert list(Path(os.environ["HOME"]).iterdir()) == []


def test_mesh_size_and_level_are_mutually_exclusive(clone):
    root, hpc = clone
    with pytest.raises(SystemExit):
        hpc.main(["--mesh-size",".2","--mesh-level","3","--prepare-only"])
    builder = hpc.load(root/"src/classical_casimir/cluster_templates/bundle.py","mesh_builder")
    with pytest.raises(ValueError,match="not both"):
        builder.distance_study_manifest(refinement=3,mesh_size=.2)
    assert not (root/"hpc-runs").exists()


def test_local_profile_freezes_environment_module_and_pins(clone):
    root,hpc = clone
    (root/'configs/custom-pins.lock').write_text('bempp-cl==0.3.2\nnumpy==2.1.3\n')
    (root/'configs/luis.local.json').write_text(json.dumps(dict(
        environment_home_relative='.conda/envs/custom-bempp',
        miniforge_module='Miniforge3/test',requirements_file='configs/custom-pins.lock')))
    wf = hpc.Workflow(root); wf.locate(); wf.prepare()
    assert wf.prefix == Path(os.environ['HOME'])/'.conda/envs/custom-bempp'
    assert wf.cfg['expected_versions'] == {'bempp-cl':'0.3.2','numpy':'2.1.3'}
    assert json.loads((wf.bundle/'operator-review.json').read_text())['miniforge_module']=='Miniforge3/test'
    assert 'site-profile.json' in wf.cfg['sha256']
    old = wf.bundle
    (root/'configs/luis.local.json').write_text(json.dumps(dict(environment_home_relative='.conda/envs/new-bempp')))
    fresh = hpc.Workflow(root); fresh.locate()
    assert fresh.bundle != old
    resume = hpc.Workflow(root,resume_run=str(old)); resume.locate(); resume.prepare()
    assert resume.bundle == old and resume.prefix == wf.prefix
    assert resume.cfg['expected_versions'] == wf.cfg['expected_versions']


@pytest.mark.parametrize('override',[
    {'environment_home_relative':'../escape'}, {'environment_home_relative':'/outside'},
    {'miniforge_module':'Miniforge3;echo unsafe'}, {'requirements_file':'../outside'},
    {'typo':'ignored'},
])
def test_invalid_site_profile_rejected_before_bundle_writes(clone,override):
    root,hpc=clone
    (root/'configs/luis.local.json').write_text(json.dumps(override))
    with pytest.raises(ValueError): hpc.Workflow(root).locate()
    assert not (root/'hpc-runs').exists()


def test_older_bundle_without_site_profile_resumes_after_local_profile_change(clone,monkeypatch):
    wf,jobs,sleeps,submissions,setups = simulated_workflow(clone,monkeypatch,legacy_distance=True)
    cfg=json.loads((wf.bundle/'bundle.json').read_text())
    del cfg['sha256']['site-profile.json']
    (wf.bundle/'site-profile.json').unlink()
    wf.builder.atomic_json(wf.bundle/'bundle.json',cfg)
    wf.prepare(); wf.run('all')
    count=len(submissions)
    (wf.root/'configs/luis.local.json').write_text('{invalid current profile')
    wf.resume_run_path=wf.bundle
    wf.locate(); wf.prepare(); wf.run('all')
    assert len(submissions)==count
