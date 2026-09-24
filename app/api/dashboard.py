import re
from typing import Optional
from pathlib import Path
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.models.database import get_db, Document, PhysicalItem, ChatThread
from app.models.schemas import DashboardResponse, DashboardKPI, RecordItem
from app.services.agent_service import categorize_deadline
from app.version import APP_VERSION

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

def classify_document_category(doc: Document) -> tuple[str, str, str]:
    """
    Restituisce (category_key, category_label, category_icon) per un documento.
    Dà priorità assoluta alla scelta autonoma dell'AI salvata nel campo doc.category_label.
    """
    # 0. Primato assoluto della scelta autonoma dell'AI o dell'utente (con protezione anti-duplicazione 'Oggetti Fisici')
    if doc.category_label:
        norm_label = doc.category_label.strip().lower()
        if "oggetti fisic" in norm_label or norm_label in ["oggetti", "oggetto", "oggetto fisico", "oggetti fisici", "cespiti", "inventario cespiti"]:
            is_img = (doc.file_type or "").lower() in ["jpg", "jpeg", "png", "webp", "image"] or (doc.doc_type or "").lower() in ["foto", "screenshot", "oggetto_fisico"]
            if is_img:
                return "foto_immagini", "Foto & Immagini", "fa-image"
            return "altro", "Altri Documenti Archiviati", "fa-folder-closed"
        icon = doc.category_icon or "fa-folder-closed"
        slug = doc.category or re.sub(r"[^a-zA-Z0-9]+", "_", doc.category_label.lower()).strip("_")
        return slug, doc.category_label, icon

    t = f"{doc.title or ''} {doc.doc_type or ''} {doc.issuer or ''} {doc.summary or ''}".lower()
    clean_type = (doc.doc_type or "").strip().lower()

    if clean_type in ["oggetto_fisico", "foto_oggetto"] or (doc.category or "").lower() in ["oggetti_fisici", "oggetto_fisico"]:
        is_img = (doc.file_type or "").lower() in ["jpg", "jpeg", "png", "webp", "image"] or clean_type in ["foto", "screenshot", "oggetto_fisico"]
        if is_img:
            return "foto_immagini", "Foto & Immagini", "fa-image"
        return "altro", "Altri Documenti Archiviati", "fa-folder-closed"

    # 1. Canzoni, Musica, Poesie e Testi Personali (PRIORITÀ: evita che parole emotive come 'sentimenti', 'ultimo', 'luce', 'acqua' finiscano in bollette)
    is_song_or_art = (
        clean_type in ["canzone", "musica", "poesia", "testo_canzone", "testo_personale", "note_personali", "brano"]
        or bool(re.search(r"\b(?:canzon[ei]|brano\s+musicale|testo\s+musicale|testo\s+di\s+un\s+brano|poesi[ae]|liric[ae]|strof[ae]|ritornell[oi]|cantautor[ei]|sfogo\s+emotivo|riflessioni\s+personali|pensieri\s+e\s+rimpianti|spartito|accordi|parole\s+della\s+canzone)\b", t))
    )
    if is_song_or_art:
        return "canzoni_musica", "Canzoni & Testi Musicali", "fa-music"

    # 2. Utenze & Bollette (Richiede contesto reale di utenza, fornitura o gestore con confine di parola)
    has_utility_provider = bool(re.search(
        r"\b(?:enel|a2a|plenitude|eni\s+gas|iren|hera|sorgenia|acea|edison|servizio\s+elettrico|servizio\s+idrico|acquedotto|vodafone|fastweb|iliad|windtre|\btim\b|telecom)\b",
        t
    ))
    has_utility_terms = bool(re.search(
        r"\b(?:bollett[ae]|utenz[ae]|fornitur[ae]|contatore|consumi|smc|kwh?|maggior\s+tutela|mercato\s+libero|energia\s+elettrica|luce\s+e\s+gas)\b",
        t
    ))
    if clean_type in ["bolletta", "utenza"]:
        return "utenze", "Utenze & Bollette", "fa-bolt"
    if has_utility_provider and (has_utility_terms or clean_type in ["fattura", "ricevuta", "spese"]):
        return "utenze", "Utenze & Bollette", "fa-bolt"
    if has_utility_terms and any(w in t for w in ["luce", "gas", "acqua", "elettric", "internet", "fibra"]):
        return "utenze", "Utenze & Bollette", "fa-bolt"

    # 3. Fisco, Tributi & F24 (Confini di parola per evitare che 'attiva', 'creativa' o 'viva' corrispondano a 'iva')
    if clean_type in ["f24", "tributo", "fiscale", "modello_unico", "dichiarazione_redditi"] or bool(re.search(
        r"\b(?:f24|imu|tari|tasi|irpef|tribut[oi]|730|modello\s+unico|redditi\s+pf|agenzia\s+delle\s+entrate|inps|tass[ae]|impost[ae]|certificazione\s+unica|\bcu\s*20\d\d\b|\biva\b)\b",
        t
    )):
        return "fisco", "Fisco, Tributi & F24", "fa-landmark"

    # 4. Documenti Personali & Identità
    if clean_type in ["carta_identita", "patente", "passaporto", "documento_identita", "tessera_sanitaria", "certificato"] or bool(re.search(
        r"\b(?:carta\s+d['’]identit[àa]|patente|passaport[oi]|tessera\s+sanitaria|codice\s+fiscale|permesso\s+di\s+soggiorno|anagrafic[ao]|certificato\s+di\s+nascita|certificato\s+di\s+residenza|stato\s+di\s+famiglia|immatricolazione|iscrizione\s+universit[àa]|tolc|diploma|laurea)\b",
        t
    )):
        return "identita", "Documenti Personali & Identità", "fa-id-card"

    # 5. Contratti, Polizze & Assicurazioni
    if clean_type in ["contratto", "polizza", "assicurazione"] or bool(re.search(
        r"\b(?:polizz[ae]|assicurazion[ei]|rca|contratt[oi]|locazione|affitto|comodato|assunzione|busta\s+paga|cedolino|stipendio|garanzia|clausol[ae])\b",
        t
    )):
        return "contratti", "Contratti, Polizze & Assicurazioni", "fa-file-contract"

    # 6. Fatture, Spese & Ricevute
    if clean_type in ["fattura", "ricevuta", "scontrino", "spese"] or bool(re.search(
        r"\b(?:fattur[ae]|ricevut[ae]|scontrin[oi]|tagliando|officina|meccanico|acquisto|spesa\s+sostenuta|ordine\s+d['’]acquisto|giustificativo|mediaworld|amazon|apple\s+store)\b",
        t
    )):
        return "spese", "Fatture, Spese & Ricevute", "fa-receipt"

    # 7. Sanità & Spese Mediche
    if clean_type in ["medico", "sanitario", "referto"] or bool(re.search(
        r"\b(?:sanit[àa]|medic[aoie]|salute|refert[oi]|ticket\s+sanitario|visita\s+medica|farmac[oi]|dentist[ae]|analisi\s+del\s+sangue|ospedal[ei]|clinica|prescrizione|ricetta\s+medica)\b",
        t
    )):
        return "sanita", "Sanità & Spese Mediche", "fa-heart-pulse"

    # 8. Archivi ZIP
    if clean_type in ["archivio_zip", "zip"] or (doc.file_type or "").lower() == "zip":
        return "archivi_zip", "Archivi Compressi & ZIP", "fa-file-zipper"

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
    # Normalize filter parameter with Italian aliases
    f_raw = (filter or "all").lower().strip()
    if f_raw in ("da_pagare", "scadenze", "scadenza", "deadlines", "pending"):
        norm_filter = "deadlines"
    elif f_raw in ("oggetti", "items", "oggetti_fisici", "cose"):
        norm_filter = "items"
    elif f_raw in ("quietanzato", "quietanzati", "pagati", "saldati", "paid"):
        norm_filter = "quietanzati"
    elif f_raw in ("documenti", "documents", "docs", "file"):
        norm_filter = "documents"
    else:
        norm_filter = "all"

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
    quietanzati_docs = [d for d in all_docs if d.status == "quietanzato"]
    quietanzati_count = len(quietanzati_docs)

    kpi = DashboardKPI(
        total_upcoming_amount=total_upcoming_amount,
        pending_deadlines_count=pending_deadlines_count,
        total_documents_count=total_documents_count,
        total_items_count=total_items_count,
        quietanzati_count=quietanzati_count
    )

    # 3. Assemble records
    records = []

    needs_commit = False
    # Map documents
    if norm_filter in ("all", "documents", "deadlines", "quietanzati"):
        for doc in all_docs:
            if norm_filter == "deadlines" and doc.status != "da_pagare":
                continue
            if norm_filter == "quietanzati" and doc.status != "quietanzato":
                continue

            badge_color = "amber" if doc.status == "da_pagare" else "emerald"
            fn = Path(doc.file_path).name
            cat = categorize_deadline(doc.due_date) if doc.status == "da_pagare" else None
            doc_cat, doc_cat_label, doc_cat_icon = classify_document_category(doc)
            if not doc.category_label or doc.category_label != doc_cat_label:
                doc.category = doc_cat
                doc.category_label = doc_cat_label
                doc.category_icon = doc_cat_icon
                needs_commit = True

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
                    subfolder=doc.subfolder,
                    room=None,
                    detailed_location=None,
                    document_id=doc.id,
                    physical_item_id=doc.physical_item_id,
                    image_url=f"/uploads/{fn}" if doc.file_type in ["jpg", "jpeg", "png", "webp"] else None,
                    has_photo=doc.file_type in ["jpg", "jpeg", "png", "webp"],
                    is_local_file=bool(doc.is_local_file),
                    original_path=doc.original_path or (doc.file_path if doc.is_local_file else None)
                )
            )

        if needs_commit:
            try:
                db.commit()
            except Exception:
                db.rollback()

    # Map physical items
    if norm_filter in ("all", "items"):
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

    return DashboardResponse(kpi=kpi, records=records, app_version=APP_VERSION)
