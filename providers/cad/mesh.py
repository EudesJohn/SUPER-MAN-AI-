"""Minimal parametric mesh CAD kernel (numpy only) - real 3D geometry.

Primitives generate CLOSED triangle meshes; transforms are 4x4 matrices;
export is binary STL. Mesh volume uses the signed tetrahedron sum, so tests
can verify every primitive against its analytic volume. No external CAD
dependency is required; the CADProvider abstraction can route to
CadQuery/OpenCASCADE later for STEP export (not installed on this machine).
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass

import numpy as np

STL_HEADER = b"AI ENGINEER binary STL"


@dataclass
class Mesh:
    vertices: np.ndarray  # (N, 3) float64
    triangles: np.ndarray  # (M, 3) int

    @property
    def n_triangles(self) -> int:
        return int(len(self.triangles))

    def transformed(self, mat: np.ndarray) -> "Mesh":
        v = self.vertices @ mat[:3, :3].T + mat[:3, 3]
        return Mesh(v.copy(), self.triangles.copy())

    def merged_with(self, other: "Mesh") -> "Mesh":
        v = np.concatenate([self.vertices, other.vertices])
        t = np.concatenate([self.triangles, other.triangles + len(self.vertices)])
        return Mesh(v, t)

    def volume(self) -> float:
        """Signed tetrahedron sum - exact for closed meshes."""
        v0 = self.vertices[self.triangles[:, 0]]
        v1 = self.vertices[self.triangles[:, 1]]
        v2 = self.vertices[self.triangles[:, 2]]
        return float(np.sum(np.einsum("ij,ij->i", v0, np.cross(v1, v2))) / 6.0)

    def centroid(self) -> np.ndarray:
        return self.vertices.mean(axis=0)


# --------------------------------------------------------------------------- #
# Transforms (4x4 homogeneous matrices)
# --------------------------------------------------------------------------- #
def translation(x: float, y: float, z: float) -> np.ndarray:
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    return m


def rotation_x(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]], dtype=float)


def rotation_y(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]], dtype=float)


def rotation_z(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=float)


def place(mesh: Mesh, x: float = 0.0, y: float = 0.0, z: float = 0.0,
          rx: float = 0.0, ry: float = 0.0, rz: float = 0.0) -> Mesh:
    """Rotate around the mesh's own origin (rx, ry, rz in degrees) then translate."""
    m = translation(x, y, z) @ rotation_z(rz) @ rotation_y(ry) @ rotation_x(rx)
    return mesh.transformed(m)


def merge_all(meshes: list[Mesh]) -> Mesh:
    out = meshes[0]
    for m in meshes[1:]:
        out = out.merged_with(m)
    return out


def scale(mesh: Mesh, sx: float, sy: float, sz: float) -> Mesh:
    """Anisotropic scaling about the origin. Scaling a CLOSED mesh about its
    center keeps it closed and watertight (volumes scale by sx*sy*sz), which
    is how teardrop/ellipse body sections are derived from a sphere."""
    if sx <= 0 or sy <= 0 or sz <= 0:
        raise ValueError("scale factors must be strictly positive")
    v = mesh.vertices * np.array([sx, sy, sz])
    return Mesh(v.copy(), mesh.triangles.copy())


# --------------------------------------------------------------------------- #
# Primitives (all centered on their own origin, axis Z by default)
# --------------------------------------------------------------------------- #
def box(l: float, w: float, h: float) -> Mesh:
    hw, hd, hh = l / 2.0, w / 2.0, h / 2.0
    v = np.array([
        [-hw, -hd, -hh], [hw, -hd, -hh], [hw, hd, -hh], [-hw, hd, -hh],   # bottom 0-3
        [-hw, -hd, hh], [hw, -hd, hh], [hw, hd, hh], [-hw, hd, hh],       # top 4-7
    ])
    t = np.array([
        [0, 2, 1], [0, 3, 2],          # bottom (out -z)
        [4, 5, 6], [4, 6, 7],          # top (out +z)
        [2, 3, 7], [2, 7, 6],          # +y
        [1, 4, 0], [1, 5, 4],          # -y
        [1, 2, 6], [1, 6, 5],          # +x
        [0, 7, 3], [0, 4, 7],          # -x
    ])
    return Mesh(v, t)


