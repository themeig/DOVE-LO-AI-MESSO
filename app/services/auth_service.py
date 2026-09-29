"""
Modulo di autenticazione e verifica token JWT Supabase.
Gestisce la validazione crittografica della firma HMAC/HS256 dei token di sessione,
estraendo l'identità dell'utente (UUID, email, ruolo) per proteggere le API dei gruppi.
"""
from typing import Optional, Dict, Any
import jwt
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import get_settings

security = HTTPBearer(auto_error=False)


def verify_supabase_jwt(token: str, secret: Optional[str] = None) -> Dict[str, Any]:
    """
    Verifica e decodifica un token JWT emesso da Supabase Auth.
    Lancia HTTPException 401 in caso di firma non valida o token scaduto.
    """
    signing_secret = secret if secret is not None else (get_settings().SUPABASE_JWT_SECRET or "local-dev-jwt-secret-key-32-chars-long!")

    try:
        # Supabase emette di default token HS256 firmati con JWT secret
        payload = jwt.decode(
            token,
            signing_secret,
            algorithms=["HS256"],
            options={"verify_exp": True}
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token di autenticazione scaduto. Ricollegarsi."
        )
    except jwt.InvalidTokenError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token JWT non valido: {str(err)}"
        )


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Dict[str, Any]:
    """
    FastAPI Dependency che estrae e valida l'utente autenticato dal Bearer token.
    Se il server è in modalità locale senza SUPABASE_JWT_SECRET configurato,
    restituisce un profilo utente locale per garantire la retrocompatibilità totale.
    """
    settings = get_settings()

    if credentials and credentials.credentials:
        payload = verify_supabase_jwt(credentials.credentials)
        user_id = payload.get("sub") or payload.get("id")
        email = payload.get("email") or ""
        user_metadata = payload.get("user_metadata", {})
        full_name = user_metadata.get("full_name") or payload.get("name") or email.split("@")[0] or "Utente"

        return {
            "sub": user_id,
            "id": user_id,
            "email": email,
            "full_name": full_name,
            "role": payload.get("role", "authenticated")
        }

    # Se non c'è header Bearer ma siamo in ambiente locale/dev senza secret impostato:
    if not settings.SUPABASE_JWT_SECRET:
        return {
            "sub": "local-dev-user",
            "id": "local-dev-user",
            "email": "local@doveloaimesso.internal",
            "full_name": "Utente Caveau Locale",
            "role": "admin"
        }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Autenticazione richiesta. Nessun token Bearer fornito."
    )


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[Dict[str, Any]]:
    """
    Restituisce l'utente autenticato se presente un token valido, altrimenti None senza lanciare 401.
    """
    if not credentials or not credentials.credentials:
        return None
    try:
        return get_current_user(credentials)
    except Exception:
        return None
