"""Solver: mass properties of closed meshes (discrete, exact by tetrahedron sum)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from providers.cad.mesh import Mesh


@dataclass
class MassProperties:
    volume_m3: float
    mass_kg: float
    density_kg_m3: float
    center_of_mass: tuple[float, float, float]
    surface_area_m2: float = 0.0
    shell: bool = False


def surface_area(mesh: Mesh) -> float:
    """Total triangle area in m2 (vertices are in meters)."""
    v0 = mesh.vertices[mesh.triangles[:, 0]]
    v1 = mesh.vertices[mesh.triangles[:, 1]]
    v2 = mesh.vertices[mesh.triangles[:, 2]]
    return float(np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1).sum())


def shell_mass(mesh: Mesh, density_kg_m3: float, thickness_m: float) -> MassProperties:
    """Mass of a thin-walled part: surface area x thickness x density.
    Car body panels, glazing and skins are SHELLS, not solids - modeling the
    enclosed volume as material gives absurd masses (a solid 'body' would weigh
    6 t). Use for panels; use mass_properties for true solid parts.
    CoM approximated by the area-weighted facet centroid."""
    v0 = mesh.vertices[mesh.triangles[:, 0]]
    v1 = mesh.vertices[mesh.triangles[:, 1]]
    v2 = mesh.vertices[mesh.triangles[:, 2]]
    areas = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
    area = float(areas.sum())
    com = (0.25 * (v0 + v1 + v2) * areas[:, None]).sum(axis=0) / max(area, 1e-12)
    return MassProperties(
        volume_m3=area * thickness_m,
        mass_kg=area * thickness_m * density_kg_m3,
        density_kg_m3=density_kg_m3,
        center_of_mass=(float(com[0]), float(com[1]), float(com[2])),
        surface_area_m2=area,
        shell=True,
    )


def mass_properties(mesh: Mesh, density_kg_m3: float) -> MassProperties:
    """Volume via signed tetrahedron sum; CoM as volume-weighted mean of
    tetrahedron centers (exact integration for the same discretization)."""
    v0 = mesh.vertices[mesh.triangles[:, 0]]
    v1 = mesh.vertices[mesh.triangles[:, 1]]
    v2 = mesh.vertices[mesh.triangles[:, 2]]
    signed6 = np.einsum("ij,ij->i", v0, np.cross(v1, v2))
    volume = float(signed6.sum() / 6.0)
    tet_centers = (v0 + v1 + v2) / 4.0  # tet center = (p0+p1+p2+p3)/4 with p3=origin
    if abs(volume) < 1e-12:
        com = mesh.centroid()
    else:
        com = (tet_centers * signed6[:, None]).sum(axis=0) / (6.0 * volume)
    return MassProperties(
        volume_m3=volume,
        mass_kg=abs(volume) * density_kg_m3,
        density_kg_m3=density_kg_m3,
        center_of_mass=(float(com[0]), float(com[1]), float(com[2])),
    )
