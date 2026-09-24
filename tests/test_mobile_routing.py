# tests/test_mobile_routing.py
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import init_db

client = TestClient(app)

def setup_module():
    init_db()

def test_get_mobile_endpoint_returns_mobile_html():
    res = client.get("/m")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")

def test_desktop_user_agent_serves_index_html():
    desktop_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    res = client.get("/", headers={"User-Agent": desktop_ua}, follow_redirects=False)
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")

def test_mobile_user_agent_redirects_to_m():
    mobile_ua = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    res = client.get("/", headers={"User-Agent": mobile_ua}, follow_redirects=False)
    assert res.status_code in (302, 307)
    assert res.headers["location"] == "/m"

def test_mobile_user_agent_with_desktop_query_bypasses_redirect():
    mobile_ua = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    res = client.get("/?desktop=true", headers={"User-Agent": mobile_ua}, follow_redirects=False)
    assert res.status_code == 200
