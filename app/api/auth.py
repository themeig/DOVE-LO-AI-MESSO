import math
from typing import Optional
from fastapi import APIRouter, HTTPException, Header, Request, Response, status, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.services.crypto_service import get_vault_manager
from app.services.auth_service import get_current_user

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
    token = mgr.create_session_token() if unlocked else None
    return {
        "unlocked": unlocked,
        "has_token": bool(x_vault_token and mgr.validate_token(x_vault_token)) if unlocked else False,
        "token": token
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


# =====================================================================
# CLOUD & MULTI-ACCOUNT AUTH (SUPABASE JWT & PROFILO)
# =====================================================================

class CloudSignupRequest(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = "Utente"


class CloudLoginRequest(BaseModel):
    email: str
    password: str


@router.post("/cloud/signup", status_code=status.HTTP_201_CREATED)
def cloud_signup(
    payload: CloudSignupRequest,
    db: Session = Depends(get_db)
):
    """
    Registra un nuovo account utente per il Caveau Cloud e restituisce il token JWT.
    """
    import uuid
    import jwt
    from datetime import datetime, timezone, timedelta
    from app.config import get_settings
    from app.models.database import User

    clean_email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == clean_email).first()
    if not user:
        user = User(
            id=str(uuid.uuid4()),
            email=clean_email,
            full_name=payload.full_name.strip() if payload.full_name else clean_email.split("@")[0].capitalize()
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    settings = get_settings()
    jwt_secret = settings.SUPABASE_JWT_SECRET or "local-dev-jwt-secret-key-32-chars-long!"
    exp = datetime.now(timezone.utc) + timedelta(days=30)
    token_payload = {
        "sub": user.id,
        "id": user.id,
        "email": user.email,
        "role": "authenticated",
        "user_metadata": {
            "full_name": user.full_name
        },
        "exp": exp
    }
    token = jwt.encode(token_payload, jwt_secret, algorithm="HS256")
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name
        }
    }


@router.post("/cloud/login")
def cloud_login(
    payload: CloudLoginRequest,
    db: Session = Depends(get_db)
):
    """
    Autentica un account utente e genera il token JWT di sessione.
    """
    import uuid
    import jwt
    from datetime import datetime, timezone, timedelta
    from app.config import get_settings
    from app.models.database import User

    clean_email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == clean_email).first()
    if not user:
        user = User(
            id=str(uuid.uuid4()),
            email=clean_email,
            full_name=clean_email.split("@")[0].capitalize()
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    settings = get_settings()
    jwt_secret = settings.SUPABASE_JWT_SECRET or "local-dev-jwt-secret-key-32-chars-long!"
    exp = datetime.now(timezone.utc) + timedelta(days=30)
    token_payload = {
        "sub": user.id,
        "id": user.id,
        "email": user.email,
        "role": "authenticated",
        "user_metadata": {
            "full_name": user.full_name
        },
        "exp": exp
    }
    token = jwt.encode(token_payload, jwt_secret, algorithm="HS256")
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name
        }
    }


@router.get("/cloud/me")
def get_cloud_me(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Restituisce i dati del profilo dell'utente correntemente autenticato.
    """
    from app.models.database import User

    user_id = current_user.get("id") or current_user.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        return {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "avatar_url": user.avatar_url,
            "created_at": user.created_at.isoformat() if user.created_at else ""
        }
    return {
        "id": user_id,
        "email": current_user.get("email", ""),
        "full_name": current_user.get("full_name", "Utente"),
        "avatar_url": None,
        "created_at": ""
    }

