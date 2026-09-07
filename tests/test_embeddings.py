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
