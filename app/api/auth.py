import math
from fastapi import APIRouter, HTTPException, Header, Request, Response, status
from pydantic import BaseModel
from typing import Optional
from app.services.crypto_service import get_vault_manager

router = APIRouter(prefix="/api/auth", tags=["auth"])

class LoginRequest(BaseModel):
    password: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

def get_client_ip(request: Request) -> str:
    """Estrae l'indirizzo IP del client gestendo header di inoltro o socket diretto."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"

@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    mgr = get_vault_manager()
    client_ip = get_client_ip(request)

    # 1. Verifica se l'IP è attualmente soggetto a blocco esponenziale da tentativi precedenti
    is_limited, remaining_wait = mgr.rate_limiter.is_rate_limited(client_ip)
    if is_limited:
        wait_seconds = max(1, int(math.ceil(remaining_wait)))
        response.headers["Retry-After"] = str(wait_seconds)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Troppi tentativi errati. Riprova tra {wait_seconds} secondi.",
            headers={"Retry-After": str(wait_seconds)}
        )

    # 2. Verifica la password
    success = mgr.unlock(payload.password)
    if not success:
        delay = mgr.rate_limiter.record_failure(client_ip)
        if delay > 0:
            wait_seconds = max(1, int(math.ceil(delay)))
            response.headers["Retry-After"] = str(wait_seconds)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Password non corretta. 3 tentativi esauriti. Riprova tra {wait_seconds} secondi.",
                headers={"Retry-After": str(wait_seconds)}
            )
        else:
            attempts_left = mgr.rate_limiter.get_remaining_attempts_in_block(client_ip)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Password non corretta. Hai ancora {attempts_left} tentativ{'o' if attempts_left == 1 else 'i'} prima del blocco temporaneo."
            )

    # 3. Successo: azzera il rate limiter per questo IP e genera token di sessione
    mgr.rate_limiter.record_success(client_ip)
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
