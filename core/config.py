"""Configuration loading (section 33) + .env loading (secrets never in code)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel


def load_env(path: str | Path = ".env") -> dict[str, str]:
    """Minimal .env loader: KEY=VALUE lines, comments (#) and blank lines
    ignored; values may be quoted. Variables already set in the environment
    take precedence. Returns the parsed entries (and exports them)."""
    p = Path(path)
    loaded: dict[str, str] = {}
    if not p.exists():
        return loaded
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key:
            loaded[key] = value
            os.environ.setdefault(key, value)
    return loaded


class LLMConfig(BaseModel):
    provider: str = "mock"
    model: Optional[str] = None
    api_key_env: Optional[str] = None


class SearchConfig(BaseModel):
    provider: str = "none"
    enabled: bool = False


class CADConfig(BaseModel):
    provider: Optional[str] = None
    solidworks_path: Optional[str] = None


class EDAConfig(BaseModel):
    provider: Optional[str] = None
    kicad_path: Optional[str] = None


class DatabaseConfig(BaseModel):
    provider: str = "sqlite"
    url: str = "sqlite:///ai_engineer.db"


class StorageConfig(BaseModel):
    provider: str = "local"
    root: str = "workspace"


class ExecutionConfig(BaseModel):
    mode: str = "supervised"   # assisted | supervised | autonomous
    max_retries: int = 2


class SecurityConfig(BaseModel):
    sandbox: bool = True
    approval_required: bool = True


class AppConfig(BaseModel):
    llm: LLMConfig = LLMConfig()
    search: SearchConfig = SearchConfig()
    cad: CADConfig = CADConfig()
    eda: EDAConfig = EDAConfig()
    database: DatabaseConfig = DatabaseConfig()
    storage: StorageConfig = StorageConfig()
    execution: ExecutionConfig = ExecutionConfig()
    security: SecurityConfig = SecurityConfig()


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    p = Path(path)
    if not p.exists():
        return AppConfig()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(data)
