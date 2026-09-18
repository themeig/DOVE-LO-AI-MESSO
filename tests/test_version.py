from fastapi.testclient import TestClient
from app.main import app
from app.version import APP_VERSION, __version__
from app.config import get_settings

client = TestClient(app)

def test_version_constants():
    assert APP_VERSION is not None
    assert isinstance(APP_VERSION, str)
    assert len(APP_VERSION.split(".")) >= 3
    assert __version__ == APP_VERSION

def test_api_version_endpoint():
    res = client.get("/api/version")
    assert res.status_code == 200
    data = res.json()
    assert "version" in data
    assert data["version"] == APP_VERSION
    assert "app_name" in data

def test_fastapi_app_version():
    assert app.version == APP_VERSION

def test_dashboard_feed_includes_version():
    res = client.get("/api/dashboard")
    assert res.status_code == 200
    data = res.json()
    assert "app_version" in data
    assert data["app_version"] == APP_VERSION
