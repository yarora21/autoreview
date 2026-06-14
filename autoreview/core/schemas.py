from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class Category(str, Enum):
    bug = "bug"
    security = "security"
    style = "style"
    performance = "performance"
    maintainability = "maintainability"


class DiffChunk(BaseModel):
    file_path: str
    start_line: int
    end_line: int
    content: str


class Finding(BaseModel):
    category: Category
    severity: Severity
    file_path: str
    start_line: int
    end_line: int
    description: str
    suggested_fix: Optional[str] = None
    confidence: float = Field(ge=0, le=1)


class CodeChunk(BaseModel):
    """A function, class, or module-level block extracted from source code."""
    file_path: str
    qualified_name: str  # e.g. "MyClass.my_method" or "top_level_func"
    kind: str  # "function", "class", or "module"
    start_line: int
    end_line: int
    content: str
    docstring: Optional[str] = None


class EvalItem(BaseModel):
    """A single labeled benchmark item."""
    repo: str           # e.g. "psf/requests"
    pr_number: int
    pr_url: str
    label: str          # "bug" or "clean"
    # For bug items: where the ground-truth bug was
    bug_file: Optional[str] = None
    bug_start_line: Optional[int] = None
    bug_end_line: Optional[int] = None
    category: Optional[str] = None  # expected category: bug/security/etc.


class ReviewResult(BaseModel):
    pr_url: str
    findings: list[Finding] = []
    token_usage: int = 0
    cost_usd: float = 0.0
    latency_seconds: float = 0.0
