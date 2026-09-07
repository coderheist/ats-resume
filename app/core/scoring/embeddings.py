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

        # use_idf=False: IDF ("how rare is this term across the corpus")
        # is meaningless -- and actively harmful here -- when the "corpus"
        # is just the 2 documents being compared in a single embed() call
        # (see score_resume_against_jd / screening_report.py, which both
        # call embed([resume_text, jd_text])). A 2-document IDF makes any
        # term that happens to appear in only one of the two get maximal
        # weight, and any term shared by both collapse toward ~0 -- i.e.
        # cosine similarity actively *penalizes* genuine lexical overlap
        # rather than rewarding it. Verified empirically before this fix:
        # "python developer" vs. a bullet containing "Python" scored 0.09
        # despite an exact word match. With use_idf=False this is plain
        # L2-normalized term-frequency (sklearn's default norm='l2'
        # still applies), which has no such degenerate case.
        self._vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), use_idf=False)

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
    """
    Similarity = (A . B) / (||A|| ||B||) -- dividing by both norms is
    mathematically identical to L2-normalizing A and B first and then
    taking their dot product; this isn't an approximation of that, it's
    the same computation. Verified correct as-is; not touched by the
    hardening below.
    """
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def scaled_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    cosine_similarity() output, defensively clamped into [0, 1] before
    hybrid_score.py scales it to a 0-100 percentage.

    Today's TfidfEmbeddingProvider can't actually produce a negative
    value here -- term-frequency vectors are non-negative by
    construction, so the raw cosine similarity is already in [0, 1].
    SBERTEmbeddingProvider's dense vectors can, though (real, if
    semantically opposite, text can score slightly negative) -- and
    without this clamp that would surface as a negative "% match" in the
    XAI panel and could pull final_score below 0.

    Design choice: negative similarity clamps to 0, not linearly
    rescaled so 0-similarity maps to 50%. This is a match *score*, not a
    general-purpose similarity metric -- "semantically unrelated" and
    "semantically opposite" both mean "not a match", and a 50% floor for
    text with zero topical overlap would overstate relevance. If that
    turns out to lose signal worth keeping, this is the one line to
    change.
    """
    raw = cosine_similarity(a, b)
    return max(0.0, min(1.0, raw))


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
