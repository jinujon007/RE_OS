import pytest
pytestmark = pytest.mark.unit

from utils.green_coverage import (
    calculate_green_coverage,
    GreenCoverageResult,
    _MIN_GREEN_PCT_BDA,
    _SQFT_PER_TREE,
)


class TestCalculateGreenCoverage:
    """Core calculation correctness — matches TASK_BRIEFS.md spec."""

    def test_standard_r2_coverage(self):
        r = calculate_green_coverage(10000, 0.55)
        assert r.landscape_area_sqft == pytest.approx(4500.0)
        assert r.green_pct == pytest.approx(45.0)

    def test_zero_land_area(self):
        r = calculate_green_coverage(0, 0.55)
        assert r.landscape_area_sqft == 0.0
        assert r.tree_count == 1

    def test_full_built_coverage(self):
        r = calculate_green_coverage(10000, 1.0)
        assert r.landscape_area_sqft == 0.0
        assert r.green_pct == 0.0
        assert r.meets_bda_minimum is False

    def test_zero_built_coverage(self):
        r = calculate_green_coverage(10000, 0.0)
        assert r.landscape_area_sqft == 10000.0
        assert r.green_pct == 100.0
        assert r.meets_bda_minimum is True

    def test_bda_minimum_exactly_met(self):
        r = calculate_green_coverage(10000, 0.85)
        assert r.meets_bda_minimum is True

    def test_bda_minimum_just_missed(self):
        r = calculate_green_coverage(10000, 0.86)
        assert r.meets_bda_minimum is False

    def test_tree_count_calculation(self):
        r = calculate_green_coverage(10000, 0.55)
        expected_trees = int(4500 / _SQFT_PER_TREE)
        assert r.tree_count == expected_trees

    def test_built_coverage_clamped_above_1(self):
        r = calculate_green_coverage(10000, 2.0)
        assert r.built_coverage_pct == 1.0
        assert r.landscape_area_sqft == 0.0


class TestEdgeCases:
    """Boundary and edge-case coverage — negative inputs, defaults, precision."""

    def test_negative_land_area_clamped(self):
        r = calculate_green_coverage(-5000, 0.55)
        assert r.land_area_sqft == 0.0
        assert r.landscape_area_sqft == 0.0
        assert r.tree_count == 1
        assert r.green_pct == 0.0
        assert r.meets_bda_minimum is False

    def test_negative_built_coverage_clamped(self):
        r = calculate_green_coverage(10000, -0.5)
        assert r.built_coverage_pct == 0.0
        assert r.landscape_area_sqft == 10000.0
        assert r.green_pct == 100.0

    def test_default_built_coverage(self):
        r = calculate_green_coverage(10000)
        assert r.built_coverage_pct == 0.55
        assert r.landscape_area_sqft == pytest.approx(4500.0)

    def test_small_land_area_floor_one_tree(self):
        r = calculate_green_coverage(50, 0.0)
        assert r.landscape_area_sqft == 50.0
        assert r.tree_count == 1

    def test_fractional_landscape_rounded(self):
        r = calculate_green_coverage(10001, 0.55)
        expected = round(10001 * 0.45, 1)
        assert r.landscape_area_sqft == expected

    def test_very_large_land_area(self):
        r = calculate_green_coverage(10_000_000, 0.55)
        assert r.landscape_area_sqft == pytest.approx(4_500_000.0)
        assert r.tree_count == int(4_500_000 / _SQFT_PER_TREE)

    def test_bda_precision_nonround_land(self):
        """meets_bda_minimum uses rounded green_pct to match display field.
        Regression guard: floating-point edge case where raw green_pct ~14.9999
        should round to 15.0 and count as compliant."""
        landscape = 1500.0
        land = 10000
        coverage = 0.85
        r = calculate_green_coverage(land, coverage)
        assert r.green_pct == pytest.approx(15.0)
        assert r.meets_bda_minimum is True

    def test_bda_precision_just_below_rounds_up(self):
        """Raw green_pct 14.9999 due to FP precision rounds to 15.0 → BDA met."""
        land = 43560
        coverage = 0.85
        r = calculate_green_coverage(land, coverage)
        raw_green = (land * (1 - coverage)) / land * 100
        assert raw_green == pytest.approx(15.0)
        assert r.meets_bda_minimum is True

    def test_tree_count_boundary_sqft(self):
        r1 = calculate_green_coverage(_SQFT_PER_TREE, 0.0)
        assert r1.tree_count == 1
        r2 = calculate_green_coverage(_SQFT_PER_TREE * 2 - 1, 0.0)
        assert r2.tree_count == 1
        r3 = calculate_green_coverage(_SQFT_PER_TREE * 2, 0.0)
        assert r3.tree_count == 2
        r4 = calculate_green_coverage(_SQFT_PER_TREE * 2 + 1, 0.0)
        assert r4.tree_count == 2
        r5 = calculate_green_coverage(_SQFT_PER_TREE * 10, 0.0)
        assert r5.tree_count == 10


