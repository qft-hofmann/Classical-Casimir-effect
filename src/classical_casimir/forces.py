"""Independent force identities in physical plane-wave normalization.

u=A exp(ik d.x)+exp(ikr)f(theta)/r+O(r^-2).
No L2 norm is assigned to a delta-function incident channel.
"""
import numpy as np
from .quadrature import sphere_quadrature
from .solver import solve


def momentum_force(solution, order=16):
    theta, weights = sphere_quadrature(order)
    f = solution.far_field(theta)
    wave = solution.wave
    forward = solution.far_field(np.asarray(wave.direction)[:, None])[0]
    cross = float(np.dot(weights, abs(f)**2))
    extinction = 4*np.pi/wave.k*np.imag(np.conj(wave.amplitude)*forward)
    force = wave.k**2*(extinction*np.asarray(wave.direction) - theta @ (weights*abs(f)**2))
    return dict(force=force, optical_residual=float(extinction-cross), scattering_integral=cross,
                extinction=float(extinction), angular_order=order)


def position_force(solution, component, step=0.01, order=16, options=None, axes=(0, 1, 2)):
    """Translate one component, hold global channels and amplitude fixed.

    F_j=2 pi Re(conj(A) partial_j f(d))
        +k Im integral(conj(f(theta)) partial_j f(theta)) dtheta.
    Return centered differences at h and h/2, without hiding their discrepancy.
    """
    if not np.isfinite(step) or step <= 0:
        raise ValueError("step must be finite and positive")
    theta, weights = sphere_quadrature(order)
    d = np.asarray(solution.wave.direction)[:, None]
    directions = np.concatenate([theta, d], axis=1)
    f = solution.far_field(theta)
    estimates = []
    for h in (step, step/2):
        force = np.full(3, np.nan)
        for axis in axes:
            shift = np.eye(3)[axis]*h
            plus = solve(solution.mesh.translated(shift, component), solution.wave, solution.boundary, options)
            minus = solve(solution.mesh.translated(-shift, component), solution.wave, solution.boundary, options)
            derivative = (plus.far_field(directions)-minus.far_field(directions))/(2*h)
            force[axis] = 2*np.pi*np.real(np.conj(solution.wave.amplitude)*derivative[-1]) + solution.wave.k*np.imag(np.dot(weights, np.conj(f)*derivative[:-1]))
        estimates.append(force)
    return dict(force=estimates[1], coarse_force=estimates[0],
                step_difference=np.abs(estimates[1]-estimates[0]), step=step, angular_order=order)


def interaction_forces(solution, options=None):
    isolated = np.array([solve(solution.mesh.component(tag), solution.wave, solution.boundary, options).component_forces()[0]
                         for tag in solution.mesh.components])
    force = solution.component_forces()
    return dict(forces=force, isolated_forces=isolated, interaction_forces=force-isolated)


def stress_tensor(u, gradient, k):
    """T_ij=Re(partial_i u conj(partial_j u))-.5 delta_ij(|grad u|²-k²|u|²)."""
    u, gradient = np.asarray(u), np.asarray(gradient)
    if gradient.shape != (3, len(u)):
        raise ValueError("incompatible field/gradient shapes")
    tensor = np.real(gradient[:, None, :]*gradient[None, :, :].conj())
    trace = np.sum(abs(gradient)**2, axis=0)-k*k*abs(u)**2
    return tensor - np.eye(3)[:, :, None]*trace/2

