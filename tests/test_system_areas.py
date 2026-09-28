"""
Test di verifica per la suddivisione delle impostazioni di Sistema per aree tematiche
(Chat & AI, Google Drive, Google Calendar, Cartelle PC, Sicurezza & Backup),
per la pulizia UI (indicatori cloud, logo caveau) e per la navigazione mobile
(gestione tasto indietro con ritorno a selezione chat, e gesture swipe cambio sezioni).
"""
from pathlib import Path
from app.version import APP_VERSION


def test_app_version():
    assert APP_VERSION == "2.10.18"


def test_index_html_has_system_areas():
    index_path = Path("index.html")
    assert index_path.exists()
    content = index_path.read_text(encoding="utf-8")

    # Verifica presenza menu sezioni stile smartphone
    assert 'id="systemSectionsMenu"' in content
    assert 'id="systemSectionDetailView"' in content
    assert 'openSystemSection' in content
    assert 'closeSystemSection' in content

    # Verifica rimozione sottotitoli dalle singole impostazioni
    assert 'id="menuStatus_chat"' not in content
    assert 'id="menuStatus_drive"' not in content
    assert 'id="menuStatus_calendar"' not in content
    assert 'id="menuStatus_pc"' not in content
    assert 'id="menuStatus_security"' not in content

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

    # ACQUISISCI ATTO e + OGGETTO rimossi dalla dashboard
    assert 'ACQUISISCI ATTO' not in content
    assert '+ OGGETTO' not in content

    # Logo Caveau ripristinato in alto a sinistra nella sidebar
    assert 'fa-solid fa-vault' in content

    # Avatar della chat visibile nell'header chat
    assert 'id="activeThreadAvatar"' in content

    # Indicatori cloud Drive e Calendar nel container sidebar a destra, rimossi vicino al nome chat
    assert 'chatHeaderDriveStatus' not in content
    assert 'chatHeaderCalendarStatus' not in content
    assert 'sidebarHeaderDriveStatus' in content
    assert 'sidebarHeaderCalendarStatus' in content


def test_mobile_html_has_system_areas():
    mobile_path = Path("mobile.html")
    assert mobile_path.exists()
    content = mobile_path.read_text(encoding="utf-8")

    # Verifica presenza menu sezioni stile smartphone in mobile
    assert 'id="systemSectionsMenu"' in content
    assert 'id="systemSectionDetailView"' in content
    assert 'openSystemSection' in content
    assert 'closeSystemSection' in content

    # Verifica rimozione sottotitoli dalle singole impostazioni mobile
    assert 'id="menuStatus_chat"' not in content
    assert 'id="menuStatus_drive"' not in content
    assert 'id="menuStatus_calendar"' not in content
    assert 'id="menuStatus_security"' not in content

    # Verifica presenza selettore tabs in mobile
    assert 'id="systemAreaTabs"' in content
    assert 'btnSystemArea_all' in content
    assert 'btnSystemArea_chat' in content
    assert 'btnSystemArea_drive' in content
    assert 'btnSystemArea_calendar' in content
    assert 'btnSystemArea_security' in content

    # Sezione Cartelle PC rimossa da mobile
    assert 'btnSystemArea_pc' not in content
    assert 'id="settingsArea_pc"' not in content

    # ACQUISISCI ATTO e + OGGETTO rimossi dalla dashboard mobile
    assert 'ACQUISISCI ATTO' not in content
    assert '+ OGGETTO' not in content

    # Logo Caveau ripristinato in alto a sinistra nella sidebar mobile
    assert 'fa-solid fa-vault' in content

    # Avatar della chat visibile nell'header chat mobile
    assert 'id="activeThreadAvatar"' in content

    # Indicatori cloud Drive e Calendar nel container sidebar a destra, rimossi vicino al nome chat mobile
    assert 'chatHeaderDriveStatus' not in content
    assert 'chatHeaderCalendarStatus' not in content
    assert 'sidebarHeaderDriveStatus' in content
    assert 'sidebarHeaderCalendarStatus' in content


def test_app_bundle_has_system_area_and_mobile_gestures():
    bundle_path = Path("static/js/app-bundle.js")
    assert bundle_path.exists()
    content = bundle_path.read_text(encoding="utf-8")

    assert "function setSystemArea(area)" in content
    assert "window.setSystemArea = setSystemArea;" in content
    assert "function openSystemSection(area)" in content
    assert "window.openSystemSection = openSystemSection;" in content
    assert "function closeSystemSection()" in content
    assert "window.closeSystemSection = closeSystemSection;" in content
    assert "function updateSystemMenuStatusBadges()" in content
    assert "window.updateSystemMenuStatusBadges = updateSystemMenuStatusBadges;" in content
    assert "function loadCalendarStatus()" in content
    assert "window.loadCalendarStatus = loadCalendarStatus;" in content
    assert "function updateHeaderCloudIndicators(driveConnected, calendarConnected)" in content
    assert "window.updateHeaderCloudIndicators = updateHeaderCloudIndicators;" in content

    # Verifica gestione tasto indietro nativo e gesture swipe interattivo 1:1 per cambio sezioni
    assert "function handleNativeBackPress()" in content
    assert "window.handleNativeBackPress = handleNativeBackPress;" in content
    assert "function initMobileSwipeGestures()" in content
    assert "window.initMobileSwipeGestures = initMobileSwipeGestures;" in content
    assert "translate3d" in content
    assert "activeFromEl.style.transform" in content
    assert "activeToEl.style.transform" in content



def test_android_main_activity_delegates_back_press():
    activity_path = Path("android/app/src/main/java/com/doveloaimesso/app/MainActivity.java")
    assert activity_path.exists()
    content = activity_path.read_text(encoding="utf-8")

    assert "window.handleNativeBackPress" in content
    assert "Premi di nuovo per uscire da Dove lo AI messo" in content
