"""
Test suite per la verifica dei token Supabase JWT e dependency di autenticazione.
"""
import time
import pytest
import jwt
from fastapi import HTTPException
from app.services.auth_service import verify_supabase_jwt, get_current_user


def test_verify_valid_jwt():
    secret = "test-secret-key-32-bytes-minimum!!"
    payload = {"sub": "user-uuid-123", "email": "test@example.com", "role": "authenticated"}
    token = jwt.encode(payload, secret, algorithm="HS256")

    user_data = verify_supabase_jwt(token, secret=secret)
    assert user_data["sub"] == "user-uuid-123"
    assert user_data["email"] == "test@example.com"


def test_verify_invalid_jwt():
    with pytest.raises(HTTPException) as exc:
        verify_supabase_jwt("invalid-token-string", secret="secret")
    assert exc.value.status_code == 401


def test_verify_expired_jwt():
    secret = "test-secret-key-32-bytes-minimum!!"
    payload = {"sub": "user-uuid-123", "email": "test@example.com", "exp": time.time() - 3600}
    token = jwt.encode(payload, secret, algorithm="HS256")
    with pytest.raises(HTTPException) as exc:
        verify_supabase_jwt(token, secret=secret)
    assert exc.value.status_code == 401
    assert "scaduto" in exc.value.detail.lower() or "expired" in exc.value.detail.lower()


def test_get_current_user_dev_fallback(monkeypatch):
    # In modalità locale/dev senza secret impostato e senza header, fornisce utente fallback per compatibilità
    class SettingsMock:
        SUPABASE_JWT_SECRET = ""
        DEBUG = True
    monkeypatch.setattr("app.services.auth_service.get_settings", lambda: SettingsMock())
    user = get_current_user(credentials=None)
    assert user["sub"] == "local-dev-user"
    assert "local" in user["email"]


def test_cloud_signup_login_and_me():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models.database import init_db

    init_db()
    client = TestClient(app)

    # 1. Registrazione Cloud / Locale
    signup_res = client.post("/api/auth/cloud/signup", json={
        "email": "mario.rossi@test.it",
        "password": "PasswordSicura123!",
        "full_name": "Mario Rossi"
    })
    assert signup_res.status_code in [200, 201]
    signup_data = signup_res.json()
    assert "access_token" in signup_data
    token = signup_data["access_token"]
    assert signup_data["user"]["email"] == "mario.rossi@test.it"
    assert signup_data["user"]["full_name"] == "Mario Rossi"

    # 2. Verifica profilo corrente /me
    me_res = client.get("/api/auth/cloud/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["email"] == "mario.rossi@test.it"
    assert me_data["full_name"] == "Mario Rossi"

    # 3. Login con credenziali
    login_res = client.post("/api/auth/cloud/login", json={
        "email": "mario.rossi@test.it",
        "password": "PasswordSicura123!"
    })
    assert login_res.status_code == 200
    assert "access_token" in login_res.json()

