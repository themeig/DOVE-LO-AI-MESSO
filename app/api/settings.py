import logging
import math
import httpx
from pathlib import Path
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.database import (
    get_db, get_app_setting, set_app_setting,
    Document, PhysicalItem, ChatMessage, ChatThread,
    WatchedFolder, PendingFileProposal, UIEvent, GoogleDriveCredential
)
from app.models.schemas import WipeDatabaseRequest, WipeDatabaseResponse
from app.services.crypto_service import get_vault_manager
from app.services.drive_service import get_drive_service
from app.api.auth import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

AVAILABLE_MODELS = [
    {
        "id": "auto",
        "name": "Router Intelligente Dinamico",
        "tag": "🎯 Consigliato",
        "tier": "auto",
        "is_free": False,
        "is_thinking": True,
        "cost_info": "Ottimizzato (Lite per salvare, Pro Thinking per cercare)",
        "features": "Seleziona dinamicamente il modello migliore: usa Gemini 2.5 Flash Lite per salvare file, foto e posizioni in pochi ms, e attiva Gemini 2.5 Pro (Thinking) per ricerche, scadenze, calcoli e spiegazioni complesse."
    },
    {
        "id": "google/gemini-2.5-flash-lite",
        "name": "Google Gemini 2.5 Flash Lite",
        "tag": "⚡ Veloce & Leggero",
        "tier": "paid",
        "is_free": False,
        "is_thinking": False,
        "cost_info": "~0,0001 € / msg (.10 / 1M in, .40 / 1M out)",
        "features": "Visione multimodale ad alta precisione + Tool Calling ultra-rapido."
    },
    {
        "id": "google/gemini-2.5-pro",
        "name": "Google Gemini 2.5 Pro (Thinking)",
        "tag": "🧠 Modello che Pensa",
        "tier": "paid",
        "is_free": False,
        "is_thinking": True,
        "cost_info": "Ragionamento profondo (~$1.25 / 1M in, $5.00 / 1M out)",
        "features": "Thinking Process nativo con ragionamento logico profondo prima di rispondere, visione e tool calling."
    },
    {
        "id": "nex-agi/nex-n2.5-pro:free",
        "name": "Nex-AGI Nex-N2.5-Pro (Free)",
        "tag": "🆓 100% Gratuito",
        "tier": "free",
        "is_free": True,
        "is_thinking": False,
        "cost_info": "0,00 € (Nessun addebito)",
        "features": "Modello open gratuito con supporto a visione e tool calling."
    }
]

class ModelUpdateRequest(BaseModel):
    model_id: str

@router.get("/ai-model")
def get_ai_model_setting(db: Session = Depends(get_db)) -> Dict[str, Any]:
    default_model = get_settings().OPENROUTER_MODEL
    current_model = get_app_setting(db, "ai_model", default=default_model)
    
    active_info = next((m for m in AVAILABLE_MODELS if m["id"] == current_model), None)
    if not active_info:
        active_info = {
            "id": current_model,
            "name": current_model,
            "tag": "Personalizzato",
            "tier": "free" if ":free" in current_model else "paid",
            "is_free": ":free" in current_model,
            "cost_info": "0,00 €" if ":free" in current_model else "Pay-as-you-go",
            "features": "Modello configurato manualmente"
        }
        
    return {
        "current_model": current_model,
        "current_info": active_info,
        "is_free": active_info["is_free"],
        "available_models": AVAILABLE_MODELS
    }

