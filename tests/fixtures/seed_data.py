"""Shared test fixtures for demand calibration and gate tests.

``LINEAR_SEED_DATA`` — 5-year synthetic trend (R² ≈ 0.97) used by
``test_gate109.py`` and ``test_demand_calibration.py``.

Each tuple: ``(calendar_year, units_absorbed, median_psf)``
"""

LINEAR_SEED_DATA: list[tuple[int, int, float]] = [
    (2019, 500, 5500.0),
    (2020, 900, 5800.0),
    (2021, 930, 6000.0),
    (2022, 960, 6200.0),
    (2023, 990, 6500.0),
]
