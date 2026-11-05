"""Exercise generated guards with isolated storage and a fake scheduler, never BEM/Slurm."""
import datetime as dt
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import runpy
import subprocess
import sys
import tarfile

import pytest

from classical_casimir.cluster import prepare, survey_manifest, distance_study_manifest


@pytest.fixture
def private_umask():
    previous = os.umask(0o077)
    yield
    os.umask(previous)


@pytest.fixture
def site(tmp_path, monkeypatch, private_umask):
    roots = {}
    for name in ("BIGWORK", "SOFTWARE", "HOME", "PROJECT"):
        roots[name] = tmp_path/name.lower()
        roots[name].mkdir()
        monkeypatch.setenv(name, str(roots[name]))
    legacy = roots["HOME"]/".conda/envs/bempp/bin"
    legacy.mkdir(parents=True)
    (legacy/"python").write_text("existing interpreter")
    (legacy/"python").chmod(0o700)
    manifest = tmp_path/"manifest.json"
    manifest.write_text(json.dumps(dict(schema_version=1, cases=[
        dict(k=1., boundary="dirichlet", gap=1., refinement=1),
        dict(k=1., boundary="neumann", gap=1., refinement=1)])))
    bundle = roots["BIGWORK"]/"bundle with spaces"
    prepare(manifest, bundle)
    spec = importlib.util.spec_from_file_location("luis_test_policy", bundle/"policy.py")
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    bundle, cfg, prefix, user = policy.context(bundle)
    result = dict(roots=roots, bundle=bundle, cfg=cfg, prefix=prefix, user=user, policy=policy)
    result["home_initial"] = home_state(result)
    return result


def home_state(site):
    root = site["roots"]["HOME"]
    return {str(p.relative_to(root)): None if p.is_dir() else p.read_bytes()
            for p in root.rglob("*")}


def policy_process(site, *args):
    return subprocess.run(["/usr/bin/python3", "-I", "-B", str(site["bundle"]/"policy.py"),
                           *args, "--bundle", str(site["bundle"])], capture_output=True, text=True)


def approve(site):
    path = site["bundle"]/"operator-review.json"
    data = json.loads(path.read_text())
    data.update(configured_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                miniforge_module="Miniforge3/test", pilot_job_ids=["90_0"])
    path.write_text(json.dumps(data))
    return data


def mark_ready(site):
    prefix = site["prefix"]
    with tarfile.open(site["bundle"]/"source.tar.gz") as archive:
        archive.extractall(site["bundle"]/"source", filter="data")
    (site["bundle"]/"environment.json").write_text(json.dumps(dict(
        release=site["cfg"]["release"], prefix=str(prefix), versions=site["cfg"]["expected_versions"])))


def test_generated_campaign_maps_every_case_once(tmp_path):
    manifest = tmp_path/"survey.json"
    data = survey_manifest()
    manifest.write_text(json.dumps(data))
    dest = tmp_path/"bundle"
    prepare(manifest, dest)
    cfg = json.loads((dest/"bundle.json").read_text())
    assert len(cfg["batches"]) == 9
    indices = [i for b in cfg["batches"] for i in range(b["start"], b["start"]+b["count"])]
    assert indices == list(range(2660))
    assert max(b["count"] for b in cfg["batches"]) == 300
    assert json.loads((dest/"manifest.json").read_text()) == data
    for script in [*dest.glob("*.sh"), *dest.glob("*.slurm")]:
        subprocess.run(["bash", "-n", str(script)], check=True)


