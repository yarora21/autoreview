from __future__ import annotations

import re

from autoreview.core.schemas import CodeChunk, DiffChunk
from autoreview.indexing.embedder import VoyageEmbedder
from autoreview.indexing.vector_store import VectorStore


# Matches Python function/method definitions to extract names from a diff
_FUNC_DEF_RE = re.compile(r"^\+?\s*def\s+(\w+)", re.MULTILINE)


def _extract_changed_functions(diff_chunks: list[DiffChunk]) -> list[str]:
    """Pull out function names that appear as definitions in the diff."""
    names = []
    for chunk in diff_chunks:
        names.extend(_FUNC_DEF_RE.findall(chunk.content))
    return list(set(names))


def retrieve(
    diff_chunks: list[DiffChunk],
    store: VectorStore,
    structural: dict,
    k: int = 10,
) -> list[CodeChunk]:
    """
    Return relevant CodeChunks for the given diff using two strategies:
    1. Vector search  — semantically similar chunks
    2. Structural     — direct callers of changed functions (ranked higher)
    """
    embedder = VoyageEmbedder()
    diff_text = "\n".join(c.content for c in diff_chunks)

    # 1. Vector search
    [query_vec] = embedder.embed([diff_text])
    vector_hits = store.search(query_vec, k=k)

    # 2. Structural: find callers of any function changed in the diff
    call_graph = structural.get("call_graph", {})
    changed_fns = _extract_changed_functions(diff_chunks)
    caller_names = set()
    for fn in changed_fns:
        caller_names.update(call_graph.get(fn, []))

    # Promote structural hits to the front, dedupe by qualified_name
    seen: set[str] = set()
    ranked: list[CodeChunk] = []

    # Structural hits first
    for chunk in vector_hits:
        if chunk.qualified_name in caller_names:
            ranked.append(chunk)
            seen.add(chunk.qualified_name)

    # Then remaining vector hits
    for chunk in vector_hits:
        if chunk.qualified_name not in seen:
            ranked.append(chunk)
            seen.add(chunk.qualified_name)

    return ranked
