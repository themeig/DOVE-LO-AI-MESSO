import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.models.database import get_db, UIEvent
from app.models.schemas import UIEventCreate, UIEventResponse, UIEventsListResponse, UIEventItem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


@router.post("/ui-event", response_model=UIEventResponse)
def record_ui_event(payload: UIEventCreate, db: Session = Depends(get_db)):
    """Riceve un feedback / evento di rendering o errore dal frontend e lo salva nel caveau."""
    try:
        ev = UIEvent(
            thread_id=payload.thread_id or "general",
            event_type=payload.event_type,
            target_type=payload.target_type,
            target_id=payload.target_id,
            title=payload.title,
            error_details=payload.error_details
        )
        db.add(ev)
        db.commit()
        db.refresh(ev)
        logger.info(f"[UI Telemetry] Ricevuto evento '{payload.event_type}' per thread '{payload.thread_id}': {payload.title or ''} ({payload.error_details or ''})")
        return UIEventResponse(status="ok", event_id=ev.id)
    except Exception as e:
        logger.error(f"[UI Telemetry] Errore salvataggio evento UI: {e}")
        db.rollback()
        return UIEventResponse(status="error", event_id=0)


@router.get("/ui-events", response_model=UIEventsListResponse)
def list_ui_events(
    thread_id: Optional[str] = Query(None, description="Filtra per thread"),
    limit: int = Query(20, description="Numero di eventi da recuperare"),
    db: Session = Depends(get_db)
):
    """Restituisce gli ultimi eventi di telemetria per ispezione o diagnostica."""
    q = db.query(UIEvent)
    if thread_id:
        q = q.filter(UIEvent.thread_id == thread_id)
    events = q.order_by(UIEvent.created_at.desc()).limit(limit).all()

    items = [
        UIEventItem(
            id=e.id,
            thread_id=e.thread_id,
            event_type=e.event_type,
            target_type=e.target_type,
            target_id=e.target_id,
            title=e.title,
            error_details=e.error_details,
            created_at=e.created_at.isoformat() if e.created_at else None
        )
        for e in events
    ]
    return UIEventsListResponse(events=items)