def test_distance_study_is_one_dirichlet_curve_with_150_gaps_to_20(tmp_path):
    data = distance_study_manifest()
    cases = data["cases"]
    assert len(cases) == 150
    assert {c["boundary"] for c in cases} == {"dirichlet"}
    assert {c["k"] for c in cases} == {1.}
    assert {tuple(c["direction"]) for c in cases} == {(0., 1., 0.)}
    gaps = [c["gap"] for c in cases]
    assert len(set(gaps)) == 150 and gaps[0] == .1 and gaps[-1] == 20.
    assert all(b-a == pytest.approx(19.9/149, abs=2e-12) for a,b in zip(gaps,gaps[1:]))
    for gap in gaps:
        assert {(c["refinement"], c["solver"]["regular_order"], c["solver"]["singular_order"])
                for c in cases if c["gap"] == gap} == {(3, 6, 6)}
    assert all(c["force_only"] is True and c["isolated"] is False for c in cases)
    assert data["study_scope"]["convergence_checks"] is False
    assert data["study_scope"]["samples"] == 150 and data["study_scope"]["gap_max"] == 20.
    assert data["study_scope"]["sampling"] == "linear"
    dest = tmp_path/"initial"
    prepare(data, dest)
    cfg = json.loads((dest/"bundle.json").read_text())
    assert cfg["batches"] == [dict(index=0, start=0, count=150)]
    plan = json.loads((dest/"resource-plan.json").read_text())
    assert plan["pilot_required"] is False and plan["smoke_required"] is True
    assert "max_concurrent" not in plan and plan["memory_gib"] == 8
    review = json.loads((dest/"operator-review.json").read_text())
    assert "max_concurrent" not in review["resources"]
    assert "cpu_architecture_compatible" not in review
    assert "account_qos_partition_limits_checked" not in review


@pytest.mark.parametrize("bad", ["frequency", "multiple_boundaries", "fine_mesh", "large_gap", "above_20", "too_many_samples", "position_check", "extra_diagnostics", "quadrature_change"])
def test_study_mode_cannot_be_used_for_expensive_cases(site, bad):
    data = distance_study_manifest()
    if bad == "frequency": data["cases"][0]["k"] = 5.
    elif bad == "multiple_boundaries": data["cases"][0]["boundary"] = "neumann"
    elif bad == "fine_mesh": data["cases"][0]["refinement"] = 4
    elif bad == "large_gap": data["cases"][0]["gap"] = 1000.
    elif bad == "above_20": data["cases"][-1]["gap"] = 20.0001
    elif bad == "too_many_samples": data["cases"].append(dict(data["cases"][0], gap=.15))
    elif bad == "position_check": data["cases"][0]["position_check"] = True
    elif bad == "extra_diagnostics": data["cases"][0]["force_only"] = False
    else: data["cases"][0]["solver"]["regular_order"] = 8
    (site["bundle"]/"manifest.json").write_text(json.dumps(data))
    cfg = dict(site["cfg"], tasks=len(data["cases"]), study_scope=data["study_scope"], batches=[dict(index=0,start=0,count=len(data["cases"]))])
    with pytest.raises(ValueError): site["policy"].validate_distance_study(site["bundle"], cfg)


def test_large_campaign_cannot_bypass_pilot_gate_as_study(site):
    data = survey_manifest()
    (site["bundle"]/"manifest.json").write_text(json.dumps(data))
    cfg = dict(site["cfg"], study_scope=dict(kind="single-distance-study"))
    with pytest.raises(ValueError, match="scope"):
        site["policy"].validate_distance_study(site["bundle"], cfg)


def test_custom_distance_parameters_are_checked_without_hardcoded_range(site):
    data = distance_study_manifest("neumann",gap_min=.02,gap_max=50.,points=450,ka=2.,
                                    direction=(1,0,0),refinement=2,regular_order=5,singular_order=7,memory_gib=16.)
    (site["bundle"]/"manifest.json").write_text(json.dumps(data))
    cfg = dict(site["cfg"],tasks=450,study_scope=data["study_scope"],
               batches=[dict(index=0,start=0,count=300),dict(index=1,start=300,count=150)])
    site["policy"].validate_distance_study(site["bundle"],cfg)
    data["cases"][200]["k"] = 3.
    (site["bundle"]/"manifest.json").write_text(json.dumps(data))
    with pytest.raises(ValueError,match="parameters"):
        site["policy"].validate_distance_study(site["bundle"],cfg)


@pytest.mark.parametrize("name,value", [("BIGWORK", ""), ("SOFTWARE", "relative"), ("BIGWORK", "missing")])
def test_bad_root_fails_before_any_write(site, monkeypatch, name, value):
    before = set(site["bundle"].rglob("*"))
    monkeypatch.setenv(name, value)
    result = policy_process(site, "init")
    assert result.returncode != 0
    assert set(site["bundle"].rglob("*")) == before
    assert home_state(site) == site["home_initial"]


@pytest.mark.parametrize("root", ["HOME", "PROJECT", "SOFTWARE"])
def test_bundle_outside_bigwork_rejected_without_mutation(site, root):
    target = site["roots"][root]/"bundle"
    shutil.copytree(site["bundle"], target)
    before = set(target.rglob("*"))
    with pytest.raises(ValueError, match="BIGWORK"):
        site["policy"].context(target)
    assert set(target.rglob("*")) == before