def tapered_box(l: float, w: float, h: float, top_sx: float = 1.0, top_sy: float = 1.0) -> Mesh:
    """Box whose top face is scaled toward its center (sloped hood-like shape)."""
    m = box(l, w, h)
    m.vertices[4:, :2] *= (top_sx, top_sy)
    return m


def _axis_rotation(axis: str) -> np.ndarray:
    if axis == "z":
        return np.eye(4)
    if axis == "x":
        return rotation_y(90.0)     # +z -> +x
    if axis == "y":
        return rotation_x(-90.0)    # +z -> +y
    raise ValueError(f"axis must be x, y or z, got {axis!r}")


def cylinder(r1: float, r2: float, h: float, segments: int = 32, axis: str = "z") -> Mesh:
    """Truncated cone (r1=r2 gives a plain cylinder), centered at origin."""
    if segments < 3:
        raise ValueError("segments must be >= 3")
    ang = np.linspace(0.0, 2.0 * math.pi, segments, endpoint=False)
    ca, sa = np.cos(ang), np.sin(ang)
    bottom = np.column_stack([r1 * ca, r1 * sa, np.full(segments, -h / 2.0)])
    top = np.column_stack([r2 * ca, r2 * sa, np.full(segments, h / 2.0)])
    v = [list(p) for p in bottom] + [list(p) for p in top]
    if r1 > 0:
        v.append([0.0, 0.0, -h / 2.0])           # bottom center: index 2n
    if r2 > 0:
        v.append([0.0, 0.0, h / 2.0])            # top center: index 2n+1 (or 2n)
    t: list[list[int]] = []
    cb = 2 * segments
    ct = 2 * segments + 1 if r1 > 0 else 2 * segments
    for i in range(segments):
        j = (i + 1) % segments
        t.append([i, j, segments + j])           # side outward
        t.append([i, segments + j, segments + i])
        if r2 > 0:
            t.append([ct, segments + i, segments + j])   # top cap (out +z)
        if r1 > 0:
            t.append([cb, j, i])                          # bottom cap (out -z)
    m = Mesh(np.array(v), np.array(t))
    return m.transformed(_axis_rotation(axis))


def torus(R: float, r: float, n_u: int = 32, n_v: int = 16, axis: str = "z") -> Mesh:
    """Ring of tube radius r centered on circle of radius R (wheel tire)."""
    us = np.linspace(0.0, 2.0 * math.pi, n_u, endpoint=False)
    vs = np.linspace(0.0, 2.0 * math.pi, n_v, endpoint=False)
    v: list[list[float]] = []
    for u in us:
        for vv in vs:
            v.append([(R + r * math.cos(vv)) * math.cos(u),
                      (R + r * math.cos(vv)) * math.sin(u),
                      r * math.sin(vv)])
    t: list[list[int]] = []
    for i in range(n_u):
        i2 = (i + 1) % n_u
        for j in range(n_v):
            j2 = (j + 1) % n_v
            a = i * n_v + j
            b = i2 * n_v + j
            c = i2 * n_v + j2
            d = i * n_v + j2
            t.append([a, b, c])
            t.append([a, c, d])
    m = Mesh(np.array(v), np.array(t))
    return m.transformed(_axis_rotation(axis))


def sphere(r: float, n_u: int = 16, n_v: int = 10) -> Mesh:
    """UV sphere with pole fans (no degenerate triangles)."""
    phis = [-math.pi / 2 + math.pi * j / n_v for j in range(1, n_v)]  # interior rings
    thetas = [2.0 * math.pi * i / n_u for i in range(n_u)]
    v: list[list[float]] = [[0.0, 0.0, -r]]  # 0: south pole
    for phi in phis:
        for th in thetas:
            v.append([r * math.cos(phi) * math.cos(th),
                      r * math.cos(phi) * math.sin(th),
                      r * math.sin(phi)])
    v.append([0.0, 0.0, r])  # north pole: index 1 + (n_v-1)*n_u
    north = 1 + (n_v - 1) * n_u
    t: list[list[int]] = []
    for i in range(n_u):
        i2 = (i + 1) % n_u
        r0 = 1 + i      # first ring row indices
        r0b = 1 + i2
        t.append([0, r0b, r0])                       # south fan
        top_row = 1 + (n_v - 2) * n_u
        t.append([north, top_row + i, top_row + i2])  # north fan
        for j in range(n_v - 2):
            a = 1 + j * n_u + i
            b = 1 + j * n_u + i2
            c = 1 + (j + 1) * n_u + i2
            d = 1 + (j + 1) * n_u + i
            t.append([a, b, c])
            t.append([a, c, d])
    return Mesh(np.array(v), np.array(t))


