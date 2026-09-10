import numpy as np

from app.core.scoring.embeddings import cosine_similarity, scaled_similarity


def test_cosine_similarity_matches_the_l2_normalized_formula_directly():
    a = np.array([3.0, 4.0])  # norm = 5
    b = np.array([6.0, 8.0])  # norm = 10, same direction as a
    # Same direction -> cosine similarity should be exactly 1.0
    assert abs(cosine_similarity(a, b) - 1.0) < 1e-9


def test_cosine_similarity_orthogonal_vectors_is_zero():
    a = np.array([1.0, 0.0])
    b = np.array([0.0, 1.0])
    assert abs(cosine_similarity(a, b)) < 1e-9


def test_cosine_similarity_opposite_vectors_is_negative_one():
    a = np.array([1.0, 0.0])
    b = np.array([-1.0, 0.0])
    assert abs(cosine_similarity(a, b) - (-1.0)) < 1e-9


def test_cosine_similarity_zero_vector_does_not_divide_by_zero():
    a = np.array([0.0, 0.0])
    b = np.array([1.0, 0.0])
    assert cosine_similarity(a, b) == 0.0


def test_cosine_similarity_result_is_independent_of_vector_magnitude():
    """Verifies the normalization is real: scaling either vector's
    magnitude shouldn't change the similarity at all."""
    a = np.array([1.0, 2.0, 3.0])
    b = np.array([2.0, 1.0, 0.5])
    base = cosine_similarity(a, b)
    scaled_a = a * 1000
    scaled_b = b * 0.0001
    assert abs(cosine_similarity(scaled_a, scaled_b) - base) < 1e-9


def test_scaled_similarity_clamps_negative_to_zero():
    a = np.array([1.0, 0.0])
    b = np.array([-1.0, 0.0])
    assert scaled_similarity(a, b) == 0.0


def test_scaled_similarity_passes_through_nonnegative_values_unchanged():
    a = np.array([3.0, 4.0])
    b = np.array([6.0, 8.0])
    assert abs(scaled_similarity(a, b) - 1.0) < 1e-9


def test_scaled_similarity_always_in_unit_range():
    import random
    random.seed(0)
    for _ in range(20):
        a = np.array([random.uniform(-5, 5) for _ in range(4)])
        b = np.array([random.uniform(-5, 5) for _ in range(4)])
        result = scaled_similarity(a, b)
        assert 0.0 <= result <= 1.0


# --------------------------------------------------------------------
# Degenerate input: nothing survives tokenizing
# --------------------------------------------------------------------
#
# sklearn raises ValueError("empty vocabulary; perhaps the documents only
# contain stop words") when no term survives across every text in the
# call. Both documents are fitted together, so it needs the resume and
# the JD to be degenerate at the same time -- which is a normal product
# state rather than a malformed request: /resume/parse-file returns
# `resume: {}` for a scanned or image-only PDF and calls that an expected
# outcome, and a blank or all-stop-words JD is one distracted paste away.
# Unhandled, that pairing was an uncaught 500 from /score/jd-match and
# /score/full-report.


def test_embed_returns_zero_vectors_when_no_terms_survive():
    from app.core.scoring.embeddings import TfidfEmbeddingProvider

    vectors = TfidfEmbeddingProvider().embed(["", "the and or of"])

    assert vectors.shape[0] == 2
    assert not vectors.any(), "no terms means no signal -- every component should be zero"


def test_zero_vectors_score_as_no_similarity_rather_than_erroring():
    from app.core.scoring.embeddings import TfidfEmbeddingProvider

    vectors = TfidfEmbeddingProvider().embed(["   ", ""])

    # cosine_similarity already returns 0.0 for a zero-norm vector, so the
    # zero vectors above flow through the rest of the pipeline as an
    # honest "0% semantic match" instead of propagating an exception.
    assert scaled_similarity(vectors[0], vectors[1]) == 0.0


def test_a_real_pair_is_unaffected_by_the_guard():
    from app.core.scoring.embeddings import TfidfEmbeddingProvider

    vectors = TfidfEmbeddingProvider().embed(
        ["Senior Python engineer, AWS and PostgreSQL", "Looking for a Python engineer with AWS"]
    )

    assert vectors.any(), "real text must still produce real vectors"
    assert scaled_similarity(vectors[0], vectors[1]) > 0.0


def test_a_different_value_error_is_not_swallowed():
    """The guard matches on sklearn's specific message. Anything else must
    still surface -- silently returning zeros for an unrelated failure
    would turn a bug into a plausible-looking score."""
    import pytest

    from app.core.scoring.embeddings import TfidfEmbeddingProvider

    provider = TfidfEmbeddingProvider()

    class _Boom:
        def fit_transform(self, texts):
            raise ValueError("something else entirely")

    provider._vectorizer = _Boom()
    with pytest.raises(ValueError, match="something else entirely"):
        provider.embed(["anything"])
