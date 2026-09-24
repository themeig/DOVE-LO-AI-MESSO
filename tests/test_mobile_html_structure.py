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
