from __future__ import annotations

from abc import ABC, abstractmethod

import voyageai


class Embedder(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Convert a list of texts into a list of embedding vectors."""


class VoyageEmbedder(Embedder):
    """Embedder backed by Voyage AI's code embedding model."""

    def __init__(self, model: str = "voyage-code-3"):
        self.client = voyageai.Client()
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        result = self.client.embed(texts, model=self.model, input_type="document")
        return result.embeddings
