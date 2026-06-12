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


class ReviewResult(BaseModel):
    pr_url: str
    findings: list[Finding] = []
    token_usage: int = 0
    cost_usd: float = 0.0
    latency_seconds: float = 0.0
