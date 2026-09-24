# tests/test_mobile_scanner_module.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_mobile_scanner_js_asset_exists():
    res = client.get("/static/js/mobile-scanner.js")
    assert res.status_code == 200
    assert "MobileScanner" in res.text
    assert "applyPerspectiveWarp" in res.text
    assert "getUserMedia" in res.text
    assert "requestMobilePermission" in res.text
    assert "magic_color" in res.text
