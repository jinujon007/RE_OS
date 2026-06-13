"""Tests for LA notification gazette parser (GATE-93, T-1150)."""
import pytest

pytestmark = pytest.mark.unit


def test_is_la_notification_detects_keywords():
    """_is_la_notification returns True for text with LA keywords."""
    from scrapers.la_gazette_parser import LAGazetteParser
    parser = LAGazetteParser()
    assert parser._is_la_notification("This is a land acquisition notification under Section 4(1)")
    assert parser._is_la_notification("KIADB preliminary notification for acquisition of land")
    assert parser._is_la_notification("BMRCL Final Notification for metro corridor land")
    assert not parser._is_la_notification("This is a routine revenue department circular")
    assert not parser._is_la_notification("")


def test_extract_notification_number():
    """Extract notification number from gazette text."""
    from scrapers.la_gazette_parser import LAGazetteParser
    parser = LAGazetteParser()
    text = """NOTIFICATION NO. KIADB/LAQ/CR/2026/1234
    Date: 15-01-2026
    Land acquisition for industrial park development"""
    notif = parser._extract_notification(text)
    assert "KIADB/LAQ/CR/2026/1234" in notif.notification_no or "KIADB" in notif.notification_no


def test_extract_authority_from_text():
    """Extract authority name from notification text."""
    from scrapers.la_gazette_parser import LAGazetteParser
    parser = LAGazetteParser()
    tests = [
        ("KIADB", "KIADB notifies acquisition of land"),
        ("BDA", "Bangalore Development Authority preliminary notification"),
        ("BMRCL", "BMRCL final notification for metro rail"),
    ]
    for expected, text in tests:
        notif = parser._extract_notification(text)
        assert notif.authority == expected, f"Failed for {expected}: got {notif.authority}"


def test_extract_villages_from_text():
    """Extract village names from notification text."""
    from scrapers.la_gazette_parser import LAGazetteParser
    parser = LAGazetteParser()
    text = "Notification for acquisition of land in villages of Venkatala, Shivanahalli and Thandavapura"
    notif = parser._extract_notification(text)
    assert "Venkatala" in notif.villages
    assert "Shivanahalli" in notif.villages


def test_extract_survey_numbers():
    """Extract survey numbers from notification text."""
    from scrapers.la_gazette_parser import LAGazetteParser
    parser = LAGazetteParser()
    text = "Survey numbers Sy No. 45/1, 45/2, 48/3 and S.No. 52/1A"
    notif = parser._extract_notification(text)
    assert len(notif.survey_nos) >= 2


def test_detect_preliminary_stage():
    """Detect preliminary notification stage."""
    from scrapers.la_gazette_parser import LAGazetteParser
    parser = LAGazetteParser()
    text = "Preliminary notification under Section 4(1) of the Land Acquisition Act"
    notif = parser._extract_notification(text)
    assert notif.stage == "preliminary"


def test_detect_final_stage():
    """Detect final notification stage."""
    from scrapers.la_gazette_parser import LAGazetteParser
    parser = LAGazetteParser()
    text = "Final declaration under Section 6(1) for acquisition of land"
    notif = parser._extract_notification(text)
    assert notif.stage == "final"


def test_to_event_creates_valid_dict():
    """to_event() produces dict with required fields for govt_policy_events."""
    from scrapers.la_gazette_parser import LANotification
    n = LANotification(
        notification_no="KIADB/2026/001",
        date_str="2026-01-15",
        authority="KIADB",
        purpose="Industrial park development",
        villages=["Venkatala", "Shivanahalli"],
        survey_nos=["45/1", "45/2"],
        stage="final",
    )
    event = n.to_event()
    assert event["category"] == "infrastructure"
    assert event["subcategory"] == "la_notification_final"
    assert event["impact_score"] == 8
    assert "Venkatala" in event["summary"]
    assert event["event_type"] == "la_notification"


def test_parse_text_with_full_notification():
    """parse_text extracts notification from multi-section text."""
    from scrapers.la_gazette_parser import LAGazetteParser
    parser = LAGazetteParser()
    text = """NOTIFICATION NO. KIADB/LAQ/2026/789
    Date: 15-03-2026
    Karnataka Industrial Areas Development Board preliminary notification
    under Section 4(1) for acquisition of land for Aerospace Park expansion
    in villages of Venkatala and Shivanahalli, Devanahalli Taluk.
    Survey numbers Sy No. 45/1, 45/2, 48/3."""
    notifs = parser.parse_text(text)
    assert len(notifs) >= 1
    n = notifs[0]
    assert n.authority == "KIADB"
    assert n.stage == "preliminary"
