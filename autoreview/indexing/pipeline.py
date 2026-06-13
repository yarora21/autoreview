from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from autoreview.indexing.chunker import chunk_file
from autoreview.indexing.embedder import VoyageEmbedder
from autoreview.indexing.structural import build_index
from autoreview.indexing.vector_store import VectorStore

logger = logging.getLogger(__name__)

INDEX_DIR_NAME = ".autoreview_index"


def index_repo(repo_path: Path) -> dict:
    """
    Index all Python files in a repo.
    Produces a ChromaDB vector store and a structural index on disk.
    Returns stats about the run.
    """
    repo_path = repo_path.resolve()
    index_dir = repo_path / INDEX_DIR_NAME
    index_dir.mkdir(exist_ok=True)

    start = time.time()

    # 1. Chunk all .py files
    py_files = list(repo_path.rglob("*.py"))
    all_chunks = []
    for f in py_files:
        try:
            all_chunks.extend(chunk_file(f))
        except Exception as e:
            logger.warning("Failed to chunk %s: %s", f, e)

    logger.info("Chunked %d files → %d chunks", len(py_files), len(all_chunks))

    # 2. Embed all chunks in one batch
    embedder = VoyageEmbedder()
    embeddings = embedder.embed([c.content for c in all_chunks])

    # 3. Store in ChromaDB
    store = VectorStore(persist_dir=index_dir / "chroma")
    store.upsert(all_chunks, embeddings)

    # 4. Build and save structural index
    structural = build_index(repo_path)
    structural_path = index_dir / "structural.json"
    structural_path.write_text(json.dumps({
        "call_graph": {k: list(v) for k, v in structural.call_graph.items()},
        "import_index": {k: list(v) for k, v in structural.import_index.items()},
    }, indent=2))

    elapsed = round(time.time() - start, 2)
    stats = {
        "files": len(py_files),
        "chunks": len(all_chunks),
        "latency_seconds": elapsed,
    }
    logger.info("Index complete: %s", stats)
    return stats


def load_vector_store(repo_path: Path) -> VectorStore:
    index_dir = repo_path.resolve() / INDEX_DIR_NAME
    return VectorStore(persist_dir=index_dir / "chroma")


def load_structural(repo_path: Path) -> dict:
    index_dir = repo_path.resolve() / INDEX_DIR_NAME
    return json.loads((index_dir / "structural.json").read_text())
