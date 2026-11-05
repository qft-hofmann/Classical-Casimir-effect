"""Independent smooth-sphere partial waves, not a BEM reference fitted to itself."""
import numpy as np
from scipy.special import spherical_jn, spherical_yn, eval_legendre
from .model import PlaneWave, points3
from .quadrature import sphere_quadrature


class AnalyticSphere:
    def __init__(self, wave: PlaneWave, boundary="dirichlet", radius=1., center=(0., 0., 0.), lmax=None):
        if boundary not in ("dirichlet", "neumann") or radius <= 0:
            raise ValueError("invalid boundary or radius")
        self.wave, self.boundary, self.radius = wave, boundary, radius
        self.center = np.asarray(center, dtype=float)
        x = wave.k*radius
        self.lmax = int(np.ceil(x + 4*x**(1/3) + 12)) if lmax is None else int(lmax)
        self.l = np.arange(self.lmax+1)
        derivative = boundary == "neumann"
        j = spherical_jn(self.l, x, derivative=derivative)
        h = j + 1j*spherical_yn(self.l, x, derivative=derivative)
        self.t = -j/h

    def far_field(self, directions):
        directions = points3(directions)
        mu = np.asarray(self.wave.direction) @ directions
        series = sum((2*l+1)*t*eval_legendre(l, mu) for l, t in enumerate(self.t))
        phase = np.exp(1j*self.wave.k*(np.asarray(self.wave.direction)[:, None]-directions).T @ self.center)
        return -1j/self.wave.k*self.wave.amplitude*phase*series

    def scattered_field(self, points):
        points = points3(points)
        x = points-self.center[:, None]
        r = np.linalg.norm(x, axis=0)
        if np.any(r < self.radius*(1-1e-12)):
            raise ValueError("sphere reference only evaluates exterior points")
        mu = np.asarray(self.wave.direction) @ (x/r)
        series = 0j
        for l, t in enumerate(self.t):
            h = spherical_jn(l, self.wave.k*r) + 1j*spherical_yn(l, self.wave.k*r)
            series += (2*l+1)*(1j**l)*t*h*eval_legendre(l, mu)
        return self.wave.amplitude*np.exp(1j*self.wave.k*np.asarray(self.wave.direction) @ self.center)*series

    def boundary_force(self, order=40):
        n, weights = sphere_quadrature(order)
        mu = np.asarray(self.wave.direction) @ n
        x = self.wave.k*self.radius
        prefactor = self.wave.amplitude*np.exp(1j*self.wave.k*np.asarray(self.wave.direction) @ self.center)
        if self.boundary == "dirichlet":
            q = sum((2*l+1)*1j**l*self.wave.k*(spherical_jn(l, x, True) + t*(spherical_jn(l, x, True)+1j*spherical_yn(l, x, True)))*eval_legendre(l, mu) for l, t in enumerate(self.t))
            integrand = -0.5*abs(prefactor*q)**2
        else:
            phi, dphi = np.zeros(mu.shape, complex), np.zeros(mu.shape, complex)
            for l, t in enumerate(self.t):
                c = (2*l+1)*1j**l*(spherical_jn(l, x)+t*(spherical_jn(l, x)+1j*spherical_yn(l, x)))
                phi += c*eval_legendre(l, mu)
                if l:
                    dphi += c*l*(eval_legendre(l-1, mu)-mu*eval_legendre(l, mu))/(1-mu*mu)
            grad2 = abs(prefactor*dphi)**2*(1-mu*mu)/self.radius**2
            integrand = 0.5*(grad2-self.wave.k**2*abs(prefactor*phi)**2)
        return self.radius**2 * (n @ (weights*integrand))

