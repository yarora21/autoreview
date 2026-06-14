from __future__ import annotations

import logging
from pathlib import Path

import anthropic

from autoreview.core.schemas import Finding
from autoreview.retrieval.context_pack import ContextPack

logger = logging.getLogger(__name__)

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


def run_agent(
    name: str,
    prompt_path: Path,
    context: ContextPack,
    model: str = "claude-sonnet-4-20250514",
) -> list[Finding]:
    """Call Claude with a focused system prompt and return structured findings."""
    client = anthropic.Anthropic()
    system_prompt = prompt_path.read_text()

    try:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system_prompt,
            tools=[FINDING_TOOL],
            tool_choice={"type": "tool", "name": "report_findings"},
            messages=[{"role": "user", "content": f"Review this PR:\n\n{context.to_prompt_text()}"}],
        )
        findings = []
        for block in response.content:
            if block.type == "tool_use" and block.name == "report_findings":
                for f in block.input.get("findings", []):
                    if isinstance(f, dict):
                        try:
                            findings.append(Finding(**f))
                        except Exception as e:
                            logger.warning("%s agent: skipping malformed finding: %s", name, e)

        logger.info("%s agent: %d findings (tokens: %d)", name, len(findings),
                    response.usage.input_tokens + response.usage.output_tokens)
        return findings

    except Exception as e:
        logger.error("%s agent failed: %s", name, e)
        return []
