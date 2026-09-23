# tests/test_drive_api.py
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import init_db

client = TestClient(app)

def setup_module():
    init_db()

def test_drive_status_disconnected():
    # Assicura pulizia preliminare
    client.post("/api/drive/disconnect")
    res = client.get("/api/drive/status")
    assert res.status_code == 200
    data = res.json()
    assert data["connected"] is False
    assert "storage_mode" in data
    assert data["mode"] in ("mock", "real")

def test_drive_auth_url():
    res = client.get("/api/drive/auth-url")
    assert res.status_code == 200
    assert "auth_url" in res.json()
    assert len(res.json()["auth_url"]) > 10

def test_drive_callback_and_disconnect():
    # Simulazione callback con codice
    res_cb = client.get("/api/drive/callback?code=test_auth_code")
    assert res_cb.status_code in (200, 307, 302)

    # Verifica status connesso
    res_status = client.get("/api/drive/status")
    assert res_status.status_code == 200
    assert res_status.json()["connected"] is True
    assert res_status.json()["user_email"] is not None

    # Modifica modalità cloud_only
    res_patch = client.patch("/api/drive/settings", json={"storage_mode": "cloud_only"})
    assert res_patch.status_code == 200
    assert res_patch.json()["storage_mode"] == "cloud_only"

    # Modifica modalità local_only
    res_patch_local = client.patch("/api/drive/settings", json={"storage_mode": "local_only"})
    assert res_patch_local.status_code == 200
    assert res_patch_local.json()["storage_mode"] == "local_only"

    # Verifica recupero status con local_only
    res_status_local = client.get("/api/drive/status")
    assert res_status_local.status_code == 200
    assert res_status_local.json()["storage_mode"] == "local_only"

    # Disconnessione
    res_disc = client.post("/api/drive/disconnect")
    assert res_disc.status_code == 200
    assert res_disc.json()["success"] is True

    # Verifica status disconnesso
    res_after = client.get("/api/drive/status")
    assert res_after.json()["connected"] is False

def test_drive_callback_missing_code():
    res = client.get("/api/drive/callback")
    assert res.status_code in (400, 422)

def test_drive_settings_invalid_mode():
    # Riconnetti prima
    client.get("/api/drive/callback?code=test_auth_code")
    res = client.patch("/api/drive/settings", json={"storage_mode": "invalid_mode"})
    assert res.status_code in (400, 422)
    # Pulisci
    client.post("/api/drive/disconnect")

def test_drive_settings_not_connected():
    client.post("/api/drive/disconnect")
    res = client.patch("/api/drive/settings", json={"storage_mode": "cloud_only"})
    assert res.status_code == 404

def test_drive_callback_html_accept():
    res_cb = client.get(
        "/api/drive/callback?code=test_auth_code",
        headers={"Accept": "text/html"}
    )
    assert res_cb.status_code == 200
    assert "text/html" in res_cb.headers.get("content-type", "")
    assert "GOOGLE_DRIVE" in res_cb.text
    # Pulisci alla fine
    client.post("/api/drive/disconnect")
