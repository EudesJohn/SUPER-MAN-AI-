"""Typed domain models shared across the platform.

Every important object carries traceability metadata: sources, assumptions,
confidence. Unknown values must stay None - never invented (regle absolue).
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class Priority(str, Enum):
    MANDATORY = "mandatory"
    DESIRED = "desired"
    OPTIONAL = "optional"


class RequirementStatus(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    UNCERTAIN = "uncertain"


class Requirement(BaseModel):
    """Formal requirement extracted from the cahier des charges."""

    id: str = Field(default_factory=lambda: new_id("REQ"))
    description: str
    quantity: Optional[str] = None        # normalized dimension, e.g. "mass", "speed"
    value: Optional[float] = None         # normalized (SI) value; None = INCONNU
    raw_value: Optional[str] = None       # as stated by the user
    unit: Optional[str] = None            # original unit as stated
    priority: Priority = Priority.MANDATORY
    source: str = "user"
    confidence: float = 1.0
    status: RequirementStatus = RequirementStatus.DRAFT
    dependencies: list[str] = Field(default_factory=list)


class CalculationRecord(BaseModel):
    """Reproducible calculation record (section 17 of the technical spec)."""

    id: str = Field(default_factory=lambda: new_id("CALC"))
    name: str
    formula: str
    inputs: dict[str, Any]
    units: dict[str, str]
    result: float
    result_unit: str
    assumptions: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    method: str = "closed-form"
    timestamp: str = Field(default_factory=utc_now_iso)
    requirement_ids: list[str] = Field(default_factory=list)


class SourceRef(BaseModel):
    """Provenance of information retrieved from the outside world."""

    url: Optional[str] = None
    title: str
    retrieved_at: str = Field(default_factory=utc_now_iso)
    date: Optional[str] = None            # publication date if known
    confidence: Confidence = Confidence.UNKNOWN
    excerpt: Optional[str] = None


class Assumption(BaseModel):
    id: str = Field(default_factory=lambda: new_id("HYP"))
    statement: str
    rationale: str = ""
    created_by: str = ""
    timestamp: str = Field(default_factory=utc_now_iso)


class VerificationOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    UNKNOWN = "UNKNOWN"


class VerificationResult(BaseModel):
    id: str = Field(default_factory=lambda: new_id("VER"))
    subject: str                          # what was verified
    outcome: VerificationOutcome
    detail: str
    checked_by: str = "VerificationEngine"
    timestamp: str = Field(default_factory=utc_now_iso)
    related_ids: list[str] = Field(default_factory=list)


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"


class Task(BaseModel):
    """Unit of work handled by one agent, with dependencies and retries."""

    id: str = Field(default_factory=lambda: new_id("TASK"))
    project_id: str = ""
    title: str
    agent: str
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 5
    dependencies: list[str] = Field(default_factory=list)
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    attempts: int = 0
    created_at: str = Field(default_factory=utc_now_iso)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class Artifact(BaseModel):
    """A file produced by the system, with checksum and version metadata."""

    id: str = Field(default_factory=lambda: new_id("ART"))
    project_id: str = ""
    path: str
    kind: str = "file"                    # report | calculation | cad | pcb | doc
    version: int = 1
    checksum: str = ""
    created_by: str = ""
    created_at: str = Field(default_factory=utc_now_iso)


class EventKind(str, Enum):
    PROJECT_CREATED = "PROJECT_CREATED"
    REQUIREMENT_ADDED = "REQUIREMENT_ADDED"
    PLAN_CREATED = "PLAN_CREATED"
    TASK_STARTED = "TASK_STARTED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    SEARCH_COMPLETED = "SEARCH_COMPLETED"
    COMPONENT_SELECTED = "COMPONENT_SELECTED"
    CALCULATION_COMPLETED = "CALCULATION_COMPLETED"
    CAD_CREATED = "CAD_CREATED"
    VERIFICATION_PASSED = "VERIFICATION_PASSED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    PROJECT_VALIDATED = "PROJECT_VALIDATED"
    INFO = "INFO"