def test_sibling_prefix_is_not_bigwork(site):
    dest = site["roots"]["BIGWORK"].with_name("bigwork-other")/"bundle"
    shutil.copytree(site["bundle"], dest)
    with pytest.raises(ValueError, match="BIGWORK"):
        site["policy"].context(dest)


def test_roots_cannot_alias_home(site, monkeypatch):
    alias = site["roots"]["BIGWORK"].parent/"alias"
    alias.symlink_to(site["roots"]["HOME"], target_is_directory=True)
    monkeypatch.setenv("SOFTWARE", str(alias))
    with pytest.raises(ValueError, match="overlaps HOME"):
        site["policy"].context(site["bundle"])


@pytest.mark.parametrize("name", ["results", "logs", "runtime", "source", "wheels", "smoke-results", "locks", "preflight"])
def test_output_alias_to_home_blocked_before_mkdir(site, name):
    path = site["bundle"]/name
    if path.exists():
        path.rmdir()
    path.symlink_to(site["roots"]["HOME"], target_is_directory=True)
    assert policy_process(site, "init").returncode != 0
    assert home_state(site) == site["home_initial"]


def test_nested_runtime_alias_rejected(site):
    runtime = site["bundle"]/"runtime"
    runtime.mkdir()
    (runtime/"tmp").symlink_to(site["roots"]["HOME"])
    assert policy_process(site, "init").returncode != 0
    assert home_state(site) == site["home_initial"]


def test_environment_alias_outside_home_rejected(site):
    shutil.rmtree(site["prefix"])
    site["prefix"].symlink_to(site["roots"]["SOFTWARE"])
    assert policy_process(site, "init").returncode != 0


def test_modified_executable_or_manifest_blocked(site):
    with (site["bundle"]/"worker.sh").open("a") as f:
        f.write("echo unsafe\n")
    result = policy_process(site, "init")
    assert result.returncode != 0 and "integrity" in result.stderr
    assert not (site["bundle"]/"runtime").exists()


def test_default_module_needs_no_manual_attestations_or_renewal(site):
    result = policy_process(site, "module")
    assert result.returncode == 0 and result.stdout.strip() == "Miniforge3"
    data = json.loads((site["bundle"]/"operator-review.json").read_text())
    assert "research_and_teaching_only" not in data
    assert "quota_bytes_inodes_and_grace_checked" not in data
    assert "backup_and_retention_planned" not in data
    assert "cpu_architecture_compatible" not in data
    assert "account_qos_partition_limits_checked" not in data
    data["reviewed_utc"] = (dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=2)).isoformat()
    data["research_and_teaching_only"] = False  # obsolete flags do not gate old runs
    (site["bundle"]/"operator-review.json").write_text(json.dumps(data))
    assert policy_process(site, "module").returncode == 0


