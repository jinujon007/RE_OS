"""Unit tests for Florence-2 evaluation pipeline (Sprint 37).

Tests the utility functions of eval_florence2.py without loading the model.
"""

import pytest

pytestmark = pytest.mark.unit

from unittest.mock import MagicMock, patch

import pytest

from scripts.eval_florence2 import (
    _calculate_cer,
    _get_device,
    _measure_vram,
    _model_size_mb,
)


class TestGetDevice:
    def test_cuda_available(self):
        with patch("scripts.eval_florence2.torch.cuda.is_available", return_value=True):
            assert _get_device() == "cuda"

    def test_cuda_unavailable(self):
        with patch(
            "scripts.eval_florence2.torch.cuda.is_available", return_value=False
        ):
            assert _get_device() == "cpu"


class TestMeasureVram:
    def test_cpu_returns_zero(self):
        with patch(
            "scripts.eval_florence2.torch.cuda.is_available", return_value=False
        ):
            vram = _measure_vram()
            assert vram == {"allocated_mb": 0, "reserved_mb": 0, "max_allocated_mb": 0}

    def test_cuda_returns_values(self):
        mock = MagicMock()
        mock.memory_allocated.return_value = 500 * 1024**2
        mock.memory_reserved.return_value = 600 * 1024**2
        mock.max_memory_allocated.return_value = 700 * 1024**2
        with (
            patch("scripts.eval_florence2.torch.cuda", mock),
            patch("scripts.eval_florence2.torch.cuda.is_available", return_value=True),
        ):
            vram = _measure_vram()
            assert vram["allocated_mb"] == 500.0
            assert vram["reserved_mb"] == 600.0
            assert vram["max_allocated_mb"] == 700.0

    def test_non_negative_clamp(self):
        mock = MagicMock()
        mock.memory_allocated.return_value = -1
        mock.memory_reserved.return_value = -1
        mock.max_memory_allocated.return_value = -1
        with (
            patch("scripts.eval_florence2.torch.cuda", mock),
            patch("scripts.eval_florence2.torch.cuda.is_available", return_value=True),
        ):
            vram = _measure_vram()
            assert vram["allocated_mb"] == 0
            assert vram["reserved_mb"] == 0
            assert vram["max_allocated_mb"] == 0


class TestModelSizeMb:
    def _make_param(self, numel, element_size, ptr_val):
        p = MagicMock(spec=[])
        p.numel = MagicMock(return_value=numel)
        p.element_size = MagicMock(return_value=element_size)
        p.data_ptr = MagicMock(return_value=ptr_val)
        return p

    def test_single_parameter_tensor(self):
        param = self._make_param(1000, 4, 42)
        mock_model = MagicMock(spec=[])
        mock_model.parameters = MagicMock(return_value=[param])
        size = _model_size_mb(mock_model)
        # 1000*4 = 4000 bytes. 4000/1024**2 = 0.00381... -> round to 1 decimal = 0.0
        assert size >= 0.0
        assert size < 0.01

    def test_shared_parameters_deduped(self):
        p1 = self._make_param(230_000_000, 2, 100)  # ~230M params * 2 bytes = ~460 MB
        p2 = self._make_param(
            1_400_000, 2, 100
        )  # Shared ptr — same as p1, should NOT double
        mock_model = MagicMock(spec=[])
        mock_model.parameters = MagicMock(return_value=[p1, p2])
        size = _model_size_mb(mock_model)
        # ~230M * 2 = 460000000 bytes = 438.69 MB, round to 1 decimal = 438.7
        # The shared param with same ptr should NOT be double-counted
        assert (
            size < 440.0
        )  # Should be ~438.7, not ~442.0 (would include shared weight)


class TestCalculateCer:
    def test_exact_match(self):
        assert _calculate_cer("hello world", "hello world") == 0.0

    def test_completely_different(self):
        cer = _calculate_cer("abc", "xyz")
        assert cer > 0.5

    def test_empty_reference_empty_hypothesis(self):
        assert _calculate_cer("", "") == 0.0

    def test_empty_reference_nonempty_hypothesis(self):
        assert _calculate_cer("", "abc") == 1.0

    def test_single_char_insertion(self):
        cer = _calculate_cer("abc", "abxc")
        assert 0.0 < cer < 1.0

    def test_single_char_deletion(self):
        cer = _calculate_cer("abcd", "abd")
        assert 0.0 < cer < 1.0

    def test_case_insensitive(self):
        assert _calculate_cer("Hello", "hello") == 0.0

    def test_same_content_different_whitespace(self):
        assert _calculate_cer("hello world", "helloworld") < 1.0


class TestMain:
    def test_missing_images_returns_error(self):
        with (
            patch("scripts.eval_florence2._load_images", return_value={}),
            patch("scripts.eval_florence2._cleanup_gpu"),
        ):
            from scripts.eval_florence2 import main

            assert main() == 1

    def test_model_load_failure_returns_error(self):
        mock_images = {"site_plan_sample.png": MagicMock()}
        with (
            patch("scripts.eval_florence2._load_images", return_value=mock_images),
            patch(
                "scripts.eval_florence2.AutoProcessor.from_pretrained",
                side_effect=RuntimeError("OOM"),
            ),
            patch("scripts.eval_florence2._cleanup_gpu"),
        ):
            from scripts.eval_florence2 import main

            assert main() == 1


@pytest.fixture(autouse=True)
def _no_gpu():
    """Prevent GPU usage in all tests by mocking cuda to False."""
    with patch("scripts.eval_florence2.torch.cuda.is_available", return_value=False):
        yield
