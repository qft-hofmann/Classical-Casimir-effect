import numpy as np
import pytest
from classical_casimir import PlaneWave
from classical_casimir.model import acoustic_force
from classical_casimir.quadrature import sphere_quadrature
from classical_casimir.analytic import AnalyticSphere
from classical_casimir.forces import momentum_force, stress_tensor


@pytest.mark.parametrize("boundary", ["dirichlet", "neumann"])
@pytest.mark.parametrize("k", [.5, 1., np.pi, 5.])
def test_analytic_stress_vs_momentum(boundary, k):
    reference = AnalyticSphere(PlaneWave(k), boundary)
    f = reference.boundary_force(48)
    check = momentum_force(reference, 48)
    np.testing.assert_allclose(f, check["force"], atol=1e-10, rtol=1e-11)
    assert abs(check["optical_residual"]) < 1e-11
    assert f[1] > 0


def test_analytic_plane_wave_scaling_translation_and_lmax():
    a = AnalyticSphere(PlaneWave(2.), "neumann")
    b = AnalyticSphere(PlaneWave(2., amplitude=2-1j), "neumann", center=(.3, .1, -.1), lmax=40)
    np.testing.assert_allclose(b.boundary_force(), 5*a.boundary_force(), atol=1e-11)


def test_plane_wave_stress_is_positive_momentum_flux():
    wave = PlaneWave(1.7, (1, 2, 3), 2-1j)
    points = np.zeros((3, 2))
    tensor = stress_tensor(wave.values(points), wave.gradient(points), wave.k)
    expected = abs(wave.amplitude)**2*wave.k**2*np.outer(wave.direction, wave.direction)
    np.testing.assert_allclose(tensor, np.repeat(expected[:, :, None], 2, axis=2), atol=1e-13)
    # Acoustic SI scale follows the time-averaged pressure/velocity tensor.
    scaled = acoustic_force(tensor, wave.k, 1.2, 340.)
    np.testing.assert_allclose(scaled, tensor/(2*1.2*340**2*wave.k**2))


def test_angular_weights_and_input_validation():
    points, weights = sphere_quadrature(12)
    np.testing.assert_allclose(weights.sum(), 4*np.pi)
    np.testing.assert_allclose(points @ weights, 0., atol=1e-14)
    np.testing.assert_allclose(np.einsum('in,jn,n->ij', points, points, weights), np.eye(3)*4*np.pi/3, atol=1e-14)
    for k, direction in [(0, (0, 1, 0)), (1, (0, 0, 0)), (1, (np.nan, 0, 0))]:
        with pytest.raises(ValueError): PlaneWave(k, direction)

