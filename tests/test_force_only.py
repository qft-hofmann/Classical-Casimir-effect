"""The initial sweep performs one pair solve per gap and no extra force checks."""
import csv
import json
from types import SimpleNamespace

import numpy as np
import pytest

from classical_casimir import study
from classical_casimir.cluster import distance_study_manifest
from classical_casimir.postprocess import envelopes, plot_results


@pytest.mark.parametrize("force_only", [True, False])
def test_force_only_skips_extra_solves_and_evaluations(tmp_path, monkeypatch, force_only):
    case = dict(distance_study_manifest()["cases"][0], force_only=force_only,
                isolated=True, position_check=True, refinement=1)
    calls = dict(solve=0, momentum=0, isolated=0, position=0, far_field=0, quadrature=0)
    forces = np.array([[1., 2., 0.], [-1., 2., 0.]])

    def solve(mesh, wave, boundary, options):
        calls["solve"] += 1
        def far_field(points):
            calls["far_field"] += 1
            return np.zeros(points.shape[1], complex)
        return SimpleNamespace(mesh=mesh, diagnostics={}, density=SimpleNamespace(coefficients=np.zeros(2, complex)),
                               component_forces=lambda: forces, far_field=far_field)
    def momentum(solution, order):
        calls["momentum"] += 1
        return dict(force=np.array([0., 4., 0.]))
    def isolated(*args):
        calls["isolated"] += 1
        return dict(interaction_forces=forces)
    def position(*args, **kwargs):
        calls["position"] += 1
        return dict(force=forces[1])
    def quadrature(*args):
        calls["quadrature"] += 1
        return np.array([[0.], [1.], [0.]]), np.array([4*np.pi])
    monkeypatch.setattr(study, "solve", solve)
    monkeypatch.setattr(study, "momentum_force", momentum)
    monkeypatch.setattr(study, "interaction_forces", isolated)
    monkeypatch.setattr(study, "position_force", position)
    monkeypatch.setattr(study, "sphere_quadrature", quadrature)
    monkeypatch.setattr(study, "versions", lambda: {"bempp-cl": "test"})

    result = study.run_case(case, tmp_path/"results")
    assert result["separation_force"] == -1.
    assert calls["solve"] == 1
    if force_only:
        assert calls == dict(solve=1, momentum=0, isolated=0, position=0, far_field=0, quadrature=0)
        assert result["momentum"] is None and result["angular_difference"] is None
        assert "position_check" not in result and "interaction_forces" not in result
    else:
        assert calls == dict(solve=1, momentum=2, isolated=1, position=1, far_field=1, quadrature=1)
        assert result["momentum"] is not None and "position_check" in result
    folder = tmp_path/"results"/study.case_id(case)
    assert study.complete_result(folder, case)
    with np.load(folder/"arrays.npz") as arrays:
        assert ("far_field" in arrays.files) is (not force_only)
    assert study.run_case(case, tmp_path/"results")["resumed"] is True
    assert calls["solve"] == 1

    manifest = dict(schema_version=1, cases=[case])
    coverage = study.collect(manifest, tmp_path/"results", tmp_path/"collected")
    assert coverage["all_cases_computed"] is True and coverage["full_study_complete"] is False
    with (tmp_path/"collected/summary.csv").open() as stream:
        row = next(csv.DictReader(stream))
    assert (row["angular_difference"] == "") is force_only
    manifest_path = tmp_path/"manifest.json"
    study.atomic_json(manifest_path, manifest)
    assert envelopes(manifest_path, tmp_path/"results")[0]["empirical_error"] is None
    if force_only:
        monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path/"matplotlib"))
        plot_results(manifest_path, tmp_path/"results", tmp_path/"figures")
        assert (tmp_path/"figures/separation-forces.png").stat().st_size > 1000
        assert json.loads((tmp_path/"figures/envelopes.json").read_text())[0]["empirical_error"] is None
