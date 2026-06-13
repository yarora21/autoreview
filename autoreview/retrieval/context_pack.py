from __future__ import annotations

from pydantic import BaseModel

from autoreview.core.schemas import CodeChunk, DiffChunk

# ~1 token per 4 characters, good enough for budget management
def _token_estimate(text: str) -> int:
    return len(text) // 4


class ContextPack(BaseModel):
    diff_chunks: list[DiffChunk]
    context_chunks: list[CodeChunk] = []

    def to_prompt_text(self) -> str:
        """Format the full context into a single string for the LLM prompt."""
        parts = ["## Diff (what changed)\n"]
        for chunk in self.diff_chunks:
            parts.append(f"--- {chunk.file_path} lines {chunk.start_line}-{chunk.end_line} ---\n{chunk.content}")

        if self.context_chunks:
            parts.append("\n## Relevant context from the codebase\n")
            for chunk in self.context_chunks:
                parts.append(f"--- {chunk.qualified_name} ({chunk.file_path} lines {chunk.start_line}-{chunk.end_line}) ---\n{chunk.content}")

        return "\n".join(parts)


def build_context_pack(
    diff_chunks: list[DiffChunk],
    ranked_chunks: list[CodeChunk],
    token_budget: int = 6000,
) -> ContextPack:
    """
    Assemble a ContextPack within the token budget.
    The diff is always included. Retrieved chunks are added until the budget is exhausted.
    """
    diff_text = " ".join(c.content for c in diff_chunks)
    remaining = token_budget - _token_estimate(diff_text)

    kept: list[CodeChunk] = []
    for chunk in ranked_chunks:
        cost = _token_estimate(chunk.content)
        if cost > remaining:
            break
        kept.append(chunk)
        remaining -= cost

    return ContextPack(diff_chunks=diff_chunks, context_chunks=kept)
