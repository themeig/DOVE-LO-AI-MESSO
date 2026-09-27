import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.models.database import get_db, Document, GoogleDriveCredential
from app.services.calendar_service import (
    get_calendar_service,
    DEDICATED_CALENDAR_SUMMARY,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.get("/status")
def get_calendar_status(db: Session = Depends(get_db)):
    """Restituisce lo stato attuale della connessione e del calendario dedicato su Google Calendar."""
    cred = db.query(GoogleDriveCredential).first()
    service = get_calendar_service()
    is_real = hasattr(service, "client_id") and bool(service.client_id)

    cal_id = cred.google_calendar_id if cred else None
    return {
        "connected": bool(cred),
        "user_email": cred.user_email if cred else None,
        "calendar_id": cal_id,
        "calendar_name": DEDICATED_CALENDAR_SUMMARY,
        "web_url": "https://calendar.google.com/calendar/u/0/r",
        "mode": "real" if is_real else "mock",
    }


@router.post("/sync")
def sync_all_calendar_deadlines(db: Session = Depends(get_db)):
    """Sincronizza in blocco tutte le scadenze del caveau nel calendario dedicato 'Dove Lo AI Messo - Scadenze'."""
    cred = db.query(GoogleDriveCredential).first()
    if not cred or not cred.access_token:
        raise HTTPException(
            status_code=400,
            detail="Account Google non collegato. Connetti prima il tuo account Google nelle impostazioni cloud.",
        )

    service = get_calendar_service()
    try:
        # Recupera o crea il calendario dedicato
        cal_id = cred.google_calendar_id or service.get_or_create_dedicated_calendar(cred.access_token)
        if not cred.google_calendar_id:
            cred.google_calendar_id = cal_id
            db.commit()

        # Documenti con data di scadenza
        docs = db.query(Document).filter(Document.due_date.isnot(None)).all()
        result = service.sync_all_deadlines(docs, cred.access_token, calendar_id=cal_id)
        db.commit()

        return {
            "success": True,
            "calendar_id": cal_id,
            "calendar_name": DEDICATED_CALENDAR_SUMMARY,
            "user_email": cred.user_email,
            "web_url": "https://calendar.google.com/calendar/u/0/r",
            "synced_count": result.get("synced_count", 0),
            "synced_doc_ids": result.get("synced_doc_ids", []),
            "errors": result.get("errors", []),
            "message": f"Sincronizzate {result.get('synced_count', 0)} scadenze nel calendario dedicato '{DEDICATED_CALENDAR_SUMMARY}'.",
        }
    except Exception as e:
        logger.error(f"Errore sincronizzazione Google Calendar: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Impossibile sincronizzare con Google Calendar: {str(e)}",
        )


@router.post("/sync/{doc_id}")
def sync_single_document_deadline(doc_id: int, db: Session = Depends(get_db)):
    """Sincronizza la scadenza di un singolo documento su Google Calendar."""
    cred = db.query(GoogleDriveCredential).first()
    if not cred or not cred.access_token:
        raise HTTPException(
            status_code=400,
            detail="Account Google non collegato. Connetti prima il tuo account Google nelle impostazioni cloud.",
        )

    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento non trovato")
    if not doc.due_date:
        raise HTTPException(status_code=400, detail="Il documento non presenta una data di scadenza definita")

    service = get_calendar_service()
    try:
        cal_id = cred.google_calendar_id or service.get_or_create_dedicated_calendar(cred.access_token)
        if not cred.google_calendar_id:
            cred.google_calendar_id = cal_id
            db.commit()

        res = service.sync_deadline_event(doc, cal_id, cred.access_token)
        if res and res.get("event_id"):
            doc.google_calendar_event_id = res["event_id"]
            db.commit()

        return {
            "success": True,
            "doc_id": doc.id,
            "calendar_id": cal_id,
            "event_id": doc.google_calendar_event_id,
            "html_link": res.get("html_link"),
            "message": "Scadenza sincronizzata con Google Calendar.",
        }
    except Exception as e:
        logger.error(f"Errore sincronizzazione singolo evento per doc #{doc_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Errore sincronizzazione evento Google Calendar: {str(e)}",
        )


@router.delete("/events/{doc_id}")
def delete_document_calendar_event(doc_id: int, db: Session = Depends(get_db)):
    """Rimuove l'evento di scadenza da Google Calendar."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento non trovato")

    cred = db.query(GoogleDriveCredential).first()
    if not cred or not cred.access_token or not doc.google_calendar_event_id:
        doc.google_calendar_event_id = None
        db.commit()
        return {"success": True, "message": "Nessun evento attivo da rimuovere"}

    service = get_calendar_service()
    cal_id = cred.google_calendar_id or "primary"
    try:
        service.delete_deadline_event(doc.google_calendar_event_id, cal_id, cred.access_token)
        doc.google_calendar_event_id = None
        db.commit()
        return {"success": True, "message": "Evento rimosso da Google Calendar"}
    except Exception as e:
        logger.warning(f"Errore eliminazione evento doc #{doc_id}: {e}")
        doc.google_calendar_event_id = None
        db.commit()
        return {"success": True, "message": "Riferimento locale rimosso"}
