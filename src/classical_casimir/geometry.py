"""Closed triangular meshes, immutable translations, and component labels.

Sphere meshes are inscribed icosahedral refinements; they need neither Gmsh
nor an external mesher. Imported meshes represent their polygonal surfaces.
"""
from dataclasses import dataclass
from pathlib import Path
from collections import defaultdict
import hashlib
import numpy as np
from scipy.spatial import ConvexHull


@dataclass(frozen=True)
class SurfaceMesh:
    vertices: np.ndarray
    elements: np.ndarray
    labels: np.ndarray

    def __post_init__(self):
        v = np.array(self.vertices, dtype=float, order="F", copy=True)
        raw = np.asarray(self.elements)
        if not np.issubdtype(raw.dtype, np.integer):
            raise ValueError("element indices must be integers")
        e = np.array(raw, dtype=np.int32, order="F", copy=True)
        if not np.issubdtype(np.asarray(self.labels).dtype, np.integer):
            raise ValueError("component labels must be integers")
        labels = np.array(self.labels, dtype=np.int32, copy=True)
        if v.ndim != 2 or v.shape[0] != 3 or not np.isfinite(v).all():
            raise ValueError("vertices must have shape (3,N) and be finite")
        if e.ndim != 2 or e.shape[0] != 3 or e.shape[1] == 0 or e.min() < 0 or e.max() >= v.shape[1]:
            raise ValueError("elements must have shape (3,M) and valid vertex indices")
        if labels.shape != (e.shape[1],) or np.any(labels < 1):
            raise ValueError("one positive component label is required per triangle")
        if len(np.unique(e)) != v.shape[1]:
            raise ValueError("unused mesh vertices")
        edges = defaultdict(list)
        for j, tri in enumerate(e.T):
            for a, b in zip(tri, np.roll(tri, -1)):
                edges[tuple(sorted((int(a), int(b))))].append((int(a), int(b), int(labels[j])))
        if any(len(x) != 2 or x[0][:2] != x[1][:2][::-1] or x[0][2] != x[1][2] for x in edges.values()):
            raise ValueError("mesh must be closed, consistently oriented, with disjoint components")
        for label in np.unique(labels):
            idx = labels == label
            tri = e[:, idx]
            # Signed volume relative to a nearby origin avoids large-offset cancellation.
            origin = v[:, np.unique(tri)].mean(axis=1)[:, None]
            a, b, c = (v[:, tri[i]] - origin for i in range(3))
            volume = np.sum(a * np.cross(b, c, axisa=0, axisb=0, axisc=0)) / 6
            if volume <= 0:
                raise ValueError("component normals must point outward")
            cross = np.cross(b-a, c-a, axisa=0, axisb=0, axisc=0)
            if np.any(np.linalg.norm(cross, axis=0) <= 1e-14):
                raise ValueError("degenerate triangle")
            # A label means one connected component, not an arbitrary physical group.
            local_edges = defaultdict(list)
            for j in np.flatnonzero(idx):
                for p, q in zip(e[:, j], np.roll(e[:, j], -1)):
                    local_edges[tuple(sorted((int(p), int(q))))].append(j)
            adjacent = defaultdict(set)
            for p, q in local_edges.values():
                adjacent[p].add(q); adjacent[q].add(p)
            seen, stack = set(), [int(np.flatnonzero(idx)[0])]
            while stack:
                j = stack.pop()
                if j not in seen:
                    seen.add(j); stack.extend(adjacent[j] - seen)
            if len(seen) != idx.sum():
                raise ValueError("each label must identify one connected component")
        for a, label in enumerate(np.unique(labels)):
            nodes = set(np.unique(e[:, labels == label]))
            for other in np.unique(labels)[a+1:]:
                if nodes.intersection(np.unique(e[:, labels == other])):
                    raise ValueError("components may not share vertices")
        for x in (v, e, labels):
            x.setflags(write=False)
        object.__setattr__(self, "vertices", v)
        object.__setattr__(self, "elements", e)
        object.__setattr__(self, "labels", labels)

    @property
    def components(self):
        return np.unique(self.labels)

    @property
    def areas_normals(self):
        a, b, c = (self.vertices[:, self.elements[i]] for i in range(3))
        n = np.cross(b-a, c-a, axisa=0, axisb=0, axisc=0)
        norm = np.linalg.norm(n, axis=0)
        return norm / 2, n / norm

    @property
    def fingerprint(self):
        digest = hashlib.sha256()
        for x in (self.vertices, self.elements, self.labels):
            digest.update(x.tobytes())
        return digest.hexdigest()

    def translated(self, delta, component=None):
        delta = np.asarray(delta, dtype=float)
        if delta.shape != (3,) or not np.isfinite(delta).all():
            raise ValueError("translation must be a finite 3-vector")
        if component is not None and component not in self.components:
            raise ValueError("unknown component")
        nodes = np.unique(self.elements if component is None else self.elements[:, self.labels == component])
        v = self.vertices.copy()
        v[:, nodes] += delta[:, None]
        return SurfaceMesh(v, self.elements, self.labels)

    def component(self, label):
        if label not in self.components:
            raise ValueError("unknown component")
        tri = self.elements[:, self.labels == label]
        nodes, inverse = np.unique(tri, return_inverse=True)
        return SurfaceMesh(self.vertices[:, nodes], inverse.reshape(tri.shape), np.ones(tri.shape[1], dtype=int))

    def save(self, path):
        np.savez_compressed(path, vertices=self.vertices, elements=self.elements, labels=self.labels)

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.suffix == ".npz":
            with np.load(path, allow_pickle=False) as data:
                return cls(data["vertices"], data["elements"], data["labels"])
        import meshio
        data = meshio.read(path)
        tri = data.cells_dict.get("triangle")
        if tri is None:
            raise ValueError("mesh must contain linear triangles")
        # Derive connected components instead of trusting Gmsh physical group labels.
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        nodes, inv = np.unique(tri, return_inverse=True)
        tri = inv.reshape(tri.shape)
        edges = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
        graph = coo_matrix((np.ones(len(edges)), (edges[:, 0], edges[:, 1])), shape=(len(nodes), len(nodes)))
        _, labels = connected_components(graph, directed=False)
        return cls(data.points[nodes].T, tri.T, labels[tri[:, 0]] + 1)


