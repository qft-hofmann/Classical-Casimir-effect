"""Validated input types. Length and wavenumber must use reciprocal units."""
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class PlaneWave:
    k: float
    direction: tuple[float, float, float] = (0., 1., 0.)
    amplitude: complex = 1.

    def __post_init__(self):
        d = np.asarray(self.direction, dtype=float)
        if not np.isfinite(self.k) or self.k <= 0:
            raise ValueError("k must be finite and positive")
        if d.shape != (3,) or not np.all(np.isfinite(d)) or np.linalg.norm(d) == 0:
            raise ValueError("direction must be a finite nonzero 3-vector")
        if not np.isfinite(self.amplitude):
            raise ValueError("amplitude must be finite")
        object.__setattr__(self, "direction", tuple(d / np.linalg.norm(d)))
        object.__setattr__(self, "amplitude", complex(self.amplitude))

    def values(self, points):
        points = points3(points)
        return self.amplitude * np.exp(1j * self.k * np.asarray(self.direction) @ points)

    def gradient(self, points):
        return 1j * self.k * np.asarray(self.direction)[:, None] * self.values(points)


def points3(points):
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[0] != 3 or not np.all(np.isfinite(points)):
        raise ValueError("points must be finite with shape (3, N)")
    return points


@dataclass(frozen=True)
class SolverOptions:
    regular_order: int = 4
    singular_order: int = 4
    rtol: float = 1e-9
    maxiter: int = 300
    memory_gib: float = 8.

    def __post_init__(self):
        if (not isinstance(self.regular_order, int) or not isinstance(self.singular_order, int)
                or self.regular_order not in range(1, 21) or self.singular_order not in range(1, 21)):
            raise ValueError("quadrature orders must be integers between 1 and 20")
        if not 0 < self.rtol < 1 or self.maxiter < 1 or self.memory_gib <= 0:
            raise ValueError("invalid solver tolerance, iterations, or memory limit")


def acoustic_force(force, k, density, sound_speed):
    """Pressure phasor convention p(t)=Re(u exp(-i c k t)); return newtons.

    The mesh length unit must be metres and u must be in pascals.
    No additional amplitude factor: the Helmholtz force already includes it.
    """
    if min(k, density, sound_speed) <= 0:
        raise ValueError("k, density, and sound speed must be positive")
    return np.asarray(force) / (2 * density * sound_speed**2 * k**2)

