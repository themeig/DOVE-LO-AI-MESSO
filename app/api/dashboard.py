from typing import Optional
from pathlib import Path
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.models.database import get_db, Document, PhysicalItem
from app.models.schemas import DashboardResponse, DashboardKPI, RecordItem

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

@router.get("", response_model=DashboardResponse)
@router.get("/", response_model=DashboardResponse, include_in_schema=False)
def get_dashboard(
    filter: Optional[str] = Query(default="all"),
    db: Session = Depends(get_db)
):
    # 1. Fetch documents and physical items
    all_docs = db.query(Document).order_by(Document.created_at.desc()).all()
    all_items = db.query(PhysicalItem).order_by(PhysicalItem.updated_at.desc()).all()

    # 2. Compute KPIs
    pending_docs = [d for d in all_docs if d.status == "da_pagare"]
    total_upcoming_amount = round(sum(d.amount for d in pending_docs if d.amount is not None), 2)
    pending_deadlines_count = len(pending_docs)
    total_documents_count = len(all_docs)
    total_items_count = len(all_items)

    kpi = DashboardKPI(
        total_upcoming_amount=total_upcoming_amount,
        pending_deadlines_count=pending_deadlines_count,
        total_documents_count=total_documents_count,
        total_items_count=total_items_count
    )

    # 3. Assemble records
    records = []

    # Map documents
    if filter in ("all", "documents", "deadlines"):
        for doc in all_docs:
            if filter == "deadlines" and doc.status != "da_pagare":
                continue

            badge_color = "amber" if doc.status == "da_pagare" else "emerald"
            fn = Path(doc.file_path).name
            records.append(
                RecordItem(
                    id=doc.id,
                    type="document",
                    title=doc.title,
                    source=doc.issuer or f"File ({doc.file_type.upper()})",
                    amount=doc.amount,
                    due_date=doc.due_date.isoformat() if doc.due_date else None,
                    status=doc.status,
                    location_or_notes=doc.summary,
                    badge_color=badge_color,
                    file_url=f"/uploads/{fn}",
                    file_type=doc.file_type
                )
            )

    # Map physical items
    if filter in ("all", "items"):
        for item in all_items:
            loc = item.primary_location
            if item.detailed_location:
                loc += f" - {item.detailed_location}"

            records.append(
                RecordItem(
                    id=item.id,
                    type="physical_item",
                    title=item.item_name,
                    source="Posizione Fisica",
                    amount=None,
                    due_date=None,
                    status="conservato",
                    location_or_notes=loc,
                    badge_color="blue"
                )
            )

    return DashboardResponse(kpi=kpi, records=records)
