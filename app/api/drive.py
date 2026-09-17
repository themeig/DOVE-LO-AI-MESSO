import html
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.models.database import get_db, GoogleDriveCredential
from app.services.drive_service import get_drive_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/drive", tags=["drive"])


class DriveSettingsUpdate(BaseModel):
    storage_mode: Literal["dual", "cloud_only"]


@router.get("/status")
def get_drive_status(db: Session = Depends(get_db)):
    """Restituisce lo stato attuale della connessione Google Drive."""
    drive_service = get_drive_service()
    cred = db.query(GoogleDriveCredential).first()
    mode = "real" if hasattr(drive_service, "client_id") and drive_service.client_id else "mock"

    return {
        "connected": bool(cred),
        "user_email": cred.user_email if cred else None,
        "storage_mode": cred.storage_mode if cred else "dual",
        "mode": mode,
    }


@router.get("/auth-url")
def get_auth_url(state: Optional[str] = None):
    """Genera l'URL di autorizzazione OAuth2 per Google Drive."""
    drive_service = get_drive_service()
    auth_url = drive_service.get_auth_url(state=state or "")
    return {"auth_url": auth_url}


@router.get("/callback")
def drive_oauth_callback(
    request: Request,
    code: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Gestisce il callback OAuth2 da Google, scambia il codice per i token e salva le credenziali."""
    if error:
        logger.warning(f"Errore ricevuto nel callback OAuth Google Drive: {error}")
        raise HTTPException(
            status_code=400,
            detail=f"Errore di autorizzazione Google Drive: {error}",
        )

    if not code:
        raise HTTPException(
            status_code=400,
            detail="Parametro 'code' mancante",
        )

    drive_service = get_drive_service()
    try:
        token_data = drive_service.exchange_code(code)
    except Exception as e:
        logger.error(f"Errore nello scambio del codice Google Drive: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Impossibile scambiare il codice di autorizzazione: {e}",
        )

    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    email = token_data.get("email")
    expires_in = token_data.get("expires_in")
    token_expiry = None
    if expires_in:
        token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    cred = db.query(GoogleDriveCredential).first()
    if cred:
        cred.access_token = access_token
        if refresh_token:
            cred.refresh_token = refresh_token
        if email:
            cred.user_email = email
        cred.token_expiry = token_expiry
        cred.updated_at = datetime.now(timezone.utc)
    else:
        cred = GoogleDriveCredential(
            user_email=email,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expiry=token_expiry,
            storage_mode="dual",
        )
        db.add(cred)

    db.commit()
    db.refresh(cred)

    accept_header = request.headers.get("accept", "")
    if "text/html" in accept_header:
        user_display = html.escape(cred.user_email or "Account Google")
        html_content = f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="utf-8">
    <title>Google Drive Connesso</title>
    <style>
        body {{
            font-family: system-ui, -apple-system, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
            background-color: #f8fafc;
            color: #1e293b;
        }}
        .card {{
            background: white;
            padding: 2rem 2.5rem;
            border-radius: 1rem;
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
            text-align: center;
            max-width: 420px;
        }}
        h2 {{ color: #075E54; margin-bottom: 0.5rem; }}
        p {{ font-size: 0.95rem; color: #475569; line-height: 1.5; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>Google Drive Connesso!</h2>
        <p>Account associato: <strong>{user_display}</strong></p>
        <p>Questa finestra si chiuder&agrave; automaticamente...</p>
    </div>
    <script>
        if (window.opener) {{
            window.opener.postMessage({{
                type: 'GOOGLE_DRIVE_AUTH_SUCCESS',
                email: '{cred.user_email or ""}'
            }}, '*');
            setTimeout(function() {{ window.close(); }}, 800);
        }} else {{
            setTimeout(function() {{ window.location.href = '/?drive_connected=true'; }}, 1200);
        }}
    </script>
</body>
</html>"""
        return HTMLResponse(content=html_content)

    return {"success": True, "email": cred.user_email}


@router.patch("/settings")
def update_drive_settings(
    body: DriveSettingsUpdate,
    db: Session = Depends(get_db),
):
    """Aggiorna le impostazioni della modalità di salvataggio ('dual' o 'cloud_only')."""
    cred = db.query(GoogleDriveCredential).first()
    if not cred:
        raise HTTPException(
            status_code=404,
            detail="Nessun account Google Drive connesso",
        )

    cred.storage_mode = body.storage_mode
    cred.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(cred)

    return {"success": True, "storage_mode": cred.storage_mode}


@router.post("/disconnect")
def disconnect_drive(db: Session = Depends(get_db)):
    """Disconnette l'account Google Drive eliminando le credenziali salvate."""
    db.query(GoogleDriveCredential).delete()
    db.commit()
    return {"success": True}