@router.post("/ai-model")
def update_ai_model_setting(payload: ModelUpdateRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    valid_ids = [m["id"] for m in AVAILABLE_MODELS]
    if payload.model_id not in valid_ids and not payload.model_id.endswith(":free"):
        raise HTTPException(status_code=400, detail="Modello non supportato")

    set_app_setting(db, "ai_model", payload.model_id)
    logger.info(f"Modello AI aggiornato a: {payload.model_id}")
    
    return get_ai_model_setting(db)


@router.post("/wipe-database", response_model=WipeDatabaseResponse)
def wipe_database(
    payload: WipeDatabaseRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """
    Elimina in modo irreversibile tutti i dati del database SQLite (documenti, scadenze,
    oggetti, foto, chat e cartelle monitorate), rimuove i file locali cifrati e,
    se richiesto dall'utente, cancella i file remoti e la cartella radice da Google Drive.
    Richiede la password master del Caveau con protezione rate limiting anti-bruteforce.
    """
    mgr = get_vault_manager()
    client_ip = get_client_ip(request)

    # 1. Verifica protezione anti-bruteforce
    is_limited, remaining_wait = mgr.rate_limiter.is_rate_limited(client_ip)
    if is_limited:
        wait_seconds = max(1, int(math.ceil(remaining_wait)))
        response.headers["Retry-After"] = str(wait_seconds)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Troppi tentativi errati. Riprova tra {wait_seconds} secondi.",
            headers={"Retry-After": str(wait_seconds)}
        )

    # 2. Verifica password del Caveau
    if not mgr.unlock(payload.password):
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

    mgr.rate_limiter.record_success(client_ip)

    # 3. Gestione opzionale Google Drive
    drive_deleted = False
    if payload.delete_drive:
        try:
            active_cred = db.query(GoogleDriveCredential).first()
            if active_cred and active_cred.access_token:
                drive_service = get_drive_service()
                drive_service.delete_vault_root_folder(active_cred.access_token)
                drive_deleted = True
            db.query(GoogleDriveCredential).delete()
        except Exception as e:
            logger.warning(f"Errore durante l'eliminazione da Google Drive: {e}")

    # 4. Eliminazione file fisici crittografati in uploads e item_photos
    settings = get_settings()
    uploads_dir = settings.STORAGE_DIR
    if uploads_dir.exists():
        for p in uploads_dir.iterdir():
            if p.is_file():
                try:
                    p.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"Impossibile eliminare {p}: {e}")

    item_photos_dir = settings.BASE_DIR / "storage" / "item_photos"
    if item_photos_dir.exists():
        for p in item_photos_dir.iterdir():
            if p.is_file():
                try:
                    p.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"Impossibile eliminare {p}: {e}")

    # 5. Pulizia tabelle SQLite
    doc_count = db.query(Document).count()
    item_count = db.query(PhysicalItem).count()
    msg_count = db.query(ChatMessage).count()
    folder_count = db.query(WatchedFolder).count()

    db.query(Document).delete()
    db.query(PhysicalItem).delete()
    db.query(ChatMessage).delete()
    db.query(WatchedFolder).delete()
    db.query(PendingFileProposal).delete()
    db.query(UIEvent).delete()

    # Rimuovi eventuali thread personalizzati mantenendo i default
    db.query(ChatThread).filter(~ChatThread.id.in_(["general", "famiglia", "lavoro", "casa"])).delete(synchronize_session=False)

    # 6. Ricrea messaggio iniziale nel thread generale
    welcome_msg = ChatMessage(
        thread_id="general",
        sender="assistant",
        message_type="text",
        content="👋 Ciao! Il database è stato completamente azzerato e il tuo caveau è pronto per essere utilizzato."
    )
    db.add(welcome_msg)
    db.commit()

    logger.info(f"Database azzerato con successo: {doc_count} doc, {item_count} oggetti, {msg_count} msg, drive_deleted={drive_deleted}")

    return WipeDatabaseResponse(
        success=True,
        message="Database e file del Caveau eliminati con successo.",
        deleted_documents=doc_count,
        deleted_items=item_count,
        deleted_messages=msg_count,
        deleted_folders=folder_count,
        drive_deleted=drive_deleted
    )


