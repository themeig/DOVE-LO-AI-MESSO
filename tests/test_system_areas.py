"""
Test di verifica per la suddivisione delle impostazioni di Sistema per aree tematiche
(Chat & AI, Google Drive, Google Calendar, Cartelle PC, Sicurezza & Backup).
"""
from pathlib import Path
from app.version import APP_VERSION


def test_app_version_is_2_10_4():
    assert APP_VERSION == "2.10.4"


def test_index_html_has_system_areas():
    index_path = Path("index.html")
    assert index_path.exists()
    content = index_path.read_text(encoding="utf-8")

    # Verifica presenza selettore tabs
    assert 'id="systemAreaTabs"' in content
    assert 'btnSystemArea_all' in content
    assert 'btnSystemArea_chat' in content
    assert 'btnSystemArea_drive' in content
    assert 'btnSystemArea_calendar' in content
    assert 'btnSystemArea_pc' in content
    assert 'btnSystemArea_security' in content

    # Verifica presenza sezioni aree tematiche
    assert 'id="settingsArea_chat"' in content
    assert 'id="settingsArea_drive"' in content
    assert 'id="settingsArea_calendar"' in content
    assert 'id="settingsArea_pc"' in content
    assert 'id="settingsArea_security"' in content

    # Verifica elementi chiave Google Calendar
    assert 'systemCalendarStatusBadge' in content
    assert 'btnSyncGoogleCalendarSettings' in content


def test_mobile_html_has_system_areas():
    mobile_path = Path("mobile.html")
    assert mobile_path.exists()
    content = mobile_path.read_text(encoding="utf-8")

    # Verifica presenza selettore tabs in mobile
    assert 'id="systemAreaTabs"' in content
    assert 'btnSystemArea_all' in content
    assert 'btnSystemArea_chat' in content
    assert 'btnSystemArea_drive' in content
    assert 'btnSystemArea_calendar' in content
    assert 'btnSystemArea_pc' in content
    assert 'btnSystemArea_security' in content

    # Verifica presenza sezioni aree tematiche in mobile
    assert 'id="settingsArea_chat"' in content
    assert 'id="settingsArea_drive"' in content
    assert 'id="settingsArea_calendar"' in content
    assert 'id="settingsArea_pc"' in content
    assert 'id="settingsArea_security"' in content


def test_app_bundle_has_system_area_controller():
    bundle_path = Path("static/js/app-bundle.js")
    assert bundle_path.exists()
    content = bundle_path.read_text(encoding="utf-8")

    assert "function setSystemArea(area)" in content
    assert "window.setSystemArea = setSystemArea;" in content
    assert "function loadCalendarStatus()" in content
    assert "window.loadCalendarStatus = loadCalendarStatus;" in content
