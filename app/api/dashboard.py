from typing import Optional
from pathlib import Path
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.models.database import get_db, Document, PhysicalItem, ChatThread
from app.models.schemas import DashboardResponse, DashboardKPI, RecordItem
from app.services.agent_service import categorize_deadline

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

def classify_document_category(doc: Document) -> tuple[str, str, str]:
    """Restituisce (category_key, category_label, category_icon) per un documento."""
    t = f"{doc.title} {doc.doc_type} {doc.issuer or ''} {doc.summary or ''}".lower()
    
    if any(k in t for k in ["bollett", "luce", "gas", "acqua", "telefoni", "internet", "fibra", "utenz", "enel", "eni", "a2a", "tim", "vodafone", "iliad", "fastweb", "servizio elettrico"]):
        return "utenze", "Utenze & Bollette", "fa-bolt"
    
    if any(k in t for k in ["f24", "imu", "tari", "tribut", "730", "agenzia delle entrate", "iva", "inps", "tassa", "tasse", "redditi", "cu "]):
        return "fisco", "Fisco, Tributi & F24", "fa-landmark"
        
    if any(k in t for k in ["carta d'identit", "patente", "passaport", "tessera sanitaria", "codice fiscale", "immatricolazione", "universit", "scuola", "anagrafic", "identit"]):
        return "identita", "Documenti Personali & Identità", "fa-id-card"
        
    if any(k in t for k in ["polizza", "assicura", "rca", "contratt", "locazione", "affitto", "lavoro", "garanzia", "clausola"]):
        return "contratti", "Contratti, Polizze & Assicurazioni", "fa-file-contract"
        
    if any(k in t for k in ["fattur", "ricevut", "scontrin", "tagliando", "officina", "meccanico", "acquisto", "spesa", "ordine", "mediaworld", "amazon", "apple"]):
        return "spese", "Fatture, Spese & Ricevute", "fa-receipt"
        
    if any(k in t for k in ["sanit", "medic", "salute", "refert", "ticket", "visita", "farmac", "dentist", "esame", "analisi del sangue", "ospedale"]):
        return "sanita", "Sanità & Spese Mediche", "fa-heart-pulse"
        
    return "altro", "Altri Documenti Archiviati", "fa-folder-closed"


def classify_item_room_and_category(item: PhysicalItem) -> tuple[str, str, str, str]:
    """Restituisce (room, category_key, category_label, category_icon) per un oggetto fisico."""
    loc_prim = (item.primary_location or "Non specificato").strip()
    loc_lower = loc_prim.lower()
    
    # Rilevamento icona stanza/ambiente
    if any(k in loc_lower for k in ["studio", "scrivania", "ufficio", "libreria", "pc"]):
        icon = "fa-laptop"
    elif any(k in loc_lower for k in ["camera", "letto", "armadio", "comodino"]):
        icon = "fa-bed"
    elif any(k in loc_lower for k in ["salotto", "soggiorno", "divano", "tv", "sala"]):
        icon = "fa-couch"
    elif any(k in loc_lower for k in ["cucina", "frigo", "credenza", "dispensa"]):
        icon = "fa-kitchen-set"
    elif any(k in loc_lower for k in ["garage", "ripostiglio", "cantina", "soffitta", "scaffale"]):
        icon = "fa-warehouse"
    elif any(k in loc_lower for k in ["bagno"]):
        icon = "fa-bath"
    elif any(k in loc_lower for k in ["ingresso", "corridoio", "appendiabiti"]):
        icon = "fa-door-open"
    else:
        icon = "fa-boxes-stacked"
        
    cat_raw = (item.category or "").lower()
    it_name = item.item_name.lower()
    
    if any(k in it_name or k in cat_raw for k in ["passaporto", "carta", "patente", "document", "contratt", "certificat", "cartell"]):
        cat_key = "documenti_cartacei"
        cat_label = "Documenti Cartacei & Valori"
    elif any(k in it_name or k in cat_raw for k in ["chiav", "telecomando", "badge", "tessera"]):
        cat_key = "chiavi_accessori"
        cat_label = "Chiavi & Accessori"
    elif any(k in it_name or k in cat_raw for k in ["cavo", "computer", "telefono", "caricabatterie", "cuffie", "elettronica"]):
        cat_key = "elettronica"
        cat_label = "Dispositivi & Elettronica"
    elif any(k in it_name or k in cat_raw for k in ["attrezz", "chiave inglese", "trapano", "cacciavite", "tenda", "bici"]):
        cat_key = "attrezzatura"
        cat_label = "Attrezzatura & Fai-da-te"
    else:
        cat_key = "oggetti_personali"
        cat_label = "Oggetti Personali"
        
    return loc_prim, cat_key, cat_label, icon


@router.get("", response_model=DashboardResponse)
@router.get("/", response_model=DashboardResponse, include_in_schema=False)
def get_dashboard(
    filter: Optional[str] = Query(default="all"),
    thread_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db)
):
    # Lookup threads for readable names
    threads = db.query(ChatThread).all()
    thread_map = {t.id: t.name for t in threads}

    # 1. Fetch documents and physical items
    doc_query = db.query(Document)
    item_query = db.query(PhysicalItem)

    if thread_id and thread_id != "all":
        doc_query = doc_query.filter(Document.thread_id == thread_id)
        item_query = item_query.filter(PhysicalItem.thread_id == thread_id)

    all_docs = doc_query.order_by(Document.created_at.desc()).all()
    all_items = item_query.order_by(PhysicalItem.updated_at.desc()).all()

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
            cat = categorize_deadline(doc.due_date) if doc.status == "da_pagare" else None
            doc_cat, doc_cat_label, doc_cat_icon = classify_document_category(doc)
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
                    file_type=doc.file_type,
                    thread_id=doc.thread_id,
                    thread_name=thread_map.get(doc.thread_id, "Principale"),
                    days_remaining=cat["days_remaining"] if cat else None,
                    urgency=cat["urgency"] if cat else None,
                    urgency_label=cat["urgency_label"] if cat else None,
                    category=doc_cat,
                    category_label=doc_cat_label,
                    category_icon=doc_cat_icon,
                    room=None,
                    detailed_location=None,
                    document_id=doc.id,
                    physical_item_id=doc.physical_item_id,
                    image_url=f"/uploads/{fn}" if doc.file_type in ["jpg", "jpeg", "png", "webp"] else None,
                    has_photo=doc.file_type in ["jpg", "jpeg", "png", "webp"]
                )
            )

    # Map physical items
    if filter in ("all", "items"):
        for item in all_items:
            loc = item.primary_location
            if item.detailed_location:
                loc += f" - {item.detailed_location}"

            room, item_cat, item_cat_label, item_icon = classify_item_room_and_category(item)
            img_url = f"/api/files/{Path(item.image_path).name}" if item.image_path else None
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
                    badge_color="blue",
                    thread_id=item.thread_id,
                    thread_name=thread_map.get(item.thread_id, "Principale"),
                    category=item_cat,
                    category_label=item_cat_label,
                    category_icon=item_icon,
                    room=room,
                    detailed_location=item.detailed_location,
                    file_url=img_url,
                    file_type="image" if item.image_path else None,
                    document_id=item.document_id,
                    physical_item_id=None,
                    image_url=img_url,
                    has_photo=bool(item.image_path)
                )
            )

    return DashboardResponse(kpi=kpi, records=records)
