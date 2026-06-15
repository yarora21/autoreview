from __future__ import annotations

import time
from abc import ABC, abstractmethod

import voyageai


class Embedder(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Convert a list of texts into a list of embedding vectors."""


class VoyageEmbedder(Embedder):
    """Embedder backed by Voyage AI's code embedding model.

    Batches requests to stay within rate limits (default: 8K tokens/batch,
    25s between batches). Adjust batch_tokens and sleep_seconds for paid tiers.
    """

    def __init__(
        self,
        model: str = "voyage-code-3",
        batch_tokens: int = 8000,
        sleep_seconds: float = 25.0,
    ):
        self.client = voyageai.Client()
        self.model = model
        self.batch_tokens = batch_tokens
        self.sleep_seconds = sleep_seconds

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Split into batches by estimated token count (4 chars ≈ 1 token)
        batches: list[list[str]] = []
        current: list[str] = []
        current_tokens = 0

        for text in texts:
            estimated = len(text) // 4
            if current and current_tokens + estimated > self.batch_tokens:
                batches.append(current)
                current = []
                current_tokens = 0
            current.append(text)
            current_tokens += estimated

        if current:
            batches.append(current)

        all_embeddings: list[list[float]] = []
        for i, batch in enumerate(batches):
            if i > 0:
                time.sleep(self.sleep_seconds)
            result = self.client.embed(batch, model=self.model, input_type="document")
            all_embeddings.extend(result.embeddings)

        return all_embeddings
