import logging
import math
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
