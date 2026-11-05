import hashlib
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
import pytest
from classical_casimir.study import atomic_json, case_id, complete_result, collect, sign_brackets
from classical_casimir.budget import run_budgeted
from classical_casimir.cluster import survey_manifest, prepare
from classical_casimir.cli import main


def fixture_result(root, case):
    dest = root/case_id(case); dest.mkdir(parents=True)
    np.savez(dest/"arrays.npz", forces=np.ones((2, 3)))
    np.savez(dest/"mesh.npz", vertices=np.zeros((3, 3)))
    result = dict(schema_version=1, status="computed", case=case, source_sha256="abc", versions={"bempp-cl":"test"},
                  seconds=1, separation_force=1., total_force=[0, 1, 0], momentum_difference=[0, 0, 0], angular_difference=[0, 0, 0],
                  artifact_sha256={name:hashlib.sha256((dest/name).read_bytes()).hexdigest() for name in ("arrays.npz", "mesh.npz")})
    atomic_json(dest/"result.json", result)
    return dest


def test_resumption_and_partial_collection(tmp_path):
    case = dict(k=1., boundary="neumann", gap=2., refinement=1)
    dest = fixture_result(tmp_path, case)
    assert complete_result(dest, case, "abc", {"bempp-cl":"test"})
    assert not complete_result(dest, case, "changed", {"bempp-cl":"test"})
    assert not complete_result(dest, case, "abc", {"bempp-cl":"other"})
    status = collect(dict(schema_version=1, cases=[case, dict(case, gap=3.)]), tmp_path, tmp_path/"collected")
    assert status["computed"] == 1 and len(status["pending"]) == 1 and not status["full_study_complete"]
    (dest/"arrays.npz").write_bytes(b"corrupt")
    assert not complete_result(dest, case)


def test_watchdog_stops_and_records_timeout(tmp_path):
    result = run_budgeted([sys.executable, "-c", "import time; time.sleep(5)"], tmp_path/"sleep.log", seconds=.2)
    assert result["stopped_by"] == "wall_time_limit" and result["seconds"] < 4
    assert (tmp_path/"sleep.budget.json").exists()
    with pytest.raises(ValueError): run_budgeted([], tmp_path/"x", seconds=1201)


def test_cluster_dispatch_and_scripts(tmp_path, capsys):
    cases = [dict(k=1., boundary="dirichlet", gap=g, refinement=1) for g in (1., 2.)]
    manifest = tmp_path/"input.json"
    atomic_json(manifest, dict(schema_version=1, cases=cases))
    bundle = tmp_path/"bundle"
    result = prepare(manifest, bundle)
    assert result["tasks"] == 2 and result["submitted"] is False
    for name in ("worker.sh", "setup.sh", "campaign.slurm", "smoke.slurm"):
        subprocess.run(["bash", "-n", str(bundle/name)], check=True)
    main(["task", "--manifest", str(manifest), "--task-id", "1", "--output", str(tmp_path/"results"), "--dry-run"])
    assert json.loads(capsys.readouterr().out)["id"] == case_id(cases[1])
    with pytest.raises(ValueError):
        main(["task", "--manifest", str(manifest), "--task-id", "-1", "--output", str(tmp_path), "--dry-run"])


def test_survey_is_complete_without_duplicate_tasks():
    data = survey_manifest()
    ids = [case_id(case) for case in data["cases"]]
    assert len(ids) == len(set(ids))
    transverse = [c for c in data["cases"] if c["direction"] == [0., 1., 0.] and not c.get("position_check")]
    assert len(transverse) >= 2*4*80*3
    assert set(c["boundary"] for c in transverse) == {"dirichlet", "neumann"}


def test_uncertain_signs_not_promoted_to_roots():
    assert sign_brackets([(1, -1., .1), (2, 2., .1)]) == [[1, 2]]
    assert sign_brackets([(1, -1., 2.), (2, 2., .1)]) == []


def test_sign_refinement_requires_mesh_and_quadrature_evidence(tmp_path):
    from classical_casimir.postprocess import envelopes, refinement_manifest
    cases = []
    for gap, sign in [(1., -1), (2., 1)]:
        for level, value in [(1, .8), (2, .95), (3, 1.)]:
            case = dict(k=1., boundary="neumann", gap=gap, refinement=level)
            folder = fixture_result(tmp_path, case)
            result = json.loads((folder/"result.json").read_text())
            result['separation_force'] = value*sign
            atomic_json(folder/"result.json", result); cases.append(case)
    manifest = tmp_path/"manifest.json"
    atomic_json(manifest, dict(schema_version=1, cases=cases))
    assert all(row['sign'] == 'unresolved' for row in envelopes(manifest, tmp_path))
    for gap, sign in [(1., -1), (2., 1)]:
        case = dict(k=1., boundary="neumann", gap=gap, refinement=3, solver=dict(regular_order=6, singular_order=6))
        folder = fixture_result(tmp_path, case)
        result = json.loads((folder/"result.json").read_text()); result['separation_force'] = 1.01*sign
        atomic_json(folder/"result.json", result); cases.append(case)
    atomic_json(manifest, dict(schema_version=1, cases=cases))
    followup = refinement_manifest(manifest, tmp_path)
    assert len(followup['cases']) == 4
    assert {case['gap'] for case in followup['cases']} == {1.5}


