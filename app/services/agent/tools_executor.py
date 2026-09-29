"""
Modulo di esecuzione ed orchestrazione dei 20 tool ufficiali del Caveau.
"""
import json
import logging
import re
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.config import get_settings
from app.models.database import (
    Document,
    PhysicalItem,
    ChatMessage,
    ChatThread,
    get_app_setting,
    UIEvent,
    WatchedFolder,
    GoogleDriveCredential,
)
from app.services.search_service import (
    search_vault_documents,
    search_vault_items,
    ITALIAN_STOPWORDS,
    it_stem,
    token_matches,
)
from app.services.drive_service import resolve_drive_folder_path, sanitize_drive_folder_name
from app.services.agent.helpers import (
    get_current_date_info,
    categorize_deadline,
    extract_bulk_delete_target,
    extract_rename_title,
)

logger = logging.getLogger(__name__)

def execute_vault_tool(name: str, args: Dict[str, Any], db: Session, thread_id: str = "general") -> Dict[str, Any]:
    """Esegue uno strumento registrato contro il database SQLite locale."""
    logger.info(f"Esecuzione tool {name} con argomenti: {args} (thread: {thread_id})")

    if name == "search_vault":
        query = (args.get("query") or "").strip()
        doc_results = search_vault_documents(db, query, thread_id=thread_id)
        item_results = search_vault_items(db, query, thread_id=thread_id)
        return {
            "query": query,
            "found_documents": doc_results[:5],
            "found_physical_items": item_results[:5]
        }

    elif name == "get_recent_vault_documents":
        limit = args.get("limit", 3)
        docs = (
            db.query(Document)
            .order_by(Document.created_at.desc())
            .limit(limit)
            .all()
        )
        return {
            "recent_documents": [
                {
                    "id": d.id,
                    "document_id": d.id,
                    "thread_id": d.thread_id,
                    "title": d.title,
                    "issuer": d.issuer,
                    "doc_type": d.doc_type,
                    "amount": d.amount,
                    "due_date": d.due_date.isoformat() if d.due_date else None,
                    "status": d.status,
                    "summary": d.summary,
                    "filename": Path(d.file_path).name if d.file_path else "",
                    "file_url": f"/uploads/{Path(d.file_path).name}" if d.file_path else None,
                    "download_url": f"/api/documents/{d.id}/download",
                    "file_type": d.file_type,
                    "drive_file_id": d.drive_file_id,
                    "drive_web_url": d.drive_web_url,
                    "is_on_drive": bool(d.drive_file_id or d.drive_web_url)
                }
                for d in docs
            ]
        }

    elif name == "store_physical_item":
        raw_name = args.get("item_name", "Oggetto").strip()
        cleaned_name = re.sub(r"^(il|lo|la|i|gli|le|l'|un|uno|una|un')\s*", "", raw_name, flags=re.IGNORECASE).strip()
        item_name = (cleaned_name if cleaned_name else raw_name).capitalize()
        prim_loc = args.get("primary_location", "Non specificato").strip()
        det_loc = args.get("detailed_location")
        if det_loc is not None:
            det_loc = det_loc.strip() or None
        cat = args.get("category", "generico")

        # 1. Cerca per nome esatto (case-insensitive)
        existing = db.query(PhysicalItem).filter(PhysicalItem.item_name.ilike(item_name)).first()
        if not existing and thread_id:
            existing = db.query(PhysicalItem).filter(PhysicalItem.thread_id == thread_id, PhysicalItem.item_name.ilike(item_name)).first()

        # 2. Se non trovato, cerca con matching semantico/stemming (es. "Tenda" per "Tenda da campeggio")
        if not existing:
            candidates = search_vault_items(db, item_name, thread_id=thread_id)
            if candidates:
                matched_id = candidates[0].get("item_id") or candidates[0].get("id")
                if matched_id:
                    existing = db.query(PhysicalItem).filter(PhysicalItem.id == matched_id).first()

        img_p = args.get("image_path")
        doc_id = args.get("document_id")
        doc_title = (args.get("document_title") or "").strip()

        linked_doc = None
        if doc_id:
            linked_doc = db.query(Document).filter(Document.id == doc_id).first()
        if not linked_doc and doc_title:
            s_docs = search_vault_documents(db, doc_title, thread_id=thread_id)
            if s_docs:
                linked_doc = db.query(Document).filter(Document.id == s_docs[0]["id"]).first()

        if existing:
            existing.primary_location = prim_loc
            existing.detailed_location = det_loc
            if img_p:
                existing.image_path = img_p
            if linked_doc:
                existing.document_id = linked_doc.id
                existing.image_path = linked_doc.file_path
                linked_doc.physical_item_id = existing.id
            if thread_id:
                existing.thread_id = thread_id
            item = existing
        else:
            item = PhysicalItem(
                thread_id=thread_id,
                item_name=item_name,
                primary_location=prim_loc,
                detailed_location=det_loc,
                category=cat,
                image_path=linked_doc.file_path if linked_doc else img_p,
                document_id=linked_doc.id if linked_doc else None
            )
            db.add(item)
            db.flush()
            if linked_doc:
                linked_doc.physical_item_id = item.id

        db.commit()
        db.refresh(item)

        loc_str = item.primary_location + (f" ({item.detailed_location})" if item.detailed_location else "")
        fn = Path(item.image_path).name if item.image_path else None
        return {
            "success": True,
            "item_id": item.id,
            "thread_id": item.thread_id,
            "item_name": item.item_name,
            "primary_location": item.primary_location,
            "detailed_location": item.detailed_location,
            "category": item.category,
            "location_str": loc_str,
            "document_id": item.document_id,
            "image_url": f"/api/files/{fn}" if fn else None,
            "has_photo": bool(item.image_path or item.document_id)
        }

    elif name == "link_document_to_item":
        item_name = (args.get("item_name") or "").strip()
        item_id = args.get("item_id")
        doc_id = args.get("document_id")
        doc_title = (args.get("document_title") or "").strip()
        img_path = args.get("image_path")

        # 1. Trova documento
        doc = None
        if doc_id:
            doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc and doc_title:
            s_docs = search_vault_documents(db, doc_title, thread_id=thread_id)
            if s_docs:
                doc = db.query(Document).filter(Document.id == s_docs[0]["id"]).first()
        if not doc:
            q = db.query(Document)
            if thread_id and thread_id not in ["general", "all"]:
                q = q.filter(Document.thread_id == thread_id)
            doc = q.order_by(Document.id.desc()).first()

        # 2. Trova o crea oggetto fisico
        item = None
        if item_id:
            item = db.query(PhysicalItem).filter(PhysicalItem.id == item_id).first()
        elif item_name:
            clean_name = re.sub(r"^(il|lo|la|i|gli|le|l'|un|uno|una|un')\s*", "", item_name, flags=re.IGNORECASE).strip()
            cap_name = (clean_name if clean_name else item_name).capitalize()
            item = db.query(PhysicalItem).filter(PhysicalItem.item_name.ilike(cap_name)).first()
            if not item and thread_id:
                item = db.query(PhysicalItem).filter(PhysicalItem.thread_id == thread_id, PhysicalItem.item_name.ilike(cap_name)).first()
            if not item:
                s_items = search_vault_items(db, cap_name, thread_id=thread_id)
                if s_items:
                    item = db.query(PhysicalItem).filter(PhysicalItem.id == s_items[0]["item_id"]).first()

        if not item and item_name:
            clean_name = re.sub(r"^(il|lo|la|i|gli|le|l'|un|uno|una|un')\s*", "", item_name, flags=re.IGNORECASE).strip()
            cap_name = (clean_name if clean_name else item_name).capitalize()
            item = PhysicalItem(
                thread_id=thread_id,
                item_name=cap_name,
                primary_location="Posizione da foto",
                category="generico"
            )
            db.add(item)
            db.flush()

        if not item:
            return {"error": "Specificare un oggetto fisico valido a cui associare la foto/documento."}

        if doc:
            item.document_id = doc.id
            item.image_path = doc.file_path
            doc.physical_item_id = item.id
        elif img_path:
            item.image_path = img_path

        db.commit()
        db.refresh(item)

        fn = Path(item.image_path).name if item.image_path else (Path(doc.file_path).name if doc and doc.file_path else None)
        doc_info = {
            "id": doc.id if doc else None,
            "document_id": doc.id if doc else None,
            "title": doc.title if doc else f"Foto {item.item_name}",
            "issuer": doc.issuer if doc else None,
            "amount": doc.amount if doc else None,
            "due_date": doc.due_date.isoformat() if doc and doc.due_date else None,
            "summary": doc.summary if doc else f"Foto della posizione di {item.item_name}",
            "file_url": f"/uploads/{fn}" if fn else None,
            "download_url": f"/api/documents/{doc.id}/download" if doc else None,
            "file_type": doc.file_type if doc else "image"
        } if (doc or fn) else None

        loc_str = item.primary_location + (f" ({item.detailed_location})" if item.detailed_location else "")
        return {
            "success": True,
            "item_id": item.id,
            "item_name": item.item_name,
            "location_str": loc_str,
            "document_id": doc.id if doc else None,
            "document_title": doc.title if doc else None,
            "image_url": f"/api/files/{fn}" if fn else None,
            "has_photo": bool(item.image_path or item.document_id),
            "document": doc_info,
            "documents": [doc_info] if doc_info else []
        }

    elif name == "delete_vault_record":
        target_type = args.get("target_type")
        target_id = args.get("target_id")
        title = args.get("title", "")
        target_ids = args.get("target_ids") or []
        category = args.get("category")

        is_bulk = (
            target_type == "bulk_documents"
            or (target_type not in ["document", "physical_item"] and any(k in (title or "").lower() for k in ["tutt", "tutte"]))
            or bool(target_ids and len(target_ids) > 1)
        )

        if is_bulk:
            target_type = "bulk_documents"
            query = db.query(Document)
            if thread_id and thread_id != "general" and thread_id != "all":
                query = query.filter(Document.thread_id == thread_id)

            clean_ref = f"{title or ''} {category or ''}".strip()
            is_total, target_kw = extract_bulk_delete_target(clean_ref)

            if target_ids:
                query = query.filter(Document.id.in_(target_ids))
                cat_name = f"{len(target_ids)} documenti selezionati"
            elif not is_total and target_kw:
                s_matches = search_vault_documents(db, target_kw, thread_id=thread_id)
                matched_ids = [m["id"] for m in s_matches]
                stem_kw = it_stem(target_kw)
                like_matches = query.filter(or_(
                    Document.title.ilike(f"%{target_kw}%"),
                    Document.doc_type.ilike(f"%{target_kw}%"),
                    Document.issuer.ilike(f"%{target_kw}%"),
                    Document.summary.ilike(f"%{target_kw}%"),
                    Document.title.ilike(f"%{stem_kw}%"),
                    Document.doc_type.ilike(f"%{stem_kw}%"),
                    Document.summary.ilike(f"%{stem_kw}%")
                )).all()
                for lm in like_matches:
                    if lm.id not in matched_ids:
                        matched_ids.append(lm.id)

                if matched_ids:
                    query = query.filter(Document.id.in_(matched_ids))
                    cat_name = f"documenti corrispondenti a '{target_kw}'"
                else:
                    return {
                        "error": f"Nessun documento trovato nel caveau corrispondente a '{target_kw}'.",
                        "status": "not_found"
                    }
            else:
                cat_name = "tutti i documenti"

            docs_to_delete = query.all()
            if not docs_to_delete:
                return {
                    "error": f"Nessun documento trovato da eliminare nel caveau ({cat_name}).",
                    "status": "not_found"
                }

            doc_ids = [d.id for d in docs_to_delete]
            doc_titles = [d.title for d in docs_to_delete]
            conf_title = title if (title and "tutt" in title.lower() and is_total) else (f"I {len(doc_ids)} {cat_name}" if len(doc_ids) > 1 else doc_titles[0])
            conf = {
                "type": "delete_confirmation",
                "target_type": "bulk_documents",
                "target_id": doc_ids[0],
                "target_ids": doc_ids,
                "title": conf_title,
                "details": f"Verranno eliminati definitivamente {len(doc_ids)} file dal caveau."
            }
            return {
                "confirmation": conf,
                "status": "pending_confirmation",
                "target_type": "bulk_documents",
                "target_id": doc_ids[0],
                "target_ids": doc_ids,
                "title": conf_title,
                "documents": [{
                    "document_id": d.id,
                    "title": d.title,
                    "issuer": d.issuer,
                    "amount": d.amount,
                    "due_date": d.due_date.isoformat() if d.due_date else None,
                    "summary": d.summary,
                    "file_url": f"/uploads/{Path(d.file_path).name}" if d.file_path else None,
                    "download_url": f"/api/documents/{d.id}/download",
                    "file_type": d.file_type
                } for d in docs_to_delete[:4]]
            }

        details = ""
        if target_type == "physical_item":
            rec = db.query(PhysicalItem).filter(PhysicalItem.id == target_id).first() if target_id else None
            if not rec and title:
                clean_t = re.sub(r"^(?:elimina|cancella|rimuovi|butta)\s*(?:il|la|lo|le|i|l'|un|una|uno)?\s*", "", title, flags=re.IGNORECASE).strip(" ?.")
                clean_t = re.sub(r"\s*(?:per favore|per cortesia|grazie)$", "", clean_t, flags=re.IGNORECASE).strip()
                s_items = search_vault_items(db, clean_t or title, thread_id=thread_id)
                if s_items:
                    rec = db.query(PhysicalItem).filter(PhysicalItem.id == (s_items[0].get("item_id") or s_items[0].get("id"))).first()
            if rec:
                target_id = rec.id
                title = rec.item_name
                details = f"Posizione: {rec.primary_location}" + (f" ({rec.detailed_location})" if rec.detailed_location else "")
        else:
            target_type = "document"
            rec = db.query(Document).filter(Document.id == target_id).first() if target_id else None
            if not rec and title:
                clean_t = re.sub(r"^(?:elimina|cancella|rimuovi|butta)\s*(?:il|la|lo|le|i|l'|un|una|uno)?\s*", "", title, flags=re.IGNORECASE).strip(" ?.")
                clean_t = re.sub(r"\s*(?:per favore|per cortesia|grazie)$", "", clean_t, flags=re.IGNORECASE).strip()
                s_res = search_vault_documents(db, clean_t or title, thread_id=thread_id)
                if s_res:
                    rec = db.query(Document).filter(Document.id == s_res[0]["id"]).first()
            if rec:
                target_id = rec.id
                title = rec.title
                details = rec.summary or rec.issuer or ""

        conf = {
            "type": "delete_confirmation",
            "target_type": target_type or "document",
            "target_id": target_id or 0,
            "title": title or "elemento",
            "details": details
        }
        return {
            "confirmation": conf,
            "status": "pending_confirmation",
            "target_type": target_type or "document",
            "target_id": target_id or 0,
            "title": title or "elemento"
        }

    elif name == "get_current_date":
        return get_current_date_info()

    elif name == "get_upcoming_deadlines":
        query_arg = (args.get("query") or "").strip().lower()
        if query_arg:
            # Se è specificata una query (es. "patente", "garanzia"), cerca tra tutti i documenti con scadenza a prescindere dallo stato
            matched_docs = search_vault_documents(db, query_arg, thread_id=thread_id)
            matched_ids = [m["id"] for m in matched_docs]
            docs = (
                db.query(Document)
                .filter(Document.id.in_(matched_ids), Document.due_date.isnot(None))
                .order_by(Document.due_date.asc().nulls_last())
                .all()
            )
            if not docs:
                docs = (
                    db.query(Document)
                    .filter(Document.due_date.isnot(None))
                    .order_by(Document.due_date.asc().nulls_last())
                    .all()
                )
                docs = [d for d in docs if query_arg in (d.title or "").lower() or query_arg in (d.summary or "").lower()]
        else:
            docs = db.query(Document).filter(Document.status == "da_pagare").order_by(Document.due_date.asc().nulls_last()).all()
        today = date.today()
        deadlines_list = []
        for d in docs:
            cat = categorize_deadline(d.due_date, today)
            deadlines_list.append({
                "id": d.id,
                "document_id": d.id,
                "title": d.title,
                "issuer": d.issuer,
                "amount": d.amount,
                "due_date": d.due_date.isoformat() if d.due_date else None,
                "days_remaining": cat["days_remaining"],
                "urgency": cat["urgency"],
                "urgency_label": cat["urgency_label"],
                "summary": d.summary,
                "file_url": f"/uploads/{Path(d.file_path).name}",
                "download_url": f"/api/documents/{d.id}/download",
                "file_type": d.file_type
            })
        return {
            "today": today.isoformat(),
            "deadlines_count": len(deadlines_list),
            "deadlines": deadlines_list,
            "upcoming_documents": deadlines_list
        }

    elif name == "list_vault_contents":
        target_type = args.get("target_type", "all")
        doc_items = []
        item_items = []

        if target_type in ["all", "documents"]:
            query_docs = db.query(Document)
            if thread_id and thread_id != "general" and thread_id != "all":
                query_docs = query_docs.filter(Document.thread_id == thread_id)
            docs = query_docs.order_by(Document.created_at.desc()).all()
            for d in docs:
                fn = Path(d.file_path).name if d.file_path else ""
                doc_items.append({
                    "id": d.id,
                    "document_id": d.id,
                    "title": d.title,
                    "issuer": d.issuer,
                    "amount": d.amount,
                    "due_date": d.due_date.isoformat() if d.due_date else None,
                    "summary": d.summary,
                    "doc_type": d.doc_type,
                    "status": d.status,
                    "file_url": f"/uploads/{fn}" if fn else None,
                    "download_url": f"/api/documents/{d.id}/download",
                    "file_type": d.file_type,
                    "drive_file_id": d.drive_file_id,
                    "drive_web_url": d.drive_web_url,
                    "is_on_drive": bool(d.drive_file_id or d.drive_web_url)
                })

        if target_type in ["all", "physical_items"]:
            query_items = db.query(PhysicalItem)
            if thread_id and thread_id != "general" and thread_id != "all":
                query_items = query_items.filter(PhysicalItem.thread_id == thread_id)
            items = query_items.order_by(PhysicalItem.updated_at.desc()).all()
            for it in items:
                loc = it.primary_location + (f" ({it.detailed_location})" if it.detailed_location else "")
                item_items.append({
                    "item_id": it.id,
                    "item_name": it.item_name,
                    "primary_location": it.primary_location,
                    "detailed_location": it.detailed_location,
                    "location_str": loc,
                    "category": it.category
                })

        return {
            "target_type": target_type,
            "documents_count": len(doc_items),
            "items_count": len(item_items),
            "documents": doc_items,
            "found_documents": doc_items,
            "physical_items": item_items,
            "found_physical_items": item_items
        }
    elif name == "rename_vault_document":
        new_title = (args.get("new_title") or "").strip()
        doc_id = args.get("document_id")
        if not new_title:
            return {"error": "Specificare un nuovo titolo valido per il documento."}

        doc = None
        if doc_id:
            doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            # Se non è specificato l'ID, cerca l'ultimo documento caricato nel canale corrente
            q = db.query(Document)
            if thread_id and thread_id not in ["general", "all"]:
                q = q.filter(Document.thread_id == thread_id)
            doc = q.order_by(Document.id.desc()).first()

        if not doc:
            return {"error": "Nessun documento trovato nel caveau da rinominare."}

        old_title = doc.title
        doc.title = new_title
        db.commit()
        db.refresh(doc)

        from app.services.calendar_service import auto_sync_calendar_event
        auto_sync_calendar_event(doc, db)

        fn = Path(doc.file_path).name if doc.file_path else ""
        doc_info = {
            "id": doc.id,
            "document_id": doc.id,
            "title": doc.title,
            "issuer": doc.issuer,
            "amount": doc.amount,
            "due_date": doc.due_date.isoformat() if doc.due_date else None,
            "summary": doc.summary,
            "doc_type": doc.doc_type,
            "status": doc.status,
            "file_url": f"/uploads/{fn}" if fn else None,
            "download_url": f"/api/documents/{doc.id}/download",
            "file_type": doc.file_type,
            "drive_file_id": doc.drive_file_id,
            "drive_web_url": doc.drive_web_url,
            "is_on_drive": bool(doc.drive_file_id or doc.drive_web_url)
        }

        return {
            "success": True,
            "document_id": doc.id,
            "old_title": old_title,
            "new_title": doc.title,
            "document": doc_info,
            "documents": [doc_info]
        }
    elif name == "recategorize_vault_document":
        category_label = (args.get("category_label") or "").strip()
        doc_id = args.get("document_id")
        doc_title = (args.get("document_title") or "").strip()
        category = (args.get("category") or "").strip()
        category_icon = (args.get("category_icon") or "").strip()
        subfolder = (args.get("subfolder") or "").strip()

        if not category_label:
            return {"error": "Specificare il nome della sezione o categoria (category_label).", "success": False}

        doc = None
        if doc_id:
            doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc and doc_title:
            s_docs = search_vault_documents(db, doc_title, thread_id=thread_id)
            if s_docs:
                doc = db.query(Document).filter(Document.id == s_docs[0]["id"]).first()
        if not doc:
            q = db.query(Document)
            if thread_id and thread_id not in ["general", "all"]:
                q = q.filter(Document.thread_id == thread_id)
            doc = q.order_by(Document.id.desc()).first()

        if not doc:
            return {"error": "Nessun documento trovato nel caveau da ricatalogare.", "success": False}

        old_label = doc.category_label or "Non categorizzato"
        from app.services.category_service import resolve_or_create_category_and_subfolder
        slug, label, icon, resolved_subfolder = resolve_or_create_category_and_subfolder(
            proposed_label=category_label,
            document_text=doc.summary,
            doc_type=doc.doc_type,
            due_date=doc.due_date,
            db=db,
            proposed_slug=category,
            proposed_icon=category_icon,
            proposed_subfolder=subfolder,
            filename=doc.file_path
        )
        doc.category = slug
        doc.category_label = label
        doc.category_icon = icon
        if resolved_subfolder:
            doc.subfolder = resolved_subfolder

        db.commit()
        db.refresh(doc)

        from app.services.calendar_service import auto_sync_calendar_event
        auto_sync_calendar_event(doc, db)

        fn = Path(doc.file_path).name if doc.file_path else ""
        doc_info = {
            "id": doc.id,
            "document_id": doc.id,
            "title": doc.title,
            "issuer": doc.issuer,
            "amount": doc.amount,
            "due_date": doc.due_date.isoformat() if doc.due_date else None,
            "summary": doc.summary,
            "doc_type": doc.doc_type,
            "status": doc.status,
            "category": doc.category,
            "category_label": doc.category_label,
            "category_icon": doc.category_icon,
            "subfolder": doc.subfolder,
            "file_url": f"/uploads/{fn}" if fn else None,
            "download_url": f"/api/documents/{doc.id}/download",
            "file_type": doc.file_type
        }

        sub_msg = f" (sottocartella: {doc.subfolder})" if doc.subfolder else ""
        return {
            "success": True,
            "document_id": doc.id,
            "title": doc.title,
            "old_category_label": old_label,
            "new_category_label": doc.category_label,
            "category": doc.category,
            "category_icon": doc.category_icon,
            "subfolder": doc.subfolder,
            "message": f"Documento '{doc.title}' spostato con successo nella sezione '{doc.category_label}'{sub_msg}.",
            "document": doc_info,
            "documents": [doc_info]
        }
    elif name == "show_document_card":
        doc_id = args.get("document_id")
        doc_ids = args.get("document_ids") or []
        doc_title = (args.get("document_title") or args.get("query") or "").strip()
        doc_titles = args.get("document_titles") or []

        docs = []
        # 1. Raccogli per document_ids
        if doc_ids:
            for did in doc_ids:
                try:
                    d = db.query(Document).filter(Document.id == int(did)).first()
                    if d and d not in docs:
                        docs.append(d)
                except Exception:
                    pass

        # 2. Raccogli per document_titles
        if doc_titles:
            for dt in doc_titles:
                matches = search_vault_documents(db, str(dt).strip(), thread_id=thread_id)
                if matches:
                    top_id = matches[0]["id"]
                    d = db.query(Document).filter(Document.id == top_id).first()
                    if d and d not in docs:
                        docs.append(d)

        # 3. Singolo ID
        if not docs and doc_id:
            try:
                d = db.query(Document).filter(Document.id == int(doc_id)).first()
                if d:
                    docs.append(d)
            except Exception:
                pass

        # 4. Singolo titolo o query di ricerca
        if not docs and doc_title:
            matches = search_vault_documents(db, doc_title, thread_id=thread_id)
            if matches:
                for m in matches[:4]:
                    d = db.query(Document).filter(Document.id == m["id"]).first()
                    if d and d not in docs:
                        docs.append(d)

        # 5. Se nessun parametro, recupera i documenti contestuali dall'ultimo messaggio dell'assistente nel canale
        if not docs and not doc_id and not doc_ids and not doc_title and not doc_titles:
            last_asst = (
                db.query(ChatMessage)
                .filter(ChatMessage.thread_id == thread_id, ChatMessage.sender == "assistant")
                .order_by(ChatMessage.id.desc())
                .first()
            )
            if last_asst:
                if last_asst.metadata_json:
                    try:
                        m_json = json.loads(last_asst.metadata_json)
                        m_docs = m_json.get("documents") or (m_json.get("data") or {}).get("deadlines") or (m_json.get("data") or {}).get("upcoming_documents")
                        if m_docs:
                            for md in m_docs:
                                md_id = md.get("id") or md.get("document_id")
                                if md_id:
                                    d_obj = db.query(Document).filter(Document.id == int(md_id)).first()
                                    if d_obj and d_obj not in docs:
                                        docs.append(d_obj)
                    except Exception:
                        pass
                if not docs and last_asst.content:
                    all_d = db.query(Document).order_by(Document.created_at.desc()).all()
                    for d_cand in all_d:
                        if d_cand.title and len(d_cand.title) >= 3 and d_cand.title.lower() in last_asst.content.lower():
                            if d_cand not in docs:
                                docs.append(d_cand)
                        elif d_cand.issuer and len(d_cand.issuer) >= 3 and d_cand.issuer.lower() in last_asst.content.lower():
                            if d_cand not in docs:
                                docs.append(d_cand)
                        elif d_cand.amount and (f"{d_cand.amount:.2f}".replace('.', ',') in last_asst.content or f"{d_cand.amount:.2f}" in last_asst.content):
                            if d_cand not in docs:
                                docs.append(d_cand)
                    if not docs and any(k in last_asst.content.lower() for k in ["scadenz", "bollett", "da pagare", "f24", "tribut"]):
                        unpaid = db.query(Document).filter(Document.status == "da_pagare").order_by(Document.due_date.asc().nulls_last()).all()
                        for ud in unpaid:
                            if ud not in docs:
                                docs.append(ud)

            if not docs:
                q = db.query(Document)
                if thread_id and thread_id not in ["general", "all"]:
                    q = q.filter(Document.thread_id == thread_id)
                last_d = q.order_by(Document.id.desc()).first()
                if last_d:
                    docs.append(last_d)

        if not docs:
            return {"error": "Nessun documento trovato nel caveau da visualizzare.", "found": False}

        docs_info = []
        for d in docs:
            fn = Path(d.file_path).name if d.file_path else ""
            docs_info.append({
                "id": d.id,
                "document_id": d.id,
                "thread_id": d.thread_id,
                "title": d.title,
                "issuer": d.issuer,
                "amount": d.amount,
                "due_date": d.due_date.isoformat() if d.due_date else None,
                "summary": d.summary,
                "doc_type": d.doc_type,
                "status": d.status,
                "file_url": f"/uploads/{fn}" if fn else None,
                "download_url": f"/api/documents/{d.id}/download",
                "file_type": d.file_type,
                "drive_file_id": d.drive_file_id,
                "drive_web_url": d.drive_web_url,
                "is_on_drive": bool(d.drive_file_id or d.drive_web_url)
            })

        return {
            "success": True,
            "document": docs_info[0],
            "documents": docs_info,
            "found_documents": docs_info
        }

    elif name == "scan_local_folder":
        from app.services.folder_service import scan_local_folder as do_scan_folder
        f_path = (args.get("folder_path") or "").strip()
        results = []
        if f_path and f_path.lower() != "all":
            res = do_scan_folder(f_path, db, thread_id=thread_id)
            results.append(res)
        else:
            watched = db.query(WatchedFolder).filter(WatchedFolder.is_active == True).all()
            if not watched:
                return {
                    "error": "Nessuna cartella del PC è attualmente configurata per il monitoraggio. Puoi aggiungerne una dalla Dashboard o indicare un percorso specifico (es. C:\\Documenti).",
                    "folders_count": 0
                }
            for wf in watched:
                res = do_scan_folder(wf.path, db, thread_id=wf.thread_id or thread_id, watched_folder_id=wf.id)
                results.append(res)

        total_new = sum(r.new_indexed_count for r in results)
        total_scanned = sum(r.scanned_files_count for r in results)
        total_skipped = sum(r.skipped_count for r in results)
        total_errors = sum(r.error_count for r in results)

        return {
            "success": True,
            "total_scanned": total_scanned,
            "total_new_indexed": total_new,
            "total_skipped": total_skipped,
            "total_errors": total_errors,
            "folders_processed": [
                {
                    "path": r.folder_path,
                    "scanned": r.scanned_files_count,
                    "new": r.new_indexed_count,
                    "skipped": r.skipped_count,
                    "details": r.details[:5]
                }
                for r in results
            ]
        }

    elif name == "list_watched_folders":
        folders = db.query(WatchedFolder).all()
        return {
            "watched_folders_count": len(folders),
            "folders": [
                {
                    "id": f.id,
                    "name": f.name,
                    "path": f.path,
                    "thread_id": f.thread_id,
                    "file_count": f.file_count,
                    "last_scanned_at": f.last_scanned_at.isoformat() if f.last_scanned_at else "Mai",
                    "is_active": f.is_active
                }
                for f in folders
            ]
        }

    elif name == "open_local_file_in_explorer":
        from app.services.folder_service import open_path_in_explorer, prepare_document_for_local_open
        doc_id = args.get("document_id")
        doc_title = (args.get("document_title") or "").strip()
        path_arg = (args.get("path") or "").strip()

        target_path = None
        matched_doc = None
        if doc_id:
            matched_doc = db.query(Document).filter(Document.id == doc_id).first()
        elif doc_title:
            matches = search_vault_documents(db, doc_title, thread_id=thread_id)
            if matches:
                matched_doc = db.query(Document).filter(Document.id == matches[0]["id"]).first()

        if matched_doc:
            try:
                target_path = prepare_document_for_local_open(matched_doc)
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Errore decifratura per apertura locale: {e}"
                }
        elif path_arg:
            target_path = path_arg

        if not target_path or not Path(target_path).exists():
            return {
                "success": False,
                "error": f"File o cartella non trovata sul computer: {target_path or doc_title or doc_id}"
            }

        opened = open_path_in_explorer(target_path, open_file=True)
        return {
            "success": opened,
            "path": target_path,
            "title": matched_doc.title if matched_doc else Path(target_path).name,
            "message": f"Aperto '{Path(target_path).name}' sul computer." if opened else "Impossibile aprire Esplora File."
        }

    elif name == "create_zip_archive":
        from app.services.archive_service import create_zip_from_documents
        doc_ids = args.get("document_ids")
        query = args.get("query")
        category = args.get("category")
        archive_name = args.get("archive_name")

        zip_doc = create_zip_from_documents(
            db=db,
            document_ids=doc_ids,
            query=query,
            category=category,
            archive_title=archive_name,
            thread_id=thread_id
        )
        if not zip_doc:
            return {
                "success": False,
                "message": "Nessun documento trovato corrispondente ai criteri per creare l'archivio ZIP."
            }
        fn = Path(zip_doc.file_path).name if zip_doc.file_path else "archivio.zip"
        return {
            "success": True,
            "message": f"Archivio ZIP '{zip_doc.title}' creato con successo.",
            "zip_document_id": zip_doc.id,
            "title": zip_doc.title,
            "file_url": f"/uploads/{fn}",
            "download_url": f"/api/documents/{zip_doc.id}/download",
            "summary": zip_doc.summary,
            "document": {
                "id": zip_doc.id,
                "document_id": zip_doc.id,
                "title": zip_doc.title,
                "issuer": zip_doc.issuer,
                "doc_type": zip_doc.doc_type,
                "amount": None,
                "due_date": None,
                "status": "archiviato",
                "summary": zip_doc.summary,
                "file_url": f"/uploads/{fn}",
                "download_url": f"/api/documents/{zip_doc.id}/download",
                "file_type": "zip"
            }
        }

    elif name == "unzip_vault_archive":
        from app.services.archive_service import unzip_document_to_vault
        doc_id = args.get("document_id")
        doc_title = args.get("document_title")

        extracted = unzip_document_to_vault(
            db=db,
            document_id=doc_id,
            document_title=doc_title,
            thread_id=thread_id
        )
        if not extracted:
            return {
                "success": False,
                "message": "Impossibile estrarre l'archivio ZIP o nessun file valido trovato all'interno."
            }
        return {
            "success": True,
            "message": f"Estratti con successo {len(extracted)} documenti dall'archivio ZIP.",
            "extracted_count": len(extracted),
            "extracted_documents": [
                {
                    "id": d.id,
                    "document_id": d.id,
                    "title": d.title,
                    "issuer": d.issuer,
                    "doc_type": d.doc_type,
                    "category": d.category,
                    "category_label": d.category_label,
                    "category_icon": d.category_icon,
                    "amount": d.amount,
                    "due_date": d.due_date.isoformat() if d.due_date else None,
                    "status": d.status,
                    "summary": d.summary,
                    "file_url": f"/uploads/{Path(d.file_path).name}" if d.file_path else None,
                    "download_url": f"/api/documents/{d.id}/download",
                    "file_type": d.file_type
                }
                for d in extracted
            ]
        }

    elif name == "get_google_drive_status":
        cred = db.query(GoogleDriveCredential).first() if db else None
        if not cred:
            return {
                "connected": False,
                "message": "Google Drive non è attualmente collegato. L'utente può collegarlo in ogni momento dal menu Strumenti -> ☁️ Google Drive Cloud Sync.",
                "root_folder": "DoveLoAIMesso",
                "folder_structure_rules": {
                    "with_due_date": "DoveLoAIMesso / <Anno> / <Categoria> / <NomeFile>",
                    "without_due_date": "DoveLoAIMesso / <Categoria> / <NomeFile>"
                },
                "standard_categories": [
                    "Bollette & Utenze",
                    "Fisco & Tasse",
                    "Fatture & Spese",
                    "Contratti & Polizze",
                    "Documenti & Foto"
                ],
                "categories": [
                    "Bollette & Utenze",
                    "Fisco & Tasse",
                    "Fatture & Spese",
                    "Contratti & Polizze",
                    "Documenti & Foto"
                ],
                "total_files_on_drive": 0,
                "matching_files": [],
                "folders_overview": {},
                "documents": []
            }

        query = (args.get("query") or "").strip().lower()
        q_drive = db.query(Document).filter(
            or_(Document.drive_file_id.isnot(None), Document.drive_web_url.isnot(None))
        )
        if thread_id and thread_id not in ["general", "all"]:
            q_drive = q_drive.filter(Document.thread_id == thread_id)

        drive_docs = q_drive.order_by(Document.id.desc()).all()

        files_list = []
        folders_overview = {}
        for d in drive_docs:
            if getattr(d, "drive_folder_path", None):
                folder_str = d.drive_folder_path
                folder_parts = folder_str.split(" / ")
            else:
                folder_parts = resolve_drive_folder_path(d.doc_type, d.due_date)
                folder_str = " / ".join(folder_parts)
            fn = Path(d.file_path).name if d.file_path else ""
            doc_title = (d.title or "").strip() or fn or f"Documento #{d.id}"
            folders_overview.setdefault(folder_str, []).append(doc_title)

            if query and (
                query not in doc_title.lower()
                and query not in folder_str.lower()
                and query not in (d.summary or "").lower()
                and query not in (d.doc_type or "").lower()
            ):
                continue

            files_list.append({
                "id": d.id,
                "document_id": d.id,
                "thread_id": d.thread_id,
                "title": doc_title,
                "issuer": d.issuer,
                "doc_type": d.doc_type,
                "amount": d.amount,
                "due_date": d.due_date.isoformat() if d.due_date else None,
                "status": d.status,
                "summary": d.summary,
                "folder_path": folder_str,
                "folder_parts": folder_parts,
                "drive_file_id": d.drive_file_id,
                "drive_web_url": d.drive_web_url,
                "is_on_drive": True,
                "file_url": f"/uploads/{fn}" if fn else None,
                "download_url": f"/api/documents/{d.id}/download",
                "file_type": d.file_type
            })

        if cred.storage_mode == "local_only":
            mode_desc = "Solo Locale nel Caveau (i file vengono cifrati e salvati esclusivamente sul tuo computer locale, nessun caricamento su Google Drive)"
        elif cred.storage_mode == "cloud_only":
            mode_desc = "Solo Google Drive (i file fisici risiedono su Google Drive, metadati nel caveau)"
        else:
            mode_desc = "Copia locale cifrata nel caveau + Google Drive (doppia copia)"

        return {
            "connected": True,
            "user_email": cred.user_email,
            "storage_mode": cred.storage_mode,
            "storage_mode_description": mode_desc,
            "root_folder": "DoveLoAIMesso",
            "folder_structure_rules": {
                "with_due_date": "DoveLoAIMesso / <Anno> / <Categoria> / <NomeFile>",
                "without_due_date": "DoveLoAIMesso / <Categoria> / <NomeFile>"
            },
            "standard_categories": [
                "Bollette & Utenze",
                "Fisco & Tasse",
                "Fatture & Spese",
                "Contratti & Polizze",
                "Documenti & Foto"
            ],
            "categories": [
                "Bollette & Utenze",
                "Fisco & Tasse",
                "Fatture & Spese",
                "Contratti & Polizze",
                "Documenti & Foto"
            ],
            "total_files_on_drive": len(drive_docs),
            "matching_files_count": len(files_list),
            "matching_files": files_list,
            "folders_overview": folders_overview,
            "documents": files_list
        }

    elif name == "read_vault_document_content":
        from app.services.archive_service import inspect_document_content
        from app.services.document_service import read_decrypted_file

        doc_id = args.get("document_id")
        doc_title = (args.get("document_title") or "").strip()
        sheet_name = args.get("sheet_name")
        query = args.get("query")
        max_rows = args.get("max_rows", 50)

        doc = None
        if doc_id:
            doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc and doc_title:
            s_docs = search_vault_documents(db, doc_title, thread_id=thread_id)
            if s_docs:
                doc = db.query(Document).filter(Document.id == s_docs[0]["id"]).first()
        if not doc and query:
            s_docs = search_vault_documents(db, query, thread_id=thread_id)
            if s_docs:
                doc = db.query(Document).filter(Document.id == s_docs[0]["id"]).first()
        if not doc:
            # Cerca prioritariamente file Excel o tabelle nel caveau
            q_excel = db.query(Document).filter(
                or_(
                    Document.file_type.in_(["xlsx", "xls", "csv"]),
                    Document.file_path.ilike("%.xlsx"),
                    Document.file_path.ilike("%.xls"),
                    Document.file_path.ilike("%.csv")
                )
            )
            if thread_id and thread_id not in ["general", "all"]:
                q_excel = q_excel.filter(Document.thread_id == thread_id)
            doc = q_excel.order_by(Document.id.desc()).first()

        if not doc:
            q_any = db.query(Document)
            if thread_id and thread_id not in ["general", "all"]:
                q_any = q_any.filter(Document.thread_id == thread_id)
            doc = q_any.order_by(Document.id.desc()).first()

        if not doc:
            return {
                "success": False,
                "error": "Nessun documento trovato nel caveau da leggere.",
                "message": "Nessun documento trovato nel caveau corrispondente ai criteri specificati."
            }

        if not doc.file_path or not Path(doc.file_path).exists():
            return {
                "success": False,
                "error": f"Il file fisico del documento '{doc.title}' non è presente su disco.",
                "document_id": doc.id,
                "document_title": doc.title
            }

        doc_fn = Path(doc.file_path).name if doc.file_path else ""
        doc_item = {
            "id": doc.id,
            "document_id": doc.id,
            "title": doc.title,
            "issuer": doc.issuer,
            "amount": doc.amount,
            "due_date": doc.due_date.isoformat() if doc.due_date else None,
            "status": doc.status,
            "file_url": f"/uploads/{doc_fn}" if doc_fn else None,
            "download_url": f"/api/documents/{doc.id}/download",
            "file_type": doc.file_type,
            "summary": doc.summary,
            "drive_file_id": doc.drive_file_id,
            "drive_web_url": doc.drive_web_url,
            "category": doc.category,
            "category_label": doc.category_label,
            "category_icon": doc.category_icon
        }

        try:
            file_bytes = read_decrypted_file(doc.file_path)
            result = inspect_document_content(
                file_bytes=file_bytes,
                file_type=doc.file_type or "",
                filename=Path(doc.file_path).name or doc.title or "file",
                sheet_name=sheet_name,
                query=query,
                max_rows=max_rows
            )
            result["document_id"] = doc.id
            result["document_title"] = doc.title
            result["documents"] = [doc_item]
            result["document"] = doc_item

            if not result.get("success"):
                if doc.summary:
                    meta_parts = []
                    if doc.title:
                        meta_parts.append(f"**Titolo Documento**: {doc.title}")
                    if doc.doc_type:
                        meta_parts.append(f"**Tipo Documento**: {doc.doc_type}")
                    if doc.issuer:
                        meta_parts.append(f"**Emittente / Mittente**: {doc.issuer}")
                    if doc.amount is not None:
                        meta_parts.append(f"**Importo**: €{doc.amount:.2f}")
                    if doc.due_date:
                        meta_parts.append(f"**Scadenza**: {doc.due_date.isoformat()}")
                    if doc.summary:
                        meta_parts.append(f"**Contenuto ed Estrazione AI**:\n{doc.summary}")
                    if doc.category_label:
                        meta_parts.append(f"**Sezione**: {doc.category_label}")

                    return {
                        "success": True,
                        "filename": Path(doc.file_path).name if doc.file_path else doc.title,
                        "file_type": doc.file_type or "pdf",
                        "content_text": "### Scheda Informativa ed Analisi Ottica AI del Documento:\n" + "\n".join(meta_parts),
                        "summary": doc.summary,
                        "document_id": doc.id,
                        "document_title": doc.title,
                        "documents": [doc_item],
                        "document": doc_item
                    }
                return result

            text_val = (result.get("content_text") or "").strip()
            if not text_val or text_val.startswith("_Nessun testo") or "scansione fotografica" in text_val:
                meta_parts = []
                if doc.title:
                    meta_parts.append(f"**Titolo Documento**: {doc.title}")
                if doc.doc_type:
                    meta_parts.append(f"**Tipo Documento**: {doc.doc_type}")
                if doc.issuer:
                    meta_parts.append(f"**Emittente / Mittente**: {doc.issuer}")
                if doc.amount is not None:
                    meta_parts.append(f"**Importo**: €{doc.amount:.2f}")
                if doc.due_date:
                    meta_parts.append(f"**Scadenza**: {doc.due_date.isoformat()}")
                if doc.summary:
                    meta_parts.append(f"**Contenuto ed Estrazione AI**:\n{doc.summary}")
                if doc.category_label:
                    meta_parts.append(f"**Sezione**: {doc.category_label}")

                if meta_parts:
                    prefix = f"{text_val}\n\n" if text_val and not text_val.startswith("_Nessun testo") else ""
                    result["content_text"] = (
                        prefix +
                        "### Scheda Informativa ed Analisi Ottica AI del Documento:\n" +
                        "\n".join(meta_parts)
                    )
            return result
        except Exception as e:
            logger.error(f"Errore lettura contenuto documento {doc.id}: {e}", exc_info=True)
            if doc and doc.summary:
                meta_parts = []
                if doc.title:
                    meta_parts.append(f"**Titolo Documento**: {doc.title}")
                if doc.doc_type:
                    meta_parts.append(f"**Tipo Documento**: {doc.doc_type}")
                if doc.issuer:
                    meta_parts.append(f"**Emittente / Mittente**: {doc.issuer}")
                if doc.amount is not None:
                    meta_parts.append(f"**Importo**: €{doc.amount:.2f}")
                if doc.due_date:
                    meta_parts.append(f"**Scadenza**: {doc.due_date.isoformat()}")
                if doc.summary:
                    meta_parts.append(f"**Contenuto ed Estrazione AI**:\n{doc.summary}")
                if doc.category_label:
                    meta_parts.append(f"**Sezione**: {doc.category_label}")
                return {
                    "success": True,
                    "filename": Path(doc.file_path).name if doc.file_path else doc.title,
                    "file_type": doc.file_type or "pdf",
                    "content_text": "### Scheda Informativa ed Analisi Ottica AI del Documento:\n" + "\n".join(meta_parts),
                    "summary": doc.summary,
                    "document_id": doc.id,
                    "document_title": doc.title,
                    "documents": [doc_item],
                    "document": doc_item
                }
            return {
                "success": False,
                "error": str(e),
                "document_id": doc.id,
                "document_title": doc.title
            }

    return {"error": f"Strumento non riconosciuto: {name}"}
