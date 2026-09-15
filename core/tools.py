"""Tool Registry + Permission Engine + Sandbox (sections 6, 7, 19, 26, 27).

Agents never touch the OS directly. Every capability is a registered tool
with a risk level; the gateway enforces workspace confinement and refuses
unauthorized actions. File tools are the only SAFE_WRITE surface in the MVP.
"""
from __future__ import annotations

import hashlib
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    SAFE_WRITE = "SAFE_WRITE"
    RESTRICTED = "RESTRICTED"
    CRITICAL = "CRITICAL"


class ToolSpec(BaseModel):
    name: str
    description: str
    version: str = "1.0.0"
    risk: RiskLevel
    timeout_s: int = 30
    input_schema: dict[str, str] = Field(default_factory=dict)


class ToolDeniedError(PermissionError):
    pass


class ToolRegistry:
    def __init__(self, workspace_root: Path, allow_restricted: bool = False) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.allow_restricted = allow_restricted
        self._tools: dict[str, tuple[ToolSpec, Callable[..., Any]]] = {}

    # ------------------------------------------------------------------ #
    def register(self, spec: ToolSpec, func: Callable[..., Any]) -> None:
        self._tools[spec.name] = (spec, func)

    def list_tools(self) -> list[ToolSpec]:
        return [spec for spec, _ in self._tools.values()]

    def describe(self, name: str) -> ToolSpec | None:
        entry = self._tools.get(name)
        return entry[0] if entry else None

    # ------------------------------------------------------------------ #
    def execute(self, tool_name: str, agent: str, **kwargs: Any) -> Any:
        """Validate permission, then run the tool. This is the only path."""
        entry = self._tools.get(tool_name)
        if entry is None:
            raise ToolDeniedError(f"unknown tool '{tool_name}' - not in whitelist")
        spec, func = entry

        if spec.risk == RiskLevel.CRITICAL and not self.allow_restricted:
            raise ToolDeniedError(f"tool '{tool_name}' is CRITICAL and disabled in this configuration")
        if spec.risk == RiskLevel.RESTRICTED and not self.allow_restricted:
            raise ToolDeniedError(f"tool '{tool_name}' is RESTRICTED and requires explicit approval")

        # Constrain any path-like argument to the workspace.
        for key, value in kwargs.items():
            if isinstance(value, (str, Path)) and ("path" in key or "file" in key or "dir" in key):
                kwargs[key] = self._confine(Path(str(value)))

        return func(**kwargs)

    def _confine(self, path: Path) -> Path:
        p = (self.workspace_root / path).resolve() if not path.is_absolute() else path.resolve()
        try:
            p.relative_to(self.workspace_root)
        except ValueError:
            raise ToolDeniedError(
                f"path '{path}' escapes the project workspace - denied"
            ) from None
        return p


# ---------------------------------------------------------------------- #
# Concrete file tools (SAFE_WRITE / READ_ONLY), workspace-confined.
# ---------------------------------------------------------------------- #
def make_file_tools(registry: ToolRegistry) -> None:
    root = registry.workspace_root

    def write_text(path: str, content: str) -> dict[str, Any]:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        # Workspace-RELATIVE path in results: manifests and artifact URLs must
        # never leak the local filesystem (absolute paths would 404 in /artifacts).
        return {"path": p.relative_to(root).as_posix(), "bytes": len(content.encode("utf-8")),
                "checksum": _sha256(content)}

    def read_text(path: str) -> dict[str, Any]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(str(p))
        return {"path": str(p), "content": p.read_text(encoding="utf-8")}

    def list_dir(path: str = ".") -> dict[str, Any]:
        p = Path(path)
        entries = sorted(str(e.relative_to(p)) for e in p.rglob("*") if e.is_file())
        return {"path": str(p), "files": entries[:500]}

    def write_file_bytes(path: str, content: bytes) -> dict[str, Any]:
        """Binary artifact writer (STL, ...) - still workspace-confined."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return {
            "path": p.relative_to(root).as_posix(), "bytes": len(content),
            "checksum": hashlib.sha256(content).hexdigest(),
        }

    def read_file_bytes(path: str) -> dict[str, Any]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(str(p))
        data = p.read_bytes()
        return {"path": str(p), "content": data,
                "checksum": hashlib.sha256(data).hexdigest()}

    def clear_dir(path: str) -> dict[str, Any]:
        """Delete FILES (not dirs) under a workspace subdirectory, so a
        regenerated design never leaves stale outputs from a previous run.
        Workspace-confined by the registry like every other tool."""
        p = Path(path)
        if not p.exists():
            return {"path": str(p), "removed": 0}
        removed = 0
        for f in p.rglob("*"):
            if f.is_file():
                f.unlink()
                removed += 1
        return {"path": str(p), "removed": removed}

    registry.register(
        ToolSpec(
            name="write_text",
            description="Write a UTF-8 text file inside the project workspace",
            risk=RiskLevel.SAFE_WRITE,
            input_schema={"path": "str", "content": "str"},
        ),
        write_text,
    )
    registry.register(
        ToolSpec(
            name="read_text",
            description="Read a UTF-8 text file from the project workspace",
            risk=RiskLevel.READ_ONLY,
            input_schema={"path": "str"},
        ),
        read_text,
    )
    registry.register(
        ToolSpec(
            name="list_dir",
            description="List files under a workspace directory",
            risk=RiskLevel.READ_ONLY,
            input_schema={"path": "str"},
        ),
        list_dir,
    )
    registry.register(
        ToolSpec(
            name="clear_dir",
            description="Delete stale files under a workspace subdirectory (design regeneration)",
            risk=RiskLevel.SAFE_WRITE,
            input_schema={"path": "str"},
        ),
        clear_dir,
    )
    registry.register(
        ToolSpec(
            name="write_file_bytes",
            description="Write a binary artifact (STL...) inside the project workspace",
            risk=RiskLevel.SAFE_WRITE,
            input_schema={"path": "str", "content": "bytes"},
        ),
        write_file_bytes,
    )
    registry.register(
        ToolSpec(
            name="read_file_bytes",
            description="Read a binary artifact from the project workspace",
            risk=RiskLevel.READ_ONLY,
            input_schema={"path": "str"},
        ),
        read_file_bytes,
    )


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
