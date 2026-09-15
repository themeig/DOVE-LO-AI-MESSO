from fastapi import APIRouter, HTTPException, Header, status
from pydantic import BaseModel
from typing import Optional
from app.services.crypto_service import get_vault_manager

router = APIRouter(prefix="/api/auth", tags=["auth"])

class LoginRequest(BaseModel):
    password: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

@router.post("/login")
def login(payload: LoginRequest):
    mgr = get_vault_manager()
    success = mgr.unlock(payload.password)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Password non corretta. Riprova."
        )
    token = mgr.create_session_token()
    return {
        "success": True,
        "token": token,
        "expires_in": 86400,
        "message": "Caveau sbloccato con successo."
    }

@router.get("/status")
def get_auth_status(x_vault_token: Optional[str] = Header(None)):
    mgr = get_vault_manager()
    unlocked = mgr.is_unlocked()
    return {
        "unlocked": unlocked,
        "has_token": bool(x_vault_token and mgr.validate_token(x_vault_token)) if unlocked else False
    }

@router.post("/lock")
def lock_vault():
    mgr = get_vault_manager()
    mgr.lock()
    return {
        "success": True,
        "message": "Caveau bloccato."
    }

@router.post("/change-password")
def change_password(payload: ChangePasswordRequest):
    if len(payload.new_password.strip()) < 4:
        raise HTTPException(status_code=400, detail="La nuova password deve contenere almeno 4 caratteri.")
    mgr = get_vault_manager()
    success = mgr.change_password(payload.old_password, payload.new_password)
    if not success:
        raise HTTPException(status_code=401, detail="Password attuale non corretta.")
    return {
        "success": True,
        "message": "Password del caveau aggiornata con successo."
    }
