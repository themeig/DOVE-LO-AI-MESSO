# tests/test_mobile_html_structure.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_mobile_html_contains_critical_components():
    res = client.get("/m")
    assert res.status_code == 200
    html = res.text
    # Meta tag per gestione tastiera Android
    assert "interactive-widget=resizes-content" in html
    # Inclusione dello scanner mobile
    assert "mobile-scanner.js" in html
    # Modale scanner
    assert "mobileScannerModal" in html
    # Tasto fotocamera/scanner
    assert "btnOpenScanner" in html
    # Tasto microfono vocale Whisper
    assert "micButton" in html or "btnVoiceRecord" in html
    # Link per tornare alla versione desktop
    assert "desktop=true" in html or "prefer_desktop" in html

def test_system_view_and_chat_contain_environment_badge():
    # Verifica che sia la vista mobile sia la vista desktop abbiano il badge di rilevamento ambiente
    for endpoint in ["/", "/m"]:
        res = client.get(endpoint, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, follow_redirects=True)
        assert res.status_code == 200
        html = res.text
        # Badge di rilevamento presente nell'header e nel sistema
        assert "env-device-badge" in html
        assert "systemEnvBadge" in html
        assert "headerEnvBadge" in html
        assert "systemMainEnvBadge" in html
        assert "SISTEMA & CONFIGURAZIONE" in html
        assert "syncDeviceEnvironment" in html or "app-bundle.js" in html
