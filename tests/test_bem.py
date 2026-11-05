"""Optional actual BEM regression; the validation campaign records richer evidence."""
import numpy as np
import pytest
from classical_casimir import PlaneWave, sphere
from classical_casimir.solver import solve
from classical_casimir.analytic import AnalyticSphere


@pytest.mark.bem
@pytest.mark.parametrize("boundary", ["dirichlet", "neumann"])
def test_force_improves_towards_analytic_sphere(boundary):
    wave = PlaneWave(1.)
    exact = AnalyticSphere(wave, boundary).boundary_force()
    errors = [np.linalg.norm(solve(sphere(refinement=l), wave, boundary).component_forces()[0]-exact) for l in (0, 1, 2)]
    assert errors[2] < errors[1] < errors[0]

