"""
Embedding provider layer.

Architecture note (see blueprint Section 4.2): the production system should
embed resume and JD text with a LoRA-tuned Sentence-BERT model. That requires
`sentence-transformers` + downloaded model weights, which this sandbox can't
fetch. The interface below is written so that swapping the fallback for the
real SBERT model in production is a one-line change everywhere else in the
codebase -- nothing that calls `get_embedding_provider()` needs to know or
care which implementation is behind it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import numpy as np


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:
        """Return an (n_texts, dim) array of dense vectors."""
        raise NotImplementedError


class TfidfEmbeddingProvider(EmbeddingProvider):
    """
    Dependency-light fallback used for local dev, tests, and this scaffold.

    This is intentionally NOT what the blueprint recommends for production
    (Section 4.2 explicitly moves off TF-IDF/keyword matching to SBERT,
    because TF-IDF can't tell "software development" and "software
    engineering" are the same competency). It exists here so the scoring
    pipeline is fully runnable and testable without a GPU or model download.
    """

    def __init__(self) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer

        self._vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))

    def embed(self, texts: list[str]) -> np.ndarray:
        matrix = self._vectorizer.fit_transform(texts)
        return matrix.toarray()


class SBERTEmbeddingProvider(EmbeddingProvider):
    """
    Production adapter.

    Requires: pip install sentence-transformers
    Requires network access to download model weights (or a pre-baked
    model volume / internal model registry in the deploy environment).

    Swap in a LoRA fine-tune checkpoint here once one is trained on
    HR-domain vocabulary (blueprint Section 4.2).
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model_name
        self._model = None  # lazy-loaded so import-time never requires torch

    def embed(self, texts: list[str]) -> np.ndarray:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return np.asarray(self._model.encode(texts))


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


_provider: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    """
    Single point of configuration. In production, set EMBEDDING_BACKEND=sbert
    via environment/settings and this returns the real adapter instead.
    """
    global _provider
    if _provider is None:
        import os

        if os.environ.get("EMBEDDING_BACKEND") == "sbert":
            _provider = SBERTEmbeddingProvider()
        else:
            _provider = TfidfEmbeddingProvider()
    return _provider
push