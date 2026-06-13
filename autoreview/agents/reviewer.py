from __future__ import annotations

import json
import time
import logging
from pathlib import Path

import anthropic

from autoreview.core.schemas import DiffChunk, Finding, ReviewResult
from autoreview.retrieval.context_pack import ContextPack

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent / "prompts" / "review.txt"
SYSTEM_PROMPT = PROMPT_PATH.read_text()

FINDING_TOOL = {
    "name": "report_findings",
    "description": "Report code review findings for the PR diff.",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "enum": ["bug", "security", "style", "performance", "maintainability"]},
                        "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
                        "file_path": {"type": "string"},
                        "start_line": {"type": "integer"},
                        "end_line": {"type": "integer"},
                        "description": {"type": "string"},
                        "suggested_fix": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["category", "severity", "file_path", "start_line", "end_line", "description", "confidence"],
                },
            }
        },
        "required": ["findings"],
    },
}

# Sonnet pricing per million tokens
INPUT_COST_PER_M = 3.0
OUTPUT_COST_PER_M = 15.0


def _estimate_cost(usage: anthropic.types.Usage) -> float:
    return (usage.input_tokens * INPUT_COST_PER_M + usage.output_tokens * OUTPUT_COST_PER_M) / 1_000_000


def review(pr_url: str, context: ContextPack, model: str = "claude-sonnet-4-20250514") -> ReviewResult:
    client = anthropic.Anthropic()

    start = time.time()
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[FINDING_TOOL],
        tool_choice={"type": "tool", "name": "report_findings"},
        messages=[{"role": "user", "content": f"Review this PR:\n\n{context.to_prompt_text()}"}],
    )
    latency = time.time() - start

    # Extract findings from tool use
    findings = []
    for block in response.content:
        if block.type == "tool_use" and block.name == "report_findings":
            for f in block.input.get("findings", []):
                findings.append(Finding(**f))

    total_tokens = response.usage.input_tokens + response.usage.output_tokens
    cost = _estimate_cost(response.usage)

    logger.info(
        "LLM call: model=%s tokens=%d (in=%d out=%d) cost=$%.4f latency=%.1fs findings=%d",
        model, total_tokens, response.usage.input_tokens, response.usage.output_tokens,
        cost, latency, len(findings),
    )

    return ReviewResult(
        pr_url=pr_url,
        findings=findings,
        token_usage=total_tokens,
        cost_usd=cost,
        latency_seconds=round(latency, 2),
    )
