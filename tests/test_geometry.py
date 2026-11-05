import numpy as np
import pytest
from classical_casimir.geometry import sphere, two_spheres, SurfaceMesh


def test_sphere_refinement_geometry():
    errors = []
    for level in (0, 1, 2):
        mesh = sphere(refinement=level)
        areas, normals = mesh.areas_normals
        assert mesh.elements.shape[1] == 20*4**level
        np.testing.assert_allclose(np.linalg.norm(mesh.vertices, axis=0), 1.)
        np.testing.assert_allclose(normals@areas, 0., atol=1e-14)
        errors.append(abs(areas.sum()-4*np.pi))
    assert errors[2] < errors[1] < errors[0]


@pytest.mark.parametrize("level", range(7))
def test_bootstrap_mesh_size_matches_actual_triangle_edges(level):
    from classical_casimir.cluster_templates.bundle import sphere_mesh_parameters
    mesh = sphere(radius=2.5, refinement=level)
    triangles = mesh.vertices[:, mesh.elements]
    attained = max(np.linalg.norm(triangles[:, i, :] - triangles[:, j, :], axis=0).max()
                   for i, j in ((0, 1), (1, 2), (2, 0))) / 2.5
    parameters = sphere_mesh_parameters(refinement=level)
    assert parameters["mesh_size"] == pytest.approx(attained, rel=2e-14)
    assert parameters["triangles_per_sphere"] == mesh.elements.shape[1]


def test_components_translation_and_roundtrip(tmp_path):
    mesh = two_spheres(gap=.3, refinement=1)
    before = mesh.fingerprint
    delta = np.array([.03, -.02, .01])
    moved = mesh.translated(delta, component=2)
    np.testing.assert_array_equal(moved.component(1).vertices, mesh.component(1).vertices)
    np.testing.assert_allclose(moved.component(2).vertices, mesh.component(2).vertices+delta[:, None])
    assert before == mesh.fingerprint
    path = tmp_path/"mesh.npz"; moved.save(path)
    assert SurfaceMesh.load(path).fingerprint == moved.fingerprint
    with pytest.raises(ValueError): mesh.vertices[0, 0] = 0


def test_import_meshio_components(tmp_path):
    import meshio
    mesh = two_spheres(refinement=0)
    path = tmp_path/"two.vtk"
    meshio.write_points_cells(path, mesh.vertices.T, [("triangle", mesh.elements.T)])
    imported = SurfaceMesh.load(path)
    assert len(imported.components) == 2
    np.testing.assert_allclose(imported.areas_normals[0].sum(), mesh.areas_normals[0].sum())


def test_invalid_meshes_rejected():
    mesh = sphere(refinement=0)
    with pytest.raises(ValueError, match="closed"):
        SurfaceMesh(mesh.vertices, mesh.elements[:, :-1], mesh.labels[:-1])
    with pytest.raises(ValueError, match="outward"):
        SurfaceMesh(mesh.vertices, mesh.elements[::-1], mesh.labels)
    with pytest.raises(ValueError): two_spheres(gap=0)
    with pytest.raises(ValueError): sphere(refinement=-1)

