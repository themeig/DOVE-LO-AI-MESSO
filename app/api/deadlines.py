from typing import Optional, List
from pathlib import Path
from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.models.database import get_db, Document
from app.models.schemas import DeadlineAlertsResponse, DeadlineAlertItem
from app.services.agent_service import categorize_deadline, get_current_date_info

router = APIRouter(prefix="/api/deadlines", tags=["deadlines"])

@router.get("/alerts", response_model=DeadlineAlertsResponse)
def get_deadline_alerts(
    thread_id: Optional[str] = Query(default=None, description="Filtra per specifico thread/gruppo"),
    days_ahead: int = Query(default=7, ge=1, le=365, description="Giorni di preavviso per le scadenze"),
    db: Session = Depends(get_db)
):
    """Rileva tutte le bollette e i documenti con stato 'da_pagare' scaduti o in scadenza entro days_ahead giorni."""
    query = db.query(Document).filter(
        Document.status == "da_pagare",
        Document.due_date.isnot(None)
    )

    if thread_id and thread_id != "all":
        query = query.filter(Document.thread_id == thread_id)

    unpaid_docs = query.order_by(Document.due_date.asc()).all()

    today = date.today()
    alerts: List[DeadlineAlertItem] = []
    overdue_count = 0
    due_soon_count = 0
    total_amount = 0.0

    for doc in unpaid_docs:
        cat = categorize_deadline(doc.due_date, today)
        days = cat["days_remaining"]
        if days is not None and days <= days_ahead:
            if days < 0:
                overdue_count += 1
            else:
                due_soon_count += 1

            if doc.amount is not None:
                total_amount += doc.amount

            fn = Path(doc.file_path).name if doc.file_path else ""
            alerts.append(
                DeadlineAlertItem(
                    id=doc.id,
                    document_id=doc.id,
                    title=doc.title,
                    issuer=doc.issuer,
                    amount=doc.amount,
                    due_date=doc.due_date.isoformat(),
                    days_remaining=days,
                    urgency=cat["urgency"],
                    urgency_label=cat["urgency_label"],
                    file_url=f"/uploads/{fn}" if fn else None,
                    download_url=f"/api/documents/{doc.id}/download",
                    file_type=doc.file_type,
                    thread_id=doc.thread_id
                )
            )

    # Ordina: le più scadute prima, poi oggi, poi quelle imminenti
    alerts.sort(key=lambda a: a.days_remaining)

    total_alerts = len(alerts)
    has_alerts = total_alerts > 0
    total_amount = round(total_amount, 2)

    if not has_alerts:
        summary_message = f"Nessuna scadenza in sospeso o scaduta nei prossimi {days_ahead} giorni."
    else:
        parts = []
        if overdue_count > 0:
            parts.append(f"{overdue_count} {'scaduta' if overdue_count == 1 else 'scadute'}")
        if due_soon_count > 0:
            parts.append(f"{due_soon_count} in scadenza entro {days_ahead} giorni")
        detail = " e ".join(parts)
        amt_str = f" per un totale di {total_amount:.2f} €" if total_amount > 0 else ""
        summary_message = f"Hai {total_alerts} {'scadenza' if total_alerts == 1 else 'scadenze'} da verificare ({detail}){amt_str}."

    date_info = get_current_date_info()

    return DeadlineAlertsResponse(
        has_alerts=has_alerts,
        overdue_count=overdue_count,
        due_soon_count=due_soon_count,
        total_alerts=total_alerts,
        total_amount=total_amount,
        summary_message=summary_message,
        today=date_info["date"],
        alerts=alerts
    )
