"""
Modulo di gestione archivi ZIP: esportazione, backup e decompressione sicura con catalogazione nel Caveau.
"""
import io
import re
import json
import zipfile
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, date, timezone
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.database import Document
from app.models.schemas import ExtractedDocument
from app.services.document_service import save_uploaded_file, read_decrypted_file, determine_document_status
from app.services.archive.inspectors import extract_text_from_office_file
from app.services.archive.metadata import fast_extract_document_metadata

logger = logging.getLogger(__name__)

def _get_ai_service_resolver(db=None):
    import app.services.archive_service as archive_service
    if hasattr(archive_service, "get_ai_service"):
        return archive_service.get_ai_service(db)
    from app.services.ai_service import get_ai_service as _direct_get_ai
    return _direct_get_ai(db)

def create_zip_from_documents(
    db: Session,
    document_ids: Optional[List[int]] = None,
    query: Optional[str] = None,
    category: Optional[str] = None,
    archive_title: Optional[str] = None,
    thread_id: str = "general"
) -> Optional[Document]:
    """
    Crea un nuovo file compresso ZIP a partire da una selezione di documenti presenti nel caveau,
    lo salva cifrato nel caveau e crea il relativo record Document in SQLite.
    """
    q = db.query(Document)
    if thread_id and thread_id != "all":
        q = q.filter(Document.thread_id == thread_id)

    all_docs = q.order_by(Document.created_at.desc()).all()
    if document_ids:
        docs = [d for d in all_docs if d.id in document_ids]
    elif query and query.strip().lower() not in ["all", "tutti", "tutto", "*"]:
        from app.services.search_service import search_vault_documents
        matches = search_vault_documents(db, query, thread_id=thread_id)
        matched_ids = {m["id"] for m in matches}
        docs = [d for d in all_docs if d.id in matched_ids]
        if not docs:
            q_lower = query.strip().lower()
            docs = [
                d for d in all_docs
                if q_lower in (d.title or "").lower()
                or q_lower in (d.summary or "").lower()
                or q_lower in (d.issuer or "").lower()
                or q_lower in (d.doc_type or "").lower()
                or q_lower in Path(d.file_path or "").name.lower()
            ]
    elif category and category.strip().lower() != "all":
        cat_lower = category.strip().lower()
        docs = [d for d in all_docs if (d.doc_type or "").lower() == cat_lower]
    else:
        docs = all_docs

    if not docs:
        logger.warning("Nessun documento trovato per la creazione dello ZIP")
        return None

    zip_buffer = io.BytesIO()
    included_names = []

    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1. Includi ciascun file decifrato
        for d in docs:
            if not d.file_path:
                continue
            fp = Path(d.file_path)
            if not fp.exists():
                continue
            try:
                decrypted = read_decrypted_file(fp)
                # Crea un nome descrittivo pulito
                ext = fp.suffix or (f".{d.file_type}" if d.file_type else ".bin")
                clean_name = f"{d.id}_{d.title[:40].replace(' ', '_').replace('/', '_')}{ext}"
                zf.writestr(clean_name, decrypted)
                included_names.append(d.title)
            except Exception as e:
                logger.warning(f"Errore aggiunta {d.title} allo ZIP: {e}")

        # 2. Aggiungi un file indice riassuntivo all'interno dello ZIP
        index_txt = f"Archivio creato da Dove lo AI messo in data {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
        index_txt += f"Documenti inclusi ({len(included_names)}):\n"
        for idx, name in enumerate(included_names, 1):
            index_txt += f"{idx}. {name}\n"
        zf.writestr("INDICE_DOCUMENTI.txt", index_txt.encode("utf-8"))

    zip_buffer.seek(0)
    zip_bytes = zip_buffer.getvalue()

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    default_name = f"Archivio_{len(included_names)}_documenti_{ts}.zip"
    final_title = (archive_title or default_name).strip()
    if not final_title.lower().endswith(".zip"):
        final_filename = f"{final_title}.zip"
    else:
        final_filename = final_title

    saved_path = save_uploaded_file(zip_bytes, final_filename)

    summary_desc = f"Archivio compresso contenente {len(included_names)} documenti: {', '.join(included_names[:4])}"
    if len(included_names) > 4:
        summary_desc += f" e altri {len(included_names) - 4} file."

    zip_doc = Document(
        thread_id=thread_id,
        title=final_title.replace(".zip", "").replace("_", " "),
        file_path=saved_path,
        file_type="zip",
        doc_type="archivio_zip",
        issuer="Dove lo AI messo",
        amount=None,
        due_date=None,
        status="archiviato",
        summary=summary_desc,
        category="archivi_zip",
        category_label="Archivi Compressi & ZIP",
        category_icon="fa-file-zipper",
        created_at=datetime.now(timezone.utc)
    )
    db.add(zip_doc)
    db.commit()
    db.refresh(zip_doc)

    return zip_doc




