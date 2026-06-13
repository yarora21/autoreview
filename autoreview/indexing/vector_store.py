from __future__ import annotations

from pathlib import Path

import chromadb

from autoreview.core.schemas import CodeChunk


class VectorStore:
    """Thin wrapper around a ChromaDB collection for storing and searching code chunks."""

    def __init__(self, persist_dir: Path, collection_name: str = "code"):
        self.client = chromadb.PersistentClient(path=str(persist_dir))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, chunks: list[CodeChunk], embeddings: list[list[float]]) -> None:
        """Store chunks and their embeddings. Re-running is idempotent."""
        self.collection.upsert(
            ids=[f"{c.file_path}::{c.qualified_name}" for c in chunks],
            embeddings=embeddings,
            documents=[c.content for c in chunks],
            metadatas=[c.model_dump(exclude={"content"}) for c in chunks],
        )

    def search(self, query_embedding: list[float], k: int = 5) -> list[CodeChunk]:
        """Return the k most similar chunks to the query embedding."""
        results = self.collection.query(query_embeddings=[query_embedding], n_results=k)
        chunks = []
        for metadata, document in zip(results["metadatas"][0], results["documents"][0]):
            chunks.append(CodeChunk(**metadata, content=document))
        return chunks

    def count(self) -> int:
        return self.collection.count()
