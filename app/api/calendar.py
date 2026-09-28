import logging
from datetime import datetime, timezone
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.database import get_db, Document, GoogleDriveCredential
from app.services.calendar_service import (
    get_calendar_service,
    DEDICATED_CALENDAR_SUMMARY,
    auto_sync_all_deadlines,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


class CalendarSettingsUpdate(BaseModel):
    calendar_enabled: Optional[bool] = None
    calendar_target: Optional[Literal["dedicated", "primary"]] = None


@router.get("/status")
def get_calendar_status(db: Session = Depends(get_db)):
    """Restituisce lo stato attuale della connessione e del calendario (dedicato o principale) su Google Calendar."""
    cred = db.query(GoogleDriveCredential).first()
    service = get_calendar_service()
    is_real = hasattr(service, "client_id") and bool(service.client_id)

    cal_target = getattr(cred, "calendar_target", "dedicated") if cred else "dedicated"
    cal_enabled = getattr(cred, "calendar_enabled", True) if cred else False

    if cal_target == "primary":
        cal_id = "primary" if cred else None
        cal_name = "Calendario Principale"
    else:
        cal_id = cred.google_calendar_id if cred else None
        cal_name = DEDICATED_CALENDAR_SUMMARY

    return {
        "connected": bool(cred),
        "user_email": cred.user_email if cred else None,
        "calendar_id": cal_id,
        "calendar_name": cal_name,
        "calendar_enabled": cal_enabled,
        "calendar_target": cal_target,
        "web_url": "https://calendar.google.com/calendar/u/0/r",
        "mode": "real" if is_real else "mock",
    }


@router.patch("/settings")
def update_calendar_settings(
    body: CalendarSettingsUpdate,
    db: Session = Depends(get_db),
):
    """Aggiorna le impostazioni di Google Calendar: abilitazione e target (dedicato vs principale)."""
    cred = db.query(GoogleDriveCredential).first()
    if not cred:
        raise HTTPException(
            status_code=404,
            detail="Nessun account Google connesso",
        )

    if body.calendar_enabled is not None:
        cred.calendar_enabled = body.calendar_enabled

    if body.calendar_target is not None:
        cred.calendar_target = body.calendar_target
        if body.calendar_target == "primary":
            cred.google_calendar_id = "primary"
        else:
            if cred.google_calendar_id == "primary":
                cred.google_calendar_id = None

    cred.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(cred)

    if cred.calendar_enabled:
        try:
            auto_sync_all_deadlines(db)
        except Exception as e:
            logger.warning(f"Errore auto_sync_all_deadlines durante aggiornamento impostazioni: {e}")

    cal_target = getattr(cred, "calendar_target", "dedicated")
    cal_name = "Calendario Principale" if cal_target == "primary" else DEDICATED_CALENDAR_SUMMARY
    return {
        "success": True,
        "calendar_enabled": cred.calendar_enabled,
        "calendar_target": cred.calendar_target,
        "calendar_name": cal_name,
    }


@router.post("/disconnect")
def disconnect_calendar(db: Session = Depends(get_db)):
    """Disconnette l'account Google eliminando le credenziali salvate."""
    db.query(GoogleDriveCredential).delete()
    db.commit()
    return {"success": True}


@router.post("/sync")
def sync_all_calendar_deadlines(db: Session = Depends(get_db)):
    """Sincronizza in blocco tutte le scadenze del caveau nel calendario prescelto (dedicato o principale)."""
    cred = db.query(GoogleDriveCredential).first()
    if not cred or not cred.access_token:
        raise HTTPException(
            status_code=400,
            detail="Account Google non collegato. Connetti prima il tuo account Google nelle impostazioni cloud.",
        )

    service = get_calendar_service()
    try:
        cal_target = getattr(cred, "calendar_target", "dedicated")
        if cal_target == "primary":
            cal_id = "primary"
            cal_name = "Calendario Principale"
        else:
            cal_id = cred.google_calendar_id or service.get_or_create_dedicated_calendar(cred.access_token)
            if not cred.google_calendar_id:
                cred.google_calendar_id = cal_id
                db.commit()
            cal_name = DEDICATED_CALENDAR_SUMMARY

        docs = db.query(Document).filter(Document.due_date.isnot(None)).all()
        result = service.sync_all_deadlines(docs, cred.access_token, calendar_id=cal_id)
        db.commit()

        return {
            "success": True,
            "calendar_id": cal_id,
            "calendar_name": cal_name,
            "user_email": cred.user_email,
            "web_url": "https://calendar.google.com/calendar/u/0/r",
            "synced_count": result.get("synced_count", 0),
            "synced_doc_ids": result.get("synced_doc_ids", []),
            "errors": result.get("errors", []),
            "message": f"Sincronizzate {result.get('synced_count', 0)} scadenze nel calendario '{cal_name}'.",
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
        cal_target = getattr(cred, "calendar_target", "dedicated")
        if cal_target == "primary":
            cal_id = "primary"
        else:
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