def unzip_document_to_vault(
    db: Session,
    document_id: Optional[int] = None,
    document_title: Optional[str] = None,
    thread_id: str = "general"
) -> List[Document]:
    """
    Estrae tutti i file contenuti all'interno di un documento ZIP del caveau,
    analizza istantaneamente ciascun file con parser ad altissima velocità e registra i nuovi documenti nel database.
    """
    doc = None
    if document_id:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            logger.warning(f"Nessun documento ZIP trovato con ID {document_id}")
            return []
    elif document_title:
        term = document_title.strip().lower()
        clean_term = re.sub(r"\.zip$", "", term).strip()
        term_spaced = re.sub(r"[_\-]+", " ", term).strip()
        clean_spaced = re.sub(r"[_\-]+", " ", clean_term).strip()
        term_words = [w for w in re.split(r"[_\W]+", clean_term) if len(w) > 2 and w not in ["zip", "archivio", "file"]]

        all_zips = db.query(Document).filter(
            or_(Document.file_type == "zip", Document.doc_type == "archivio_zip")
        ).all()
        doc = next((
            d for d in all_zips 
            if term in (d.title or "").lower() 
            or term in (d.summary or "").lower()
            or (d.file_path and term in Path(d.file_path).name.lower())
            or (clean_term and clean_term in (d.title or "").lower())
            or (clean_spaced and clean_spaced in (d.title or "").lower())
            or (term_spaced and term_spaced in (d.title or "").lower())
            or (term_words and all(w in (d.title or "").lower() for w in term_words))
            or (d.file_path and clean_term and clean_term in Path(d.file_path).name.lower())
        ), None)
        if not doc and clean_spaced in ["", "zip", "archivio", "file", "file zip", "archivio zip", "lo zip", "l archivio", "l'archivio"]:
            # Se il termine fornito era puramente generico (es. 'zip' o 'archivio'), lascia procedere al fallback dell'ultimo zip
            pass
        elif not doc:
            logger.warning(f"Nessun documento ZIP trovato con titolo o file '{document_title}'")
            return []

    if not doc:
        # Cerca l'ultimo zip caricato (priorità al canale/thread attuale se specificato)
        q_zip = db.query(Document).filter(
            or_(Document.file_type == "zip", Document.doc_type == "archivio_zip")
        )
        if thread_id and thread_id != "general" and thread_id != "all":
            doc = q_zip.filter(Document.thread_id == thread_id).order_by(Document.created_at.desc()).first()
        if not doc:
            doc = q_zip.order_by(Document.created_at.desc()).first()


    if not doc or not doc.file_path:
        logger.warning(f"Nessun documento ZIP trovato con ID {document_id}")
        return []

    fp = Path(doc.file_path)
    if not fp.exists():
        logger.warning(f"File zip {fp} non trovato su disco")
        return []

    zip_bytes = read_decrypted_file(fp)
    extracted_docs: List[Document] = []

    active_cred = None
    try:
        from app.models.database import GoogleDriveCredential
        active_cred = db.query(GoogleDriveCredential).first()
    except Exception:
        pass

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            for info in zf.infolist():
                # Salta directory e file nascosti di sistema
                if info.is_dir() or "__MACOSX" in info.filename or Path(info.filename).name.startswith("."):
                    continue
                # Salta file di indice generati
                if Path(info.filename).name == "INDICE_DOCUMENTI.txt":
                    continue

                raw_inner_bytes = zf.read(info.filename)
                if not raw_inner_bytes:
                    continue

                inner_filename = Path(info.filename).name
                saved_path = save_uploaded_file(raw_inner_bytes, inner_filename)

                file_ext = Path(inner_filename).suffix.lstrip(".").lower() or "bin"
                mime = "application/pdf" if file_ext == "pdf" else (
                    f"image/{file_ext}" if file_ext in ["jpg", "jpeg", "png", "webp"] else "application/octet-stream"
                )

                # Analisi puntuale di ciascun file con motore multimodale AI
                ai_service = _get_ai_service_resolver(db)
                try:
                    extracted = ai_service.extract_document(
                        file_bytes=raw_inner_bytes,
                        mime_type=mime,
                        filename=inner_filename
                    )
                except Exception as ai_err:
                    logger.warning(f"Errore estrazione AI per '{inner_filename}': {ai_err}. Uso parser di fallback.")
                    extracted = fast_extract_document_metadata(raw_inner_bytes, inner_filename, mime)

                due_date_obj = None
                if extracted.due_date:
                    try:
                        due_date_obj = datetime.strptime(extracted.due_date, "%Y-%m-%d").date()
                    except ValueError:
                        due_date_obj = None

                title = (extracted.title or "").strip()
                if not title:
                    clean_stem = Path(inner_filename).stem.replace("_", " ").strip()
                    title = clean_stem.capitalize()

                doc_status = determine_document_status(extracted, due_date_obj)

                # Sincronizzazione automatica con Google Drive se attivo (e non solo locale)
                drive_file_id = None
                drive_web_url = None
                drive_folder_str = None
                if active_cred and getattr(active_cred, "storage_mode", "dual") != "local_only":
                    try:
                        from app.services.drive_service import get_drive_service, resolve_drive_folder_path, sanitize_drive_folder_name
                        from app.models.database import ChatThread

                        chat_folder = "Generale"
                        if thread_id and thread_id not in ("general", "all"):
                            th = db.query(ChatThread).filter(ChatThread.id == thread_id).first()
                            chat_folder = sanitize_drive_folder_name(th.name if th else thread_id, thread_id=thread_id)

                        drive_service = get_drive_service()
                        folder_path = resolve_drive_folder_path(
                            extracted.doc_type,
                            due_date_obj,
                            category_label=extracted.category_label,
                            subfolder=extracted.subfolder,
                            chat_folder=chat_folder,
                        )
                        drive_res = drive_service.upload_file(
                            file_bytes=raw_inner_bytes,
                            filename=inner_filename,
                            mime_type=mime,
                            folder_path=folder_path,
                            access_token=active_cred.access_token
                        )
                        drive_file_id = drive_res.get("file_id")
                        drive_web_url = drive_res.get("web_view_link")
                        drive_folder_str = " / ".join(folder_path) if drive_file_id else None
                    except Exception as drive_err:
                        logger.warning(f"Errore upload Drive per '{inner_filename}': {drive_err}")
                        drive_folder_str = None

                new_doc = Document(
                    thread_id=thread_id,
                    title=title,
                    file_path=saved_path,
                    file_type=file_ext,
                    doc_type=extracted.doc_type,
                    issuer=extracted.issuer,
                    amount=extracted.amount,
                    due_date=due_date_obj,
                    status=doc_status,
                    summary=extracted.summary,
                    category=extracted.category,
                    category_label=extracted.category_label,
                    category_icon=extracted.category_icon,
                    subfolder=extracted.subfolder,
                    drive_file_id=drive_file_id,
                    drive_web_url=drive_web_url,
                    drive_folder_path=drive_folder_str,
                    created_at=datetime.now(timezone.utc)
                )
                db.add(new_doc)
                extracted_docs.append(new_doc)

        db.commit()
        from app.services.calendar_service import auto_sync_calendar_event
        for d in extracted_docs:
            db.refresh(d)
            if d.due_date:
                try:
                    auto_sync_calendar_event(d, db)
                except Exception as sync_err:
                    logger.warning(f"Errore sincronizzazione calendar per doc decompresso #{d.id}: {sync_err}")

    except Exception as e:
        logger.error(f"Errore durante l'unzip di {doc.title}: {e}")

    return extracted_docs
