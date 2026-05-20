"""
Unit tests for utils/db_organizer.py — logic that doesn't need a real DB.
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from utils.db_organizer import DBOrganizer


class TestComputeGrade:
    def test_known_grade_a_name(self):
        assert DBOrganizer._compute_grade("Brigade Enterprises", 10) == "A"

    def test_known_grade_a_name_case_insensitive(self):
        assert DBOrganizer._compute_grade("PRESTIGE GROUP", 50) == "A"

    def test_grade_a_by_units(self):
        assert DBOrganizer._compute_grade("Unknown Builder", 600) == "A"

    def test_grade_b_by_units(self):
        assert DBOrganizer._compute_grade("Unknown Builder", 200) == "B"

    def test_grade_c_low_units(self):
        assert DBOrganizer._compute_grade("Unknown Builder", 50) == "C"

    def test_grade_c_unknown_zero_units(self):
        assert DBOrganizer._compute_grade("Random Constructions", 0) == "C"

    def test_name_match_overrides_unit_count(self):
        # Brigade is Grade A even with 10 units (name match beats unit threshold)
        assert DBOrganizer._compute_grade("Brigade Projects", 10) == "A"

    def test_boundary_grade_a_min(self, monkeypatch):
        import config.settings as s
        monkeypatch.setattr(s, "GRADE_A_MIN_UNITS", 500)
        monkeypatch.setattr(s, "GRADE_B_MIN_UNITS", 100)
        assert DBOrganizer._compute_grade("Unknown", 500) == "A"
        assert DBOrganizer._compute_grade("Unknown", 499) == "B"

    def test_boundary_grade_b_min(self, monkeypatch):
        import config.settings as s
        monkeypatch.setattr(s, "GRADE_A_MIN_UNITS", 500)
        monkeypatch.setattr(s, "GRADE_B_MIN_UNITS", 100)
        assert DBOrganizer._compute_grade("Unknown", 100) == "B"
        assert DBOrganizer._compute_grade("Unknown", 99) == "C"