@router.get("/openrouter-credits")
def get_openrouter_credits(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Recupera i dati in tempo reale sul saldo crediti e consumi dell'account OpenRouter tramite API ufficiale.
    Restituisce quanti crediti rimangono (saldo residuo), quanti crediti ci sono in totale (acquistati/depositati),
    e il dettaglio dei consumi dell'account e della specifica chiave API.
    """
    key = get_app_setting(db, "openrouter_api_key") or get_settings().OPENROUTER_API_KEY or ""
    key = key.strip()

    if not key:
        return {
            "connected": False,
            "is_configured": False,
            "has_key": False,
            "message": "Nessuna chiave API OpenRouter configurata nel sistema.",
            "total_credits": 0.0,
            "total_usage": 0.0,
            "remaining_credits": 0.0,
            "percentage_remaining": 0.0
        }

    headers = {
        "Authorization": f"Bearer {key}",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "Dove lo AI messo"
    }

    try:
        total_credits = 0.0
        total_usage = 0.0
        r_credits = httpx.get("https://openrouter.ai/api/v1/credits", headers=headers, timeout=10.0)
        if r_credits.status_code == 200:
            c_data = r_credits.json().get("data", {})
            total_credits = float(c_data.get("total_credits") or 0.0)
            total_usage = float(c_data.get("total_usage") or 0.0)
        elif r_credits.status_code == 401:
            return {
                "connected": False,
                "has_key": True,
                "error": "Chiave API non valida o non autorizzata (401).",
                "message": "La chiave OpenRouter configurata non è valida o è scaduta."
            }

        remaining_credits = max(0.0, total_credits - total_usage)
        percentage_remaining = round((remaining_credits / total_credits * 100), 1) if total_credits > 0 else 0.0

        key_label = "Chiave OpenRouter"
        key_usage = 0.0
        key_usage_daily = 0.0
        key_usage_weekly = 0.0
        key_usage_monthly = 0.0
        free_requests_remaining = 1000
        is_free_tier = False

        try:
            r_key = httpx.get("https://openrouter.ai/api/v1/auth/key", headers=headers, timeout=10.0)
            if r_key.status_code == 200:
                k_data = r_key.json().get("data", {})
                key_label = k_data.get("label") or key_label
                key_usage = float(k_data.get("usage") or 0.0)
                key_usage_daily = float(k_data.get("usage_daily") or 0.0)
                key_usage_weekly = float(k_data.get("usage_weekly") or 0.0)
                key_usage_monthly = float(k_data.get("usage_monthly") or 0.0)
                is_free_tier = bool(k_data.get("is_free_tier", False))
                free_req_data = k_data.get("free_model_daily_requests") or {}
                free_requests_remaining = int(free_req_data.get("remaining", 1000))
        except Exception as e_key:
            logger.warning(f"Errore secondario query auth/key OpenRouter: {e_key}")

        if remaining_credits > 5.0:
            status_level = "healthy"
            status_text = "DISPONIBILI"
        elif remaining_credits > 1.0:
            status_level = "warning"
            status_text = "IN ESAURIMENTO"
        elif remaining_credits > 0.0:
            status_level = "critical"
            status_text = "QUASI ESAURITI"
        else:
            status_level = "depleted"
            status_text = "ESAURITI"

        masked_key = f"{key[:10]}...{key[-4:]}" if len(key) >= 16 else "sk-or-v1-***"

        return {
            "connected": True,
            "is_configured": True,
            "has_key": True,
            "total_credits": round(total_credits, 2),
            "total_usage": round(total_usage, 2),
            "remaining_credits": round(remaining_credits, 2),
            "percentage_remaining": percentage_remaining,
            "key_label": key_label,
            "masked_key": masked_key,
            "key_usage": round(key_usage, 2),
            "key_usage_daily": round(key_usage_daily, 2),
            "key_usage_weekly": round(key_usage_weekly, 2),
            "key_usage_monthly": round(key_usage_monthly, 2),
            "free_requests_remaining": free_requests_remaining,
            "is_free_tier": is_free_tier,
            "status_level": status_level,
            "status_text": status_text,
            "currency": "USD ($)"
        }

    except Exception as e:
        logger.error(f"Errore recupero crediti OpenRouter: {e}")
        return {
            "connected": False,
            "is_configured": True,
            "has_key": True,
            "error": str(e),
            "message": "Impossibile contattare i server OpenRouter al momento. Verifica la tua connessione."
        }