def sphere(radius=1., center=(0., 0., 0.), refinement=1):
    if not np.isfinite(radius) or radius <= 0 or not isinstance(refinement, int) or refinement not in range(0, 7):
        raise ValueError("positive radius and integer refinement 0..6 required")
    center = np.asarray(center, dtype=float)
    if center.shape != (3,) or not np.isfinite(center).all():
        raise ValueError("invalid center")
    golden = (1 + np.sqrt(5.)) / 2
    v = np.array([(0, s, t*golden) for s in (-1, 1) for t in (-1, 1)] +
                 [(s, t*golden, 0) for s in (-1, 1) for t in (-1, 1)] +
                 [(t*golden, 0, s) for s in (-1, 1) for t in (-1, 1)], float)
    v /= np.linalg.norm(v, axis=1)[:, None]
    faces = ConvexHull(v).simplices
    for _ in range(refinement):
        vertices, cache, new = list(v), {}, []
        def midpoint(i, j):
            key = tuple(sorted((int(i), int(j))))
            if key not in cache:
                p = v[i] + v[j]; p /= np.linalg.norm(p)
                cache[key] = len(vertices); vertices.append(p)
            return cache[key]
        for a, b, c in faces:
            ab, bc, ca = midpoint(a, b), midpoint(b, c), midpoint(c, a)
            new.extend([(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)])
        v, faces = np.array(vertices), np.array(new)
    for face in faces:
        a, b, c = v[face]
        if np.dot(np.cross(b-a, c-a), a) < 0:
            face[1], face[2] = face[2], face[1]
    return SurfaceMesh((radius*v + center).T, faces.T, np.ones(len(faces), dtype=int))


def union(meshes):
    vertices, elements, labels, offset, component = [], [], [], 0, 0
    for mesh in meshes:
        vertices.append(mesh.vertices); elements.append(mesh.elements + offset)
        remap = {int(tag): i + component + 1 for i, tag in enumerate(mesh.components)}
        labels.extend(remap[int(tag)] for tag in mesh.labels)
        offset += mesh.vertices.shape[1]; component += len(remap)
    return SurfaceMesh(np.concatenate(vertices, axis=1), np.concatenate(elements, axis=1), np.array(labels))


def two_spheres(gap=1., radius=1., refinement=1):
    if not np.isfinite(gap) or gap <= 0:
        raise ValueError("surface gap must be finite and positive")
    x = radius + gap/2
    return union([sphere(radius, (-x, 0, 0), refinement), sphere(radius, (x, 0, 0), refinement)])

