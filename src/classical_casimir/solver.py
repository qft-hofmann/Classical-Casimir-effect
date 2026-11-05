"""Direct, combined-field exterior BEM with total Cauchy traces.

G=exp(ikr)/(4 pi r); n points from the obstacle into the exterior;
W=-gamma_1 D. Exterior representation: u=u_inc+D phi-S q.
The combined equations avoid real interior eigenvalue failures of a plain
single-layer inversion. All matrices use Galerkin weak forms and mass
preconditioning; the diagnostic residual is measured in the original system.
"""
from dataclasses import dataclass
import time
import os
import numpy as np
from scipy.sparse import csc_matrix
from scipy.sparse.linalg import gmres, splu, LinearOperator
from .backend import api, versions
from .model import PlaneWave, SolverOptions, points3
from .geometry import SurfaceMesh


@dataclass
class ScatteringSolution:
    mesh: SurfaceMesh
    wave: PlaneWave
    boundary: str
    density: object
    grid: object
    space: object
    parameters: object
    diagnostics: dict

    def far_field(self, directions):
        directions = points3(directions)
        if not np.allclose(np.linalg.norm(directions, axis=0), 1., rtol=0, atol=1e-10):
            raise ValueError("far-field directions must be unit vectors")
        if directions.shape[1] == 0:
            return np.zeros(0, complex)
        helmholtz = api().operators.far_field.helmholtz
        kernel = helmholtz.single_layer if self.boundary == "dirichlet" else helmholtz.double_layer
        op = kernel(self.space, directions, self.wave.k, parameters=self.parameters,
                    device_interface="numba", precision="double")
        return (-1 if self.boundary == "dirichlet" else 1)*np.asarray(op.evaluate(self.density)).ravel()

    def scattered_field(self, points):
        """Exterior evaluations only; callers must supply points off the surface."""
        points = points3(points)
        if points.shape[1] == 0:
            return np.zeros(0, complex)
        helmholtz = api().operators.potential.helmholtz
        kernel = helmholtz.single_layer if self.boundary == "dirichlet" else helmholtz.double_layer
        op = kernel(self.space, points, self.wave.k, parameters=self.parameters,
                    device_interface="numba", precision="double")
        return (-1 if self.boundary == "dirichlet" else 1)*np.asarray(op.evaluate(self.density)).ravel()

    def total_field(self, points):
        return self.wave.values(points) + self.scattered_field(points)

    def component_forces(self):
        """Exact traction integrals for the discrete trace on flat triangles.

        This does not assert exact traction of the continuous PDE solution:
        trace and polygonal-geometry errors are assessed by refinement.
        """
        areas, normals = self.mesh.areas_normals
        samples = np.array([[0., 1., 0.], [0., 0., 1.]])
        scalar = np.zeros(len(areas))
        for e in range(len(areas)):
            values = np.asarray(self.density.evaluate(e, samples)).ravel()
            if self.boundary == "dirichlet":
                scalar[e] = -0.5*areas[e]*abs(values[0])**2
            else:
                tri = self.mesh.vertices[:, self.mesh.elements[:, e]]
                edges = tri[:, 1:] - tri[:, :1]
                grad = edges @ np.linalg.solve(edges.T @ edges, values[1:]-values[0])
                phi2 = areas[e]/12*(np.vdot(values, values).real + abs(values.sum())**2)
                scalar[e] = 0.5*(areas[e]*np.vdot(grad, grad).real-self.wave.k**2*phi2)
        return np.array([normals[:, self.mesh.labels == tag] @ scalar[self.mesh.labels == tag]
                         for tag in self.mesh.components])


def estimated_peak_bytes(mesh, boundary):
    """Conservative dense working-set estimate, not a peak RSS guarantee."""
    n = mesh.elements.shape[1] if boundary == "dirichlet" else mesh.vertices.shape[1]
    return int(8 * 16 * n*n + 256*1024**2)


def solve(mesh: SurfaceMesh, wave: PlaneWave, boundary="dirichlet", options=None):
    if boundary not in ("dirichlet", "neumann"):
        raise ValueError("boundary must be dirichlet or neumann")
    options = SolverOptions() if options is None else options
    estimate = estimated_peak_bytes(mesh, boundary)
    if estimate > options.memory_gib * 1024**3:
        raise MemoryError(f"estimated dense peak {estimate/1024**3:.2f} GiB exceeds budget")
    start = time.monotonic()
    b = api()
    p = b.DefaultParameters()
    p.quadrature.regular = options.regular_order
    p.quadrature.singular = options.singular_order
    grid = b.Grid(mesh.vertices.copy(), mesh.elements.copy(), domain_indices=mesh.labels.copy())
    space = b.function_space(grid, "DP", 0) if boundary == "dirichlet" else b.function_space(grid, "P", 1)
    h = b.operators.boundary.helmholtz
    ident = b.operators.boundary.sparse.identity(space, space, space)
    kw = dict(parameters=p, assembler="dense", device_interface="numba", precision="double")
    k = wave.k
    if boundary == "dirichlet":
        operator = 0.5*ident + h.adjoint_double_layer(space, space, space, k, **kw) - 1j*k*h.single_layer(space, space, space, k, **kw)
    else:
        operator = 0.5*ident - h.double_layer(space, space, space, k, **kw) + (1j/k)*h.hypersingular(space, space, space, k, **kw)

    d, amplitude = np.array(wave.direction), wave.amplitude
    @b.complex_callable(jit=False)
    def rhs_fun(x, normal, domain_index, result):
        inc = amplitude*np.exp(1j*k*np.dot(d, x))
        qinc = 1j*k*np.dot(d, normal)*inc
        result[0] = qinc - 1j*k*inc if boundary == "dirichlet" else inc + 1j/k*qinc

    rhs = b.GridFunction(space, fun=rhs_fun, parameters=p).projections(space)
    matrix = operator.weak_form().to_dense()
    mass = csc_matrix(ident.weak_form().to_sparse(), dtype=complex)
    preconditioner = splu(mass)
    pre = LinearOperator(matrix.shape, matvec=lambda x: preconditioner.solve(x), dtype=complex)
    assembly_time = time.monotonic()-start
    history = []
    coeffs, info = gmres(matrix, rhs, M=pre, rtol=options.rtol, atol=0., restart=min(100, matrix.shape[0]),
                         maxiter=options.maxiter, callback=history.append, callback_type="pr_norm")
    residual = np.linalg.norm(matrix @ coeffs-rhs) / max(np.linalg.norm(rhs), np.finfo(float).tiny)
    if info != 0 or residual > 10*options.rtol:
        raise RuntimeError(f"GMRES failed: info={info}, relative weak residual={residual:.3g}")
    density = b.GridFunction(space, coefficients=coeffs, parameters=p)
    diag = dict(assembly_seconds=assembly_time, solve_seconds=time.monotonic()-start-assembly_time,
                seconds=time.monotonic()-start, relative_residual=float(residual), iterations=len(history),
                elements=mesh.elements.shape[1], dofs=len(coeffs), mesh_sha256=mesh.fingerprint,
                estimated_peak_gib=estimate/1024**3, versions=versions(),
                regular_order=options.regular_order, singular_order=options.singular_order,
                threads={x:os.environ.get(x) for x in ("NUMBA_NUM_THREADS", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")})
    return ScatteringSolution(mesh, wave, boundary, density, grid, space, p, diag)

