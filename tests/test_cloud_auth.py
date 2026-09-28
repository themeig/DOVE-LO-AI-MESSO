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