def test_environment_paths_and_inherited_targets(site, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(site["roots"]["HOME"]))
    monkeypatch.setenv("PIP_TARGET", str(site["roots"]["HOME"] / "packages"))
    result = subprocess.run(["bash", "-c", 'source "$1/common.sh"; env', "_", str(site["bundle"])],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    env = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    assert "PYTHONPATH" not in env and "PIP_TARGET" not in env
    for key in ("TMPDIR", "TMP", "TEMP", "MPLCONFIGDIR", "NUMBA_CACHE_DIR", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR"):
        assert Path(env[key]).is_relative_to(site["roots"]["BIGWORK"])
    assert Path(env["CASIMIR_ENV"]) == site["roots"]["HOME"]/".conda/envs/bempp"
    for key in ("CONDA_ENVS_PATH", "CONDA_PKGS_DIRS", "PIP_CACHE_DIR", "UV_CACHE_DIR"):
        assert Path(env[key]).is_relative_to(site["roots"]["BIGWORK"])
    assert env["CONDA_REGISTER_ENVS"] == "false"
    assert env["PIP_CONFIG_FILE"] == "/dev/null"
    assert env["HOME"] == str(site["roots"]["HOME"])
    assert home_state(site) == site["home_initial"]


def scheduler(site, monkeypatch, bad_state=False):
    calls = []
    def fake(args):
        calls.append(args)
        if args[0] == "checkquota": return "operator-readable quota report\n"
        if args[0] == "squeue": pytest.fail("submission must leave queue management to Slurm")
        if args[0] == "sacct": return args[args.index("-j")+1]+"|"+("FAILED|1:0" if bad_state else "COMPLETED|0:0")+"|\n"
        if args[0] == "sbatch": return "" if "--test-only" in args else "100;cluster\n"
        raise AssertionError(args)
    monkeypatch.setattr(site["policy"], "run", fake)
    monkeypatch.setattr(site["policy"].socket, "gethostname", lambda: "login03")
    monkeypatch.setattr(site["policy"].socket, "getfqdn", lambda: pytest.fail("submission must not query reverse DNS"))
    return calls


@pytest.mark.parametrize("host", ["transfer", "transfer01.internal", "taurus001", "login03-other"])
def test_submission_rejects_nonlogin_hosts_before_scheduler_access(site, monkeypatch, host):
    policy = site["policy"]
    monkeypatch.setattr(policy.socket, "gethostname", lambda: host)
    monkeypatch.setattr(policy.socket, "getfqdn", lambda: "login03.cluster.uni-hannover.de")
    monkeypatch.setattr(policy, "run", lambda args: pytest.fail("host rejection must precede scheduler access"))
    monkeypatch.setattr(policy, "ready", lambda *args: pytest.fail("host rejection must precede environment checks"))
    with pytest.raises(ValueError, match="observed hostname: " + repr(host)):
        policy.submit(site["bundle"], site["cfg"], site["prefix"], site["user"], "smoke", None, False)
    assert not (site["bundle"]/"submissions.jsonl").exists()


def smoke_evidence(site):
    p = site["bundle"]/"smoke-results/smoke-check.json"
    p.parent.mkdir()
    p.write_text(json.dumps(dict(passed=True, versions=site["cfg"]["expected_versions"])))
    (site["bundle"]/"smoke-proof.json").write_text(json.dumps(dict(
        release=site["cfg"]["release"], job_id="80_0", check_sha256=site["policy"].digest(p))))


@pytest.mark.parametrize("partition", [None, "mpp.share", "amo"])
def test_submission_uses_absolute_paths_and_explicit_resources(site, monkeypatch, partition):
    mark_ready(site); data = approve(site)
    assert data["partition"] is None  # new bundles use the cluster's automatic policy
    data["partition"] = partition
    (site["bundle"]/"operator-review.json").write_text(json.dumps(data))
    calls = scheduler(site, monkeypatch)
    monkeypatch.setenv("SBATCH_OUTPUT", str(site["roots"]["HOME"] / "unsafe.log"))
    monkeypatch.setenv("SBATCH_PARTITION", "mpp.single")
    monkeypatch.setenv("SBATCH_NODELIST", "unrequested-node")
    monkeypatch.setenv("SBATCH_EXCLUSIVE", "yes")
    site["policy"].submit(site["bundle"], site["cfg"], site["prefix"], site["user"], "smoke", None, False)
    real = [c for c in calls if c[0] == "sbatch" and "--test-only" not in c]
    assert len(real) == 1
    args = real[0]
    assert "--array=0-0" in args and "--time=10" in args
    assert "--output="+str(site["bundle"]/"logs/%A_%a.out") in args
    assert "--error="+str(site["bundle"]/"logs/%A_%a.err") in args
    assert "--chdir="+str(site["bundle"]) in args
    assert "--nodes=1" in args and "--ntasks=1" in args
    checked = next(c for c in calls if c[0] == "sbatch" and "--test-only" in c)
    assert checked[2:] == args[2:]
    assert [a for a in args if a.startswith("--partition=")] == ([] if partition is None else ["--partition=" + partition])
    assert not any(a.startswith(("--nodelist", "--exclusive", "--gres", "--gpus")) for a in args)
    assert all("%" not in a for a in args if a.startswith("--array="))
    assert not any(key.startswith("SBATCH_") for key in os.environ)
    assert home_state(site) == site["home_initial"]


def test_dry_run_does_not_submit_or_create_state(site, monkeypatch):
    mark_ready(site); approve(site)
    calls = scheduler(site, monkeypatch)
    before = set(site["bundle"].rglob("*"))
    site["policy"].submit(site["bundle"], site["cfg"], site["prefix"], site["user"], "smoke", None, True)
    assert set(site["bundle"].rglob("*")) == before
    assert [c for c in calls if c[0] == "sbatch"] and all("--test-only" in c for c in calls if c[0] == "sbatch")


@pytest.mark.parametrize("loaded", ["Miniforge3/23.11.0-0", "Miniforge3/25.3.0-3:GCC/12"])
def test_lower_level_scripts_load_default_module_without_selection(site,loaded):
    shell = '''source "$1/common.sh"
    module() { if [[ $1 == purge ]]; then unset LOADEDMODULES; else
        [[ $2 == Miniforge3 ]] || exit 99; export LOADEDMODULES="$TEST_MODULE_STACK"; fi; }
    load_miniforge
    '''
    result = subprocess.run(["bash","-c",shell,"_",str(site["bundle"])],capture_output=True,text=True,
                            env=dict(os.environ,TEST_MODULE_STACK=loaded))
    assert (result.returncode == 0) is (":" not in loaded)
    assert home_state(site) == site["home_initial"]


def test_actual_scheduler_rejection_propagates_without_recording_a_job(site, monkeypatch):
    mark_ready(site); approve(site)
    calls = scheduler(site, monkeypatch)
    fake = site["policy"].run
    def reject(args):
        if args[0] == "sbatch" and "--test-only" not in args:
            calls.append(args)
            raise subprocess.CalledProcessError(1, args, stderr="QOSMaxSubmitJobPerUserLimit")
        return fake(args)
    monkeypatch.setattr(site["policy"], "run", reject)
    with pytest.raises(subprocess.CalledProcessError, match="sbatch"):
        site["policy"].submit(site["bundle"], site["cfg"], site["prefix"], site["user"], "smoke", None, False)
    assert len([c for c in calls if c[0] == "sbatch"]) == 2  # feasibility check, then submission
    assert not (site["bundle"]/"submissions.jsonl").exists()


@pytest.mark.parametrize("problem", ["no_smoke", "failed_job", "no_pilots", "bad_partition", "scheduler_rejects"])
def test_production_is_blocked_without_required_evidence(site, monkeypatch, problem):
    mark_ready(site); data = approve(site)
    calls = scheduler(site, monkeypatch, bad_state=problem == "failed_job")
    if problem != "no_smoke": smoke_evidence(site)
    if problem == "no_pilots": data["pilot_job_ids"] = []
    if problem == "bad_partition": data["partition"] = "mpp.single"
    (site["bundle"]/"operator-review.json").write_text(json.dumps(data))
    fake = site["policy"].run
    def more(args):
        if problem == "scheduler_rejects" and "--test-only" in args:
            raise subprocess.CalledProcessError(1, args, stderr="QOS denied")
        return fake(args)
    monkeypatch.setattr(site["policy"], "run", more)
    with pytest.raises((ValueError, OSError, subprocess.CalledProcessError)):
        site["policy"].submit(site["bundle"], site["cfg"], site["prefix"], site["user"], "campaign", 0, False)
    assert not any(c[0] == "sbatch" and "--test-only" not in c for c in calls)


def test_worker_rejects_missing_allocation_before_creating_runtime(site):
    result = subprocess.run(["bash", str(site["bundle"]/"worker.sh")], capture_output=True, text=True,
                            env={k:v for k,v in os.environ.items() if not k.startswith("SLURM_")})
    assert result.returncode != 0 and "allocation" in result.stderr
    assert not (site["bundle"]/"runtime").exists()


def executable(path, text):
    path.write_text(text)
    path.chmod(0o700)


@pytest.mark.parametrize("failure", [False, True])
def test_worker_redirects_all_runtime_writes_and_propagates_failure(site, monkeypatch, failure):
    mark_ready(site); approve(site)
    bin_dir = site["roots"]["BIGWORK"]/"fake-bin"
    bin_dir.mkdir()
    executable(bin_dir/"scontrol", '#!/bin/bash\nprintf "JobId=100 ArrayJobId=100 ArrayTaskId=0 JobState=RUNNING UserId=test(%s) NumNodes=1 NumCPUs=2\\n" "$(id -u)"\n')
    executable(bin_dir/"srun", '#!/bin/bash\nwhile [[ $1 == --* ]]; do shift; done\nexec "$@"\n')
    executable(site["prefix"]/"bin/python", '''#!/usr/bin/python3
import json, os, pathlib, sys
if any(x.endswith('verify-environment.py') for x in sys.argv): sys.exit(0)
output=pathlib.Path(sys.argv[sys.argv.index('--output')+1]); output.mkdir(exist_ok=True)
keys=('OMP_NUM_THREADS','NUMBA_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','TMPDIR')
(output/'runtime.json').write_text(json.dumps({k:os.environ[k] for k in keys}))
if '--smoke' in sys.argv:
    cfg=json.loads(pathlib.Path(os.environ['CASIMIR_BUNDLE'],'bundle.json').read_text())
    (output/'smoke-check.json').write_text(json.dumps(dict(passed=True,versions=cfg['expected_versions'])))
sys.exit(17 if os.environ.get('FAKE_FAILURE') else 0)
''')
    monkeypatch.setenv("PATH", str(bin_dir)+":"+os.environ["PATH"])
    for key, value in dict(SLURM_JOB_ID="100", SLURM_ARRAY_JOB_ID="100", SLURM_ARRAY_TASK_ID="0", SLURM_NTASKS="1",
                           SLURM_CPUS_PER_TASK="2", CASIMIR_SUBMIT_MODE="smoke").items():
        monkeypatch.setenv(key, value)
    if failure: monkeypatch.setenv("FAKE_FAILURE", "1")
    before = home_state(site)
    shell = 'module() { if [[ $1 == load ]]; then export LOADEDMODULES="$2"; else unset LOADEDMODULES; fi; }; conda() { return 0; }; script=$1; shift; source "$script"'
    result = subprocess.run(["bash", "-c", shell, "_", str(site["bundle"]/"worker.sh")], capture_output=True, text=True)
    assert result.returncode == (17 if failure else 0), result.stderr
    env = json.loads((site["bundle"]/"smoke-results/runtime.json").read_text())
    assert env["OMP_NUM_THREADS"] == env["NUMBA_NUM_THREADS"] == "2"
    assert env["OPENBLAS_NUM_THREADS"] == env["MKL_NUM_THREADS"] == "1"
    assert Path(env["TMPDIR"]).is_relative_to(site["bundle"]/"runtime")
    assert not Path(env["TMPDIR"]).exists()  # EXIT trap on success and failure
    assert home_state(site) == before
    assert (site["bundle"]/"smoke-proof.json").exists() is (not failure)


def test_direct_batch_file_never_runs_worker_or_writes_home(site):
    for name in ("smoke.slurm", "campaign.slurm"):
        result = subprocess.run(["bash", str(site["bundle"]/name)], capture_output=True, text=True,
                                env={k:v for k,v in os.environ.items() if k != "CASIMIR_SUBMIT_MODE"})
        assert result.returncode != 0
    assert not (site["bundle"]/"runtime").exists()
    assert home_state(site) == site["home_initial"]


def test_setup_reuses_existing_environment_without_installing_or_writing_home(site):
    approve(site)
    executable(site["prefix"]/"bin/python", """#!/usr/bin/python3
import json, os, pathlib, sys
assert any(x.endswith('verify-environment.py') for x in sys.argv)
bundle=pathlib.Path(os.environ['CASIMIR_BUNDLE'])
cfg=json.loads((bundle/'bundle.json').read_text())
if '--record' in sys.argv:
    (bundle/'environment.json').write_text(json.dumps(dict(release=cfg['release'],prefix=os.environ['CASIMIR_ENV'],versions=cfg['expected_versions'])))
""")
    before=home_state(site)
    shell='''module() { if [[ $1 == load ]]; then export LOADEDMODULES="$2"; else unset LOADEDMODULES; fi; }
conda() { [[ $# == 2 && $1 == activate && $2 == "$CASIMIR_ENV" ]] || return 99; }
script=$1; shift; source "$script"
'''
    result=subprocess.run(["bash","-c",shell,"_",str(site["bundle"]/"setup.sh")],capture_output=True,text=True)
    assert result.returncode==0, (site["bundle"]/"logs/setup.log").read_text()
    site["policy"].ready(site["bundle"],site["prefix"],site["cfg"])
    assert home_state(site)==before
    assert list(site["roots"]["SOFTWARE"].iterdir())==[]
    assert not (site["bundle"]/"wheels").exists()


def test_existing_runtime_needs_no_software_root(site, monkeypatch):
    monkeypatch.delenv("SOFTWARE")
    assert policy_process(site,"init").returncode==0
    assert home_state(site)==site["home_initial"]


def test_runtime_record_detects_package_drift_without_touching_home(site, monkeypatch):
    monkeypatch.setattr(sys, "prefix", str(site["prefix"]))
    monkeypatch.setenv("CASIMIR_ENV", str(site["prefix"]))
    monkeypatch.setenv("CASIMIR_BUNDLE", str(site["bundle"]))
    versions = dict(site["cfg"]["expected_versions"])
    monkeypatch.setattr(importlib.metadata, "version", versions.__getitem__)
    script = str(site["bundle"]/"verify-environment.py")
    monkeypatch.setattr(sys, "argv", [script, "--inspect"])
    runpy.run_path(script, run_name="__main__")
    assert not (site["bundle"]/"environment.json").exists()
    monkeypatch.setattr(sys, "argv", [script, "--record"])
    runpy.run_path(script, run_name="__main__")
    record = (site["bundle"]/"environment.json").read_bytes()
    monkeypatch.setattr(sys, "argv", [script])
    runpy.run_path(script, run_name="__main__")
    versions["numpy"] = "1.26.4"
    with pytest.raises(AssertionError, match="numpy"):
        runpy.run_path(script, run_name="__main__")
    assert (site["bundle"]/"environment.json").read_bytes() == record
    assert home_state(site) == site["home_initial"]


def test_smoke_from_a_different_runtime_cannot_unlock_sweep(site, monkeypatch):
    smoke_evidence(site)
    check = site["bundle"]/"smoke-results/smoke-check.json"
    data = json.loads(check.read_text())
    data["versions"]["bempp-cl"] = "0.4.2"
    check.write_text(json.dumps(data))
    monkeypatch.setattr(site["policy"], "completed", lambda job: None)
    with pytest.raises(ValueError, match="legacy profile"):
        site["policy"].smoke_passed(site["bundle"], site["cfg"])


def test_nested_source_alias_is_rejected(site):
    mark_ready(site)
    source = site["bundle"]/"source/src"
    other = site["roots"]["BIGWORK"]/"other-source"
    source.rename(other)
    source.symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError, match="staged"):
        site["policy"].ready(site["bundle"], site["prefix"], site["cfg"])


def test_staged_code_changes_are_rejected_before_submission(site, monkeypatch):
    mark_ready(site); approve(site)
    calls=scheduler(site,monkeypatch)
    with (site["bundle"]/"source/src/classical_casimir/solver.py").open("a") as stream:
        stream.write("\n# changed after staging\n")
    with pytest.raises(ValueError,match="staged application changed"):
        site["policy"].submit(site["bundle"],site["cfg"],site["prefix"],site["user"],"smoke",None,False)
    assert not calls


def test_isolated_launcher_runs_staged_source_without_installation(site, monkeypatch):
    mark_ready(site)
    monkeypatch.setenv("PYTHONPATH",str(site["roots"]["HOME"]))
    result=subprocess.run([sys.executable,"-I","-B",str(site["bundle"]/"run-project.py"),"task",
                           "--manifest",str(site["bundle"]/"manifest.json"),"--task-id","0",
                           "--output",str(site["bundle"]/"results"),"--dry-run"],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)["case"]["boundary"]=="dirichlet"
    assert home_state(site)==site["home_initial"]


@pytest.mark.parametrize("wrong", ["memory_expands_cpus", "not_running", "wrong_user", "multiple_nodes"])
def test_allocation_matches_actual_scheduler_record(site, monkeypatch, wrong):
    for k, v in dict(SLURM_JOB_ID="100", SLURM_NTASKS="1", SLURM_CPUS_PER_TASK="2").items():
        monkeypatch.setenv(k, v)
    values = dict(JobId="100", JobState="RUNNING", UserId="me("+str(os.getuid())+")", NumNodes="1", NumCPUs="2")
    key, value = {"memory_expands_cpus": ("NumCPUs", "8"), "not_running": ("JobState", "PENDING"),
                  "wrong_user": ("UserId", "other(999999)"), "multiple_nodes": ("NumNodes", "2")}[wrong]
    values[key] = value
    monkeypatch.setattr(site["policy"], "run", lambda args: " ".join(k+"="+v for k,v in values.items()))
    with pytest.raises(ValueError): site["policy"].allocation()


@pytest.mark.parametrize("task,job", [("79", "7100"), ("0", "7101"), (None, "7102")])
def test_allocation_queries_only_current_array_element(site, monkeypatch, task, job):
    monkeypatch.setattr(site["policy"].socket, "gethostname", lambda: "enos-n023")
    for key, value in dict(SLURM_JOB_ID=job, SLURM_NTASKS="1", SLURM_CPUS_PER_TASK="2").items():
        monkeypatch.setenv(key, value)
    for key in ("SLURM_ARRAY_JOB_ID", "SLURM_ARRAY_TASK_ID"):
        monkeypatch.delenv(key, raising=False)
    fields = dict(JobId=job, JobState="RUNNING", UserId=f"me({os.getuid()})", NumNodes="1", NumCPUs="2")
    if task is not None:
        monkeypatch.setenv("SLURM_ARRAY_JOB_ID", "7100")
        monkeypatch.setenv("SLURM_ARRAY_TASK_ID", task)
        fields.update(ArrayJobId="7100", ArrayTaskId=task)
    line = " ".join(k+"="+v for k,v in fields.items())
    calls = []
    def scontrol(args):
        calls.append(args)
        if task is not None and args[3] == "7100":
            # The old query merges the running element with a pending sibling.
            return line + "\nJobId=7200 ArrayJobId=7100 ArrayTaskId=1 JobState=PENDING\n"
        return line + "\n"
    monkeypatch.setattr(site["policy"], "run", scontrol)
    assert site["policy"].allocation() == (job, 2)
    assert calls == [["scontrol", "show", "job", "7100_"+task if task is not None else job, "--oneliner"]]


@pytest.mark.parametrize("problem", ["multiple_records", "wrong_job", "wrong_array", "wrong_task", "partial_identity"])
def test_allocation_rejects_ambiguous_or_wrong_identity(site, monkeypatch, problem):
    monkeypatch.setattr(site["policy"].socket, "gethostname", lambda: "enos-n023")
    for key, value in dict(SLURM_JOB_ID="100", SLURM_ARRAY_JOB_ID="100", SLURM_ARRAY_TASK_ID="79",
                           SLURM_NTASKS="1", SLURM_CPUS_PER_TASK="2").items():
        monkeypatch.setenv(key, value)
    fields = dict(JobId="100", ArrayJobId="100", ArrayTaskId="79", JobState="RUNNING",
                  UserId=f"me({os.getuid()})", NumNodes="1", NumCPUs="2")
    if problem == "wrong_job": fields["JobId"] = "101"
    if problem == "wrong_array": fields["ArrayJobId"] = "101"
    if problem == "wrong_task": fields["ArrayTaskId"] = "78"
    if problem == "partial_identity": monkeypatch.delenv("SLURM_ARRAY_TASK_ID")
    line = " ".join(k+"="+v for k,v in fields.items()) + "\n"
    monkeypatch.setattr(site["policy"], "run", lambda args: line * (2 if problem == "multiple_records" else 1))
    with pytest.raises(ValueError): site["policy"].allocation()


def test_linked_task_artifact_rejected_before_compute(site, monkeypatch):
    from classical_casimir.study import case_id
    case = json.loads((site["bundle"]/"manifest.json").read_text())["cases"][0]
    directory = site["bundle"]/"results"/case_id(case)
    directory.mkdir(parents=True)
    target = site["roots"]["HOME"]/"keep.txt"
    target.write_text("preserve")
    (directory/"result.json").symlink_to(target)
    monkeypatch.setenv("SLURM_ARRAY_TASK_ID", "0")
    monkeypatch.setenv("CASIMIR_SUBMIT_MODE", "campaign")
    result = policy_process(site, "task-check")
    assert result.returncode != 0 and "symlink" in result.stderr
    assert target.read_text() == "preserve"


def test_log_symlink_prevents_scheduler_submission(site, monkeypatch):
    mark_ready(site); approve(site)
    calls = scheduler(site, monkeypatch)
    (site["bundle"]/"logs/100_0.out").symlink_to(site["roots"]["HOME"]/"unsafe")
    with pytest.raises(ValueError, match="symlink"):
        site["policy"].submit(site["bundle"], site["cfg"], site["prefix"], site["user"], "smoke", None, False)
    assert not any(args[0] == "sbatch" for args in calls)
    assert home_state(site) == site["home_initial"]
