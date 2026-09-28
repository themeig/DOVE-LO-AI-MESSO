"""
Servizio per la registrazione e consultazione del registro operativo condiviso (Activity Ledger).
Gestisce la memorizzazione di eventi di protocollo (caricamento documenti, pagamenti, scadenze, inventario)
per i gruppi, garantendo che il feed mostri solo atti ufficiali e mai messaggi social informali.
"""
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from app.models.database import ActivityEvent


def record_activity_event(
    db: Session,
    group_id: str,
    event_type: str,
    title: str,
    actor_user_id: Optional[str] = None,
    actor_name: str = "Sistema",
    content: Optional[str] = None,
    document_id: Optional[int] = None,
    item_id: Optional[int] = None,
    payload: Optional[Dict[str, Any]] = None
) -> ActivityEvent:
    """
    Registra un evento ufficiale nel registro operativo del gruppo.
    Tipologie supportate:
    - DOCUMENT_UPLOADED
    - DOCUMENT_PAID
    - DOCUMENT_RENAMED
    - DOCUMENT_DELETED
    - ITEM_STORED
    - DEADLINE_ALERT
    - AI_ASSISTANT_QUERY
    """
    event = ActivityEvent(
        group_id=group_id,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        event_type=event_type,
        title=title,
        content=content,
        document_id=document_id,
        item_id=item_id,
        payload=payload or {}
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def list_group_activity_feed(
    db: Session,
    group_id: str,
    limit: int = 50,
    offset: int = 0
) -> List[ActivityEvent]:
    """
    Restituisce il feed cronologico decrescente degli eventi di un gruppo.
    """
    return db.query(ActivityEvent)\
        .filter(ActivityEvent.group_id == group_id)\
        .order_by(ActivityEvent.created_at.desc(), ActivityEvent.id.desc())\
        .offset(offset)\
        .limit(limit)\
        .all()
