import pytest
from utils.validator import validate_rera_records, _check_record


@pytest.fixture
def sample_records():
    return [
        {
            "rera_number": "PRM/KA/12345",
            "project_name": "Sunrise Apartments",
            "developer_name": "Acme Developers",
            "total_units": 100,
        },
        {
            "rera_number": "INVALID/123",
            "project_name": "",
            "developer_name": "   ",
            "total_units": -5,
        },
        "not a dict",
    ]


def test_validate_rera_records_counts(sample_records):
    valid, invalid, report = validate_rera_records(sample_records)
    assert len(valid) == 1
    assert len(invalid) == 2
    assert report["total"] == 3
    assert report["valid"] == 1
    assert report["invalid"] == 2
    error_messages = " ".join(report["error_summary"])
    assert "bad rera_number format" in error_messages
    assert "empty or placeholder project_name" in error_messages
    assert "empty developer_name" in error_messages
    assert "negative total_units" in error_messages
    assert "not a dict" in error_messages


def test_validate_empty_list():
    valid, invalid, report = validate_rera_records([])
    assert valid == []
    assert invalid == []
    assert report["total"] == 0
    assert report["valid"] == 0
    assert report["invalid"] == 0


def test_valid_rera_number_loose_pattern():
    record = {
        "rera_number": "PRM/00001",
        "project_name": "Sunrise Villas",
        "developer_name": "Builder Co",
        "total_units": 50,
    }
    errors = _check_record(record)
    assert not any("rera_number" in e for e in errors), f"Unexpected RERA error: {errors}"


def test_check_record_individual_errors():
    bad_record = {
        "rera_number": "XYZ/123",
        "project_name": "N/A",
        "developer_name": "unknown developer",
        "total_units": "ten",
    }
    errors = _check_record(bad_record)
    assert "bad rera_number format: 'XYZ/123'" in errors
    assert "empty or placeholder project_name" in errors
    assert "empty developer_name" in errors
    assert "non-integer total_units: 'ten'" in errors

    good_record = {
        "rera_number": "PRM/KA/98765",
        "project_name": "Greenfield Villas",
        "developer_name": "Builder Co",
        "total_units": 50,
    }
    assert _check_record(good_record) == []


def test_unicode_project_name_passes():
    record = {
        "rera_number": "PRM/KA/12300",
        "project_name": "श्री गणेश अपार्टमेंट्स",
        "developer_name": "Shri Builders",
        "total_units": 24,
    }
    valid, invalid, report = validate_rera_records([record])
    assert len(valid) == 1
    assert len(invalid) == 0


# C0 — data provenance: seed_estimated records must be visibly marked
def test_seed_estimated_gets_estimated_prefix():
    record = {
        "rera_number": "PRM/KA/00001",
        "project_name": "Test Project",
        "developer_name": "Builder Co",
        "total_units": 50,
        "data_source": "seed_estimated",
    }
    valid, invalid, report = validate_rera_records([record])
    assert len(valid) == 1, "seed_estimated record should pass validation"
    assert valid[0]["project_name"].startswith("[ESTIMATED]"), (
        "seed_estimated records must have [ESTIMATED] prefix so fallback data "
        "is never silently treated as real market data"
    )


def test_non_seed_estimated_not_prefixed():
    record = {
        "rera_number": "PRM/KA/00002",
        "project_name": "Real Project",
        "developer_name": "Builder Co",
        "total_units": 100,
        "data_source": "rera_portal",
    }
    valid, invalid, report = validate_rera_records([record])
    assert len(valid) == 1
    assert not valid[0]["project_name"].startswith("[ESTIMATED]")