def tube_along(points, radius: float, seg: int = 8) -> Mesh:
    """Round wire along a polyline: per-segment tubes + joint spheres."""
    pts = np.asarray(points, dtype=float)
    if len(pts) < 2:
        raise ValueError("tube needs at least 2 points")
    parts: list[Mesh] = []
    for a, b in zip(pts[:-1], pts[1:]):
        d = b - a
        length = float(np.linalg.norm(d))
        if length < 1e-9:
            continue
        u = d / length
        ref = np.array([0.0, 0.0, 1.0]) if abs(u[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        e1 = np.cross(u, ref)
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(u, e1)
        ang = np.linspace(0.0, 2.0 * math.pi, seg, endpoint=False)
        ring_a = a + radius * (np.outer(np.cos(ang), e1) + np.outer(np.sin(ang), e2))
        ring_b = b + radius * (np.outer(np.cos(ang), e1) + np.outer(np.sin(ang), e2))
        verts = np.concatenate([ring_a, ring_b])
        tris: list[list[int]] = []
        for i in range(seg):
            j = (i + 1) % seg
            tris.append([i, j, seg + j])
            tris.append([i, seg + j, seg + i])
        parts.append(Mesh(verts, np.array(tris)))
    for p in pts:
        parts.append(place(sphere(radius, 12, 8), x=p[0], y=p[1], z=p[2]))
    return merge_all(parts)


# --------------------------------------------------------------------------- #
# STL export / import (binary)
# --------------------------------------------------------------------------- #
_STL_DTYPE = np.dtype([
    ("normal", "<3f4"), ("v0", "<3f4"), ("v1", "<3f4"), ("v2", "<3f4"), ("attr", "<u2"),
])


def stl_bytes(mesh: Mesh) -> bytes:
    """Binary STL payload in memory (sandbox-safe writers then persist it)."""
    tris = mesh.vertices[mesh.triangles]                       # (M, 3, 3)
    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    norms = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.where(norms > 1e-12, normals / np.maximum(norms, 1e-12), np.array([0.0, 0.0, 1.0]))
    data = np.zeros(len(tris), dtype=_STL_DTYPE)
    data["normal"] = normals.astype("<f4")
    data["v0"] = tris[:, 0].astype("<f4")
    data["v1"] = tris[:, 1].astype("<f4")
    data["v2"] = tris[:, 2].astype("<f4")
    import io

    buf = io.BytesIO()
    buf.write(STL_HEADER.ljust(80, b"\0")[:80])
    buf.write(struct.pack("<I", len(tris)))
    buf.write(data.tobytes())
    return buf.getvalue()


def export_binary_stl(mesh: Mesh, path) -> dict:
    from pathlib import Path

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(stl_bytes(mesh))
    return {"path": str(path), "triangles": mesh.n_triangles}


def read_binary_stl(path) -> Mesh:
    """Test/inspection helper: parse a binary STL written by export_binary_stl."""
    raw = open(path, "rb").read()
    count = int.from_bytes(raw[80:84], "little")
    if len(raw) != 84 + 50 * count:
        raise ValueError(f"STL size mismatch: expected {84 + 50 * count}, got {len(raw)}")
    data = np.frombuffer(raw[84:], dtype=_STL_DTYPE, count=count)
    verts = np.concatenate([data["v0"], data["v1"], data["v2"]]).reshape(-1, 3).astype(float)
    k = np.arange(count)
    tris = np.column_stack([k, count + k, 2 * count + k]).astype(int)
    return Mesh(verts, tris)
