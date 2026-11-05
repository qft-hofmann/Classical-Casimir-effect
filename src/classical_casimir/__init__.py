"""Component forces in exterior Helmholtz scattering.

The public force is -integral(T n), with the normal pointing from the
obstacle into the exterior. It is a Helmholtz force, before acoustic SI scaling.
"""

__version__ = "0.1.0"

from .model import PlaneWave, SolverOptions
from .geometry import SurfaceMesh, sphere, two_spheres

__all__ = ["PlaneWave", "SolverOptions", "SurfaceMesh", "sphere", "two_spheres"]

