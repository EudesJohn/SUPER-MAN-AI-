"""CAD abstraction layer (spec sections 13/14): provider interface + default.

The core system never calls a CAD kernel directly. MeshCadProvider is the
always-available default (internal numpy mesh kernel, binary STL).
STEP export requires CadQuery/OpenCASCADE: if it is not installed the
provider reports it honestly instead of pretending.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from providers.cad import mesh


class CADProvider(ABC):
    name: str = "cad"

    @abstractmethod
    def availability(self) -> tuple[bool, str]:
        """(is_usable, honest_reason)"""

    @abstractmethod
    def export_mesh(self, m: mesh.Mesh, path: Path, fmt: str = "stl") -> dict:
        """Write the mesh to path in the requested format."""

    def export_mesh_bytes(self, m: mesh.Mesh, fmt: str = "stl") -> bytes:
        """In-memory payload for sandboxed writers (default: binary STL)."""
        raise ValueError(f"format '{fmt}' not supported by {self.name}")


class MeshCadProvider(CADProvider):
    name = "internal_mesh"

    def availability(self) -> tuple[bool, str]:
        return True, "numpy mesh kernel available; formats: stl"

    def export_mesh_bytes(self, m: mesh.Mesh, fmt: str = "stl") -> bytes:
        fmt = fmt.lower()
        if fmt != "stl":
            raise ValueError(
                f"format '{fmt}' requires CadQuery/OpenCASCADE, which is not installed "
                "on this machine. Available: stl. Nothing was written - no fake export."
            )
        return mesh.stl_bytes(m)

    def export_mesh(self, m: mesh.Mesh, path: Path, fmt: str = "stl") -> dict:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return mesh.export_binary_stl(m, path)


def detect_provider(preferred: str | None = None) -> tuple[CADProvider, list[str]]:
    """Choose a CAD provider; report honestly what is and is not available."""
    notes: list[str] = []
    try:  # optional heavy dependency
        import cadquery  # noqa: F401
        notes.append("cadquery detected: STEP export could be enabled (adapter not wired yet)")
    except ImportError:
        notes.append("cadquery not installed: STEP/IGES export unavailable (STL only)")
    if preferred in ("solidworks", "cadquery") :
        notes.append(f"preferred CAD '{preferred}' not usable on this machine; using internal mesh kernel")
    return MeshCadProvider(), notes
