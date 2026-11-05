"""Product Gauss--Legendre/trapezoidal quadrature with area measure on S2."""
import numpy as np
from numpy.polynomial.legendre import leggauss


def sphere_quadrature(order=16):
    if not isinstance(order, int) or order < 2:
        raise ValueError("angular order must be an integer >= 2")
    z, w = leggauss(order)
    phi = np.arange(2*order) * (np.pi/order)
    radial = np.sqrt(1-z*z)[:, None]
    points = np.stack([radial*np.cos(phi), radial*np.sin(phi), np.broadcast_to(z[:, None], (order, 2*order))])
    weights = np.broadcast_to(w[:, None]*np.pi/order, (order, 2*order))
    return points.reshape(3, -1), weights.ravel()

