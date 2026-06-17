"""T-1169: config/scheduler/__init__.py test."""
import pytest

pytestmark = pytest.mark.unit


def test_start_scheduler_importable():
    import config.scheduler
    assert hasattr(config.scheduler, 'start_scheduler')
    assert callable(config.scheduler.start_scheduler)