class TestInvariants:
    """Properties that must always hold regardless of input."""

    LAND_VALUES = [0, 1, 100, 43560, 100000, 10_000_000]
    COVERAGE_VALUES = [0.0, 0.1, 0.55, 0.85, 1.0]

    def test_tree_count_at_least_one(self):
        for land in self.LAND_VALUES:
            for cov in self.COVERAGE_VALUES:
                r = calculate_green_coverage(land, cov)
                assert r.tree_count >= 1, f"land={land} cov={cov} → tree_count={r.tree_count}"

    def test_green_pct_range_0_to_100(self):
        for land in self.LAND_VALUES:
            for cov in self.COVERAGE_VALUES:
                r = calculate_green_coverage(land, cov)
                assert 0.0 <= r.green_pct <= 100.0, f"land={land} cov={cov} → green_pct={r.green_pct}"

    def test_landscape_nonnegative(self):
        for land in self.LAND_VALUES:
            for cov in self.COVERAGE_VALUES:
                r = calculate_green_coverage(land, cov)
                assert r.landscape_area_sqft >= 0.0

    def test_built_coverage_in_0_to_1(self):
        for cov in [-0.5, 0.0, 0.5, 1.0, 2.0, 999.0]:
            r = calculate_green_coverage(10000, cov)
            assert 0.0 <= r.built_coverage_pct <= 1.0, f"cov={cov} → built={r.built_coverage_pct}"

    def test_green_plus_built_approx_100(self):
        """For valid built coverage in [0,1], green_pct + 100*coverage ≈ 100."""
        for land in [100, 43560, 100000]:
            for cov in [0.0, 0.1, 0.55, 0.85]:
                r = calculate_green_coverage(land, cov)
                total = pytest.approx(100.0, abs=0.2)
                assert r.green_pct + r.built_coverage_pct * 100 == total, \
                    f"land={land} cov={cov}: {r.green_pct}+{r.built_coverage_pct*100} != 100"


class TestDataclassStructure:
    """Ensure the dataclass contract is stable."""

    def test_fields_present(self):
        r = calculate_green_coverage(10000, 0.55)
        assert hasattr(r, "land_area_sqft")
        assert hasattr(r, "built_coverage_pct")
        assert hasattr(r, "landscape_area_sqft")
        assert hasattr(r, "green_pct")
        assert hasattr(r, "tree_count")
        assert hasattr(r, "meets_bda_minimum")

    def test_field_types(self):
        r = calculate_green_coverage(10000, 0.55)
        assert isinstance(r.land_area_sqft, float)
        assert isinstance(r.built_coverage_pct, float)
        assert isinstance(r.landscape_area_sqft, float)
        assert isinstance(r.green_pct, float)
        assert isinstance(r.tree_count, int)
        assert isinstance(r.meets_bda_minimum, bool)

    def test_dataclass_repr(self):
        r = calculate_green_coverage(10000, 0.55)
        rep = repr(r)
        assert "GreenCoverageResult" in rep
        assert "land_area_sqft=10000.0" in rep or "land_area_sqft=10000" in rep
