"""
Unit tests for Memory score normalizer functions.

Memory uses two normalizers for converting raw FAISS scores to [0, 1] similarity:
  - _cosine_normalizer(val): maps cosine inner product → (1 + val) / 2, clamped [0, 1]
  - _score_normalizer(val): sigmoid transform → 1 - 1/(1 + exp(val)), general distance→score
"""
import math
import pytest
from helpers.memory import Memory


# ── _cosine_normalizer ─────────────────────────────────────────────────────────

@pytest.mark.unit
class TestCosineNormalizer:
    """Tests for Memory._cosine_normalizer(val)."""

    def test_zero_input_returns_half(self):
        """cosine(0) → (1+0)/2 = 0.5."""
        assert Memory._cosine_normalizer(0.0) == pytest.approx(0.5)

    def test_positive_one_returns_one(self):
        """cosine(1.0) → (1+1)/2 = 1.0."""
        assert Memory._cosine_normalizer(1.0) == pytest.approx(1.0)

    def test_negative_one_returns_zero(self):
        """cosine(-1.0) → (1-1)/2 = 0.0."""
        assert Memory._cosine_normalizer(-1.0) == pytest.approx(0.0)

    def test_midpoint_positive(self):
        """cosine(0.5) → 0.75."""
        assert Memory._cosine_normalizer(0.5) == pytest.approx(0.75)

    def test_midpoint_negative(self):
        """cosine(-0.5) → 0.25."""
        assert Memory._cosine_normalizer(-0.5) == pytest.approx(0.25)

    def test_clamps_above_one(self):
        """Float precision overflow above 1.0 is clamped to 1.0."""
        # FAISS can return values like 1.0000000596046448 due to float precision
        result = Memory._cosine_normalizer(1.0000000596046448)
        assert result == pytest.approx(1.0)
        assert result <= 1.0

    def test_clamps_below_zero(self):
        """Values that produce below 0.0 are clamped to 0.0."""
        result = Memory._cosine_normalizer(-1.0000001)
        assert result == pytest.approx(0.0)
        assert result >= 0.0

    def test_output_always_in_unit_interval(self):
        """Result is always in [0, 1] for extreme inputs."""
        for val in [-10.0, -2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, 10.0]:
            result = Memory._cosine_normalizer(val)
            assert 0.0 <= result <= 1.0, f'Out of range for val={val}: {result}'

    def test_monotonically_increasing(self):
        """Higher cosine distance produces higher normalised score."""
        vals = [-1.0, -0.5, 0.0, 0.5, 1.0]
        results = [Memory._cosine_normalizer(v) for v in vals]
        assert results == sorted(results), 'Result must be monotonically increasing'


# ── _score_normalizer ──────────────────────────────────────────────────────────

@pytest.mark.unit
class TestScoreNormalizer:
    """Tests for Memory._score_normalizer(val)."""

    def test_zero_input_returns_point_five(self):
        """score(0) → 1 - 1/(1+exp(0)) = 1 - 0.5 = 0.5."""
        assert Memory._score_normalizer(0.0) == pytest.approx(0.5)

    def test_large_positive_approaches_one(self):
        """Large positive → sigmoid approaches 1.0."""
        result = Memory._score_normalizer(100.0)
        assert result > 0.999

    def test_large_negative_approaches_zero(self):
        """Large negative → sigmoid approaches 0.0."""
        result = Memory._score_normalizer(-100.0)
        assert result < 0.001

    def test_positive_one(self):
        """score(1.0) = 1 - 1/(1+e) ≈ 0.7311."""
        expected = 1 - 1 / (1 + math.exp(1.0))
        assert Memory._score_normalizer(1.0) == pytest.approx(expected, rel=1e-6)

    def test_negative_one(self):
        """score(-1.0) = 1 - 1/(1+e^-1) ≈ 0.2689."""
        expected = 1 - 1 / (1 + math.exp(-1.0))
        assert Memory._score_normalizer(-1.0) == pytest.approx(expected, rel=1e-6)

    def test_output_bounded(self):
        """Result is in [0, 1] for extreme inputs; strictly (0,1) for moderate inputs.

        Note: float64 underflow at val=-50 causes 1+exp(-50)=1.0 exactly
        (exp(-50)~1.93e-22 < float64 epsilon ~2.22e-16), so result=0.0 exactly.
        This is correct float64 arithmetic, not a bug.
        """
        # Moderate range: result is strictly between 0 and 1
        for val in [-10.0, -1.0, 0.0, 1.0, 10.0]:
            result = Memory._score_normalizer(val)
            assert 0.0 < result < 1.0, f'Out of open interval for val={val}: {result}'
        # Extreme range: float64 saturation is acceptable — result stays in [0, 1]
        for val in [-50.0, 50.0]:
            result = Memory._score_normalizer(val)
            assert 0.0 <= result <= 1.0, f'Out of [0,1] for extreme val={val}: {result}'
    def test_symmetry_around_half(self):
        """score(x) + score(-x) ≈ 1.0 (sigmoid symmetry)."""
        for x in [0.5, 1.0, 2.0, 5.0]:
            assert Memory._score_normalizer(x) + Memory._score_normalizer(-x) == pytest.approx(1.0, rel=1e-6)
