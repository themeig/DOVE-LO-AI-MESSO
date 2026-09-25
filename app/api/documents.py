import json
import logging
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.database import get_db, Document, ChatMessage, GoogleDriveCredential, get_app_setting, ChatThread
from app.models.schemas import DocumentStatusUpdate, BulkDeleteRequest, BulkDeleteResponse, UnzipVaultRequest
from app.services.ai_service import get_ai_service
from app.services.document_service import save_uploaded_file, read_decrypted_file, determine_document_status
from app.services.drive_service import get_drive_service, resolve_drive_folder_path, sanitize_drive_folder_name

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])



def _process_and_save_single_doc(
    contents: bytes,
    filename: str,
    content_type: str,
    thread_id: str,
    db: Session
) -> Document:
    # 1. Read file contents and save to disk
    saved_path = save_uploaded_file(contents, filename)

    # 2. Extract structured data with AI service
    ai_service = get_ai_service()
    extracted = ai_service.extract_document(contents, content_type, filename=filename)

    # 3. Parse due_date (YYYY-MM-DD -> date)
    due_date_obj = None
    if extracted.due_date:
        try:
            due_date_obj = datetime.strptime(extracted.due_date, "%Y-%m-%d").date()
        except ValueError:
            due_date_obj = None

    # 4. Determine file type and title
    file_ext = Path(filename).suffix.lstrip(".").lower() or "bin"
    title = (extracted.title or "").strip()
    if not title:
        if extracted.issuer:
            title = f"{extracted.doc_type.capitalize()} {extracted.issuer}".strip()
        else:
            clean_stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
            title = f"Foto {clean_stem}" if file_ext in ["jpg", "jpeg", "png", "webp"] else (clean_stem or filename)

    # 5. Save Document in DB (autonomia semantica e gestione quietanze/pagamenti)
    doc_status = determine_document_status(extracted, due_date_obj)

    drive_file_id = None
    drive_web_url = None
    drive_folder_str = None
    active_cred = db.query(GoogleDriveCredential).first()
    if active_cred and getattr(active_cred, "storage_mode", "dual") != "local_only":
        try:
            drive_service = get_drive_service()
            chat_folder = "Generale"
            if thread_id and thread_id not in ("general", "all"):
                th = db.query(ChatThread).filter(ChatThread.id == thread_id).first()
                chat_folder = sanitize_drive_folder_name(th.name if th else thread_id, thread_id=thread_id)

            folder_path = resolve_drive_folder_path(
                extracted.doc_type,
                due_date_obj,
                category_label=extracted.category_label,
                subfolder=extracted.subfolder,
                chat_folder=chat_folder,
            )
            clean_filename = Path(filename).name
            drive_res = drive_service.upload_file(
                file_bytes=contents,
                filename=clean_filename,
                mime_type=content_type,
                folder_path=folder_path,
                access_token=active_cred.access_token
            )
            drive_file_id = drive_res.get("file_id")
            drive_web_url = drive_res.get("web_view_link")
            drive_folder_str = " / ".join(folder_path) if drive_file_id else None
        except Exception as e:
            logger.warning(f"Errore durante l'upload su Google Drive per '{filename}': {e}")
            drive_folder_str = None

    doc = Document(
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
        drive_file_id=drive_file_id,
        drive_web_url=drive_web_url,
        drive_folder_path=drive_folder_str,
        category=extracted.category,
        category_label=extracted.category_label,
        category_icon=extracted.category_icon,
        subfolder=extracted.subfolder
    )
    db.add(doc)
    db.flush()
    return doc


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    thread_id: str = Form("general"),
    db: Session = Depends(get_db)
):
    contents = await file.read()
    filename = file.filename or "upload.bin"
    content_type = file.content_type or "application/octet-stream"

    doc = _process_and_save_single_doc(contents, filename, content_type, thread_id, db)
    db.commit()
    db.refresh(doc)

    is_zip = doc.file_type == "zip" or doc.doc_type == "archivio_zip" or filename.lower().endswith(".zip")
    if doc.status == "quietanzato":
        amount_str = f" ({doc.amount:.2f} €)" if doc.amount is not None else ""
        chat_reply = f"📄 Ho registrato e archiviato il documento come già saldato/quietanzato: **{doc.title}**{amount_str}.\n💡 {doc.summary}"
    elif doc.status == "da_pagare":
        amount_str = f" ({doc.amount:.2f} €)" if doc.amount is not None else ""
        due_str = f" con scadenza {doc.due_date.strftime('%d/%m/%Y')}" if doc.due_date else ""
        if doc.amount is not None:
            chat_reply = f"📄 Ho registrato la spesa/scadenza da saldare: {doc.title}{amount_str}{due_str}."
        else:
            chat_reply = f"📄 Ho registrato il documento con scadenza attiva: {doc.title}{due_str}."
    elif doc.due_date is not None:
        due_str = f" con scadenza promemoria {doc.due_date.strftime('%d/%m/%Y')}"
        chat_reply = f"📄 Ho registrato e archiviato il documento: **{doc.title}**{due_str}.\n💡 {doc.summary}"
    elif is_zip:
        chat_reply = (
            f"📦 Ho archiviato l'archivio compresso: **{doc.title}**.\n"
            f"💡 {doc.summary}\n\n"
            f"⚡ *Vuoi che lo scompatti per te per analizzare e registrare singolarmente ogni documento? Clicca su **'Estrai'** qui sotto oppure dimmi 'scompatta lo zip'!*"
        )
    else:
        is_scan = "scansion" in filename.lower()
        should_ask_rename = doc.doc_type in ["foto", "foto_oggetto", "oggetto_fisico", "screenshot"] and not is_scan
        if should_ask_rename:
            chat_reply = (
                f"📸 Ho analizzato e salvato il file nel caveau come: **{doc.title}**.\n"
                f"💡 {doc.summary}\n\n"
                f"*Desideri dargli un nome specifico o dirmi dove lo conservi?* (es. 'Chiamalo Base Volante' oppure 'Mettilo nello studio')"
            )
        elif is_scan:
            chat_reply = f"📄 Ho analizzato e protocollato il documento: **{doc.title}**.\n💡 {doc.summary}"
        else:
            chat_reply = f"📸 Ho analizzato e archiviato il file: **{doc.title}**.\n💡 {doc.summary}"

    active_model = get_app_setting(db, "ai_model", default=get_settings().OPENROUTER_MODEL) or "auto"
    routed_model = "google/gemini-2.5-flash-lite" if active_model == "auto" else active_model

    fn = Path(doc.file_path).name
    doc_info = {
        "id": doc.id,
        "document_id": doc.id,
        "title": doc.title,
        "issuer": doc.issuer,
        "amount": doc.amount,
        "due_date": doc.due_date.isoformat() if doc.due_date else None,
        "status": doc.status,
        "file_url": f"/uploads/{fn}",
        "download_url": f"/api/documents/{doc.id}/download",
        "file_type": doc.file_type,
        "summary": doc.summary,
        "drive_file_id": doc.drive_file_id,
        "drive_web_url": doc.drive_web_url,
        "category": doc.category,
        "category_label": doc.category_label,
        "category_icon": doc.category_icon,
        "subfolder": doc.subfolder
    }

    user_msg = ChatMessage(
        thread_id=thread_id,
        sender="user",
        message_type="document",
        content=f"Caricato file: {filename}",
        metadata_json=json.dumps({
            "document_id": doc.id,
            "file_name": filename,
            "file_url": f"/uploads/{fn}",
            "download_url": f"/api/documents/{doc.id}/download",
            "file_type": doc.file_type,
            "file_size": len(contents),
            "documents": [doc_info]
        })
    )
    asst_msg = ChatMessage(
        thread_id=thread_id,
        sender="assistant",
        message_type="document",
        content=chat_reply,
        metadata_json=json.dumps({
            "document_id": doc.id,
            "documents": [doc_info],
            "routed_model": routed_model
        })
    )
    db.add(user_msg)
    db.add(asst_msg)
    db.commit()

    fn = Path(doc.file_path).name
    return {
        "document_id": doc.id,
        "title": doc.title,
        "issuer": doc.issuer,
        "amount": doc.amount,
        "due_date": doc.due_date.isoformat() if doc.due_date else None,
        "status": doc.status,
        "chat_reply": chat_reply,
        "file_url": f"/uploads/{fn}",
        "download_url": f"/api/documents/{doc.id}/download",
        "file_type": doc.file_type,
        "summary": doc.summary,
        "drive_file_id": doc.drive_file_id,
        "drive_web_url": doc.drive_web_url,
        "routed_model": routed_model
    }


@router.post("/upload-batch", status_code=status.HTTP_201_CREATED)
async def upload_documents_batch(
    files: List[UploadFile] = File(...),
    thread_id: str = Form("general"),
    db: Session = Depends(get_db)
):
    if not files:
        raise HTTPException(status_code=400, detail="Nessun file fornito per il caricamento.")

    saved_docs: List[Document] = []
    file_names: List[str] = []

    for f in files:
        contents = await f.read()
        filename = f.filename or "upload.bin"
        # Rimuove percorsi relativi se presenti da cartelle (es. "Fatture/sub/doc.pdf" -> "doc.pdf")
        clean_filename = Path(filename).name
        content_type = f.content_type or "application/octet-stream"

        doc = _process_and_save_single_doc(contents, clean_filename, content_type, thread_id, db)
        saved_docs.append(doc)
        file_names.append(clean_filename)

    doc_ids = [d.id for d in saved_docs if d.id]
    db.commit()
    if doc_ids:
        saved_docs = db.query(Document).filter(Document.id.in_(doc_ids)).all()

    total_count = len(saved_docs)
    payable_docs = [d for d in saved_docs if d.status == "da_pagare"]
    quietanzati_docs = [d for d in saved_docs if d.status == "quietanzato"]
    total_payable_amount = sum(d.amount for d in payable_docs if d.amount is not None)
    total_quietanzati_amount = sum(d.amount for d in quietanzati_docs if d.amount is not None)

    # Costruzione della risposta aggregata dell'assistente
    if total_count == 1:
        doc = saved_docs[0]
        if doc.status == "quietanzato":
            amount_str = f" ({doc.amount:.2f} €)" if doc.amount is not None else ""
            chat_reply = f"📄 Ho registrato e archiviato il documento come già saldato/quietanzato: **{doc.title}**{amount_str}.\n💡 {doc.summary}"
        elif doc.status == "da_pagare":
            amount_str = f" ({doc.amount:.2f} €)" if doc.amount is not None else ""
            due_str = f" con scadenza {doc.due_date.strftime('%d/%m/%Y')}" if doc.due_date else ""
            if doc.amount is not None:
                chat_reply = f"📄 Ho registrato la spesa/scadenza da saldare: {doc.title}{amount_str}{due_str}."
            else:
                chat_reply = f"📄 Ho registrato il documento con scadenza attiva: {doc.title}{due_str}."
        elif doc.due_date is not None:
            due_str = f" con scadenza promemoria {doc.due_date.strftime('%d/%m/%Y')}"
            chat_reply = f"📄 Ho registrato e archiviato il documento: **{doc.title}**{due_str}.\n💡 {doc.summary}"
        else:
            chat_reply = f"📸 Ho analizzato e archiviato il file: **{doc.title}**.\n💡 {doc.summary}"
    else:
        lines = []
        for d in saved_docs:
            icon = "📄" if d.file_type == "pdf" else "📸"
            extra = ""
            if d.status == "quietanzato":
                extra_amt = f" — **{d.amount:.2f} €**" if d.amount is not None else ""
                extra = f"{extra_amt} (✅ Già Pagato / Quietanzato)"
            elif d.amount is not None:
                due_info = f", scad. {d.due_date.strftime('%d/%m/%Y')}" if d.due_date else ""
                status_str = " (Da pagare)" if d.status == "da_pagare" else ""
                extra = f" — **{d.amount:.2f} €**{due_info}{status_str}"
            elif d.due_date:
                extra = f" — *scad. {d.due_date.strftime('%d/%m/%Y')}*"
            lines.append(f"- {icon} **{d.title}** ({d.doc_type}){extra}")

        summary_parts = [f"📁 Ho caricato e analizzato con successo **{total_count} documenti** nel caveau!"]
        if payable_docs:
            if total_payable_amount > 0:
                summary_parts.append(f"💳 **{len(payable_docs)} pagamenti/scadenze da saldare** per un totale di **{total_payable_amount:.2f} €**.")
            else:
                summary_parts.append(f"⏰ **{len(payable_docs)} scadenze attive registrate** nel tuo scadenzario.")
        if quietanzati_docs:
            amt_info = f" per complessivi **{total_quietanzati_amount:.2f} €**" if total_quietanzati_amount > 0 else ""
            summary_parts.append(f"✅ **{len(quietanzati_docs)} documenti già saldati/quietanzati**{amt_info} archiviati a memoria storica.")
        summary_parts.append("\n**Documenti archiviati:**\n" + "\n".join(lines))
        summary_parts.append("\nPuoi visualizzarli o scaricarli singolarmente dalle schede qui sotto! ⬇️")
        chat_reply = "\n\n".join(summary_parts)

    active_model = get_app_setting(db, "ai_model", default=get_settings().OPENROUTER_MODEL) or "auto"
    routed_model = "google/gemini-2.5-flash-lite" if active_model == "auto" else active_model

    user_names_str = ", ".join(file_names[:4]) + (f" e altri {total_count - 4} file" if total_count > 4 else "")
    doc_ids = [d.id for d in saved_docs]

    docs_output = []
    for d in saved_docs:
        fn = Path(d.file_path).name
        docs_output.append({
            "id": d.id,
            "document_id": d.id,
            "title": d.title,
            "issuer": d.issuer,
            "amount": d.amount,
            "due_date": d.due_date.isoformat() if d.due_date else None,
            "status": d.status,
            "file_url": f"/uploads/{fn}",
            "download_url": f"/api/documents/{d.id}/download",
            "file_type": d.file_type,
            "summary": d.summary,
            "drive_file_id": d.drive_file_id,
            "drive_web_url": d.drive_web_url,
            "category": d.category,
            "category_label": d.category_label,
            "category_icon": d.category_icon,
            "subfolder": d.subfolder
        })

    user_msg = ChatMessage(
        thread_id=thread_id,
        sender="user",
        message_type="document",
        content=f"Caricati {total_count} file: {user_names_str}",
        metadata_json=json.dumps({
            "document_ids": doc_ids,
            "documents": docs_output
        })
    )
    asst_msg = ChatMessage(
        thread_id=thread_id,
        sender="assistant",
        message_type="document",
        content=chat_reply,
        metadata_json=json.dumps({
            "document_ids": doc_ids,
            "documents": docs_output,
            "routed_model": routed_model
        })
    )
    db.add(user_msg)
    db.add(asst_msg)
    db.commit()

    return {
        "success": True,
        "count": total_count,
        "documents": docs_output,
        "chat_reply": chat_reply,
        "routed_model": routed_model
    }

@router.get("/preview-content")
def get_document_preview_content(
    document_id: Optional[int] = None,
    file_url: Optional[str] = None,
    filename: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Ritorna la preview strutturata e l'HTML formattato per file Word (.docx, .doc),
    Excel (.xlsx, .xls) o CSV, decifrati al volo dal caveau.
    """
    file_bytes = None
    target_filename = ""

    if document_id:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc and Path(doc.file_path).exists():
            file_bytes = read_decrypted_file(doc.file_path)
            target_filename = Path(doc.file_path).name

    if file_bytes is None and (file_url or filename):
        raw_name = filename or ""
        if not raw_name and file_url:
            raw_name = file_url.split("?")[0].split("/")[-1]

        target_filename = raw_name
        settings = get_settings()
        file_path = settings.STORAGE_DIR / raw_name
        if file_path.exists():
            file_bytes = read_decrypted_file(file_path)
        else:
            doc = db.query(Document).filter(Document.file_path.like(f"%{raw_name}%")).first()
            if doc and Path(doc.file_path).exists():
                file_bytes = read_decrypted_file(doc.file_path)
                target_filename = Path(doc.file_path).name

    if file_bytes is None:
        raise HTTPException(status_code=404, detail="File non trovato o non accessibile per l'anteprima")

    from app.services.archive_service import render_office_file_to_html
    preview_data = render_office_file_to_html(file_bytes, target_filename)
    return preview_data

def _handle_unzip_vault_document(
    target_id: Optional[int],
    file_url: Optional[str],
    thread_id: Optional[str],
    db: Session
):
    from app.services.archive_service import unzip_document_to_vault
    target_doc = None
    if target_id:
        target_doc = db.query(Document).filter(Document.id == target_id).first()
    if not target_doc and file_url:
        raw_name = file_url.split("?")[0].split("/")[-1]
        target_doc = db.query(Document).filter(Document.file_path.like(f"%{raw_name}%")).first()

    if not target_doc:
        # Prendi l'ultimo archivio ZIP presente nel thread
        q = db.query(Document).filter(
            (Document.file_type == "zip") | (Document.doc_type == "archivio_zip")
        )
        if thread_id and thread_id not in ["general", "all"]:
            q = q.filter(Document.thread_id == thread_id)
        target_doc = q.order_by(Document.id.desc()).first()

    if not target_doc:
        raise HTTPException(status_code=404, detail="Nessun archivio ZIP trovato nel caveau da decomprimere")

    effective_thread = thread_id or target_doc.thread_id or "general"
    extracted_docs = unzip_document_to_vault(
        db=db,
        document_id=target_doc.id,
        thread_id=effective_thread
    )

    if not extracted_docs:
        raise HTTPException(status_code=400, detail="Impossibile estrarre l'archivio ZIP o nessun file valido trovato all'interno.")

    doc_lines = []
    for idx, d in enumerate(extracted_docs, 1):
        details = []
        if d.category_label:
            folder_info = f"📁 *{d.category_label}*"
            if d.subfolder:
                folder_info += f" / 📂 *{d.subfolder}*"
            details.append(folder_info)
        elif d.doc_type:
            details.append(f"*{d.doc_type.capitalize()}*")
        if d.amount is not None:
            details.append(f"💶 **€ {d.amount:.2f}**")
        if d.due_date:
            details.append(f"📅 Scadenza: **{d.due_date.strftime('%d/%m/%Y')}**")
        detail_str = f" ({' • '.join(details)})" if details else ""
        summary_line = f"\n   _{d.summary}_" if d.summary else ""
        doc_lines.append(f"**{idx}.** 📄 **{d.title}**{detail_str}{summary_line}")

    chat_content = (
        f"📦 Ho scompattato con successo l'archivio **{target_doc.title}** ed esaminato ciascun file singolarmente con l'AI!\n"
        f"Sono stati catalogati ed estratti **{len(extracted_docs)} nuovi documenti** nel Caveau:\n\n"
        + "\n\n".join(doc_lines) +
        "\n\nTutti i documenti sono stati inseriti nelle rispettive sezioni e sono visualizzabili e scaricabili singolarmente."
    )

    extracted_ids = [d.id for d in extracted_docs]
    docs_payload = [
        {
            "id": d.id,
            "document_id": d.id,
            "title": d.title,
            "doc_type": d.doc_type,
            "category": d.category,
            "category_label": d.category_label,
            "category_icon": d.category_icon,
            "subfolder": d.subfolder,
            "issuer": d.issuer,
            "amount": d.amount,
            "due_date": d.due_date.isoformat() if d.due_date else None,
            "status": d.status,
            "summary": d.summary,
            "file_url": f"/uploads/{Path(d.file_path).name}" if d.file_path else None,
            "download_url": f"/api/documents/{d.id}/download",
            "file_type": d.file_type
        }
        for d in extracted_docs
    ]
    meta_json = json.dumps({
        "document_ids": extracted_ids,
        "documents": docs_payload,
        "unzipped_from_id": target_doc.id
    })

    asst_msg = ChatMessage(
        thread_id=effective_thread,
        sender="assistant",
        message_type="document",
        content=chat_content,
        metadata_json=meta_json
    )
    db.add(asst_msg)
    db.commit()

    return {
        "success": True,
        "message": f"Estratti con successo {len(extracted_docs)} documenti dall'archivio ZIP",
        "archive_id": target_doc.id,
        "archive_title": target_doc.title,
        "count": len(extracted_docs),
        "documents": [
            {
                "id": d.id,
                "document_id": d.id,
                "title": d.title,
                "doc_type": d.doc_type,
                "category": d.category,
                "category_label": d.category_label,
                "category_icon": d.category_icon,
                "subfolder": d.subfolder,
                "issuer": d.issuer,
                "amount": d.amount,
                "due_date": d.due_date.isoformat() if d.due_date else None,
                "status": d.status,
                "summary": d.summary,
                "file_url": f"/uploads/{Path(d.file_path).name}" if d.file_path else None,
                "download_url": f"/api/documents/{d.id}/download",
                "file_type": d.file_type
            }
            for d in extracted_docs
        ]
    }

@router.post("/{document_id}/unzip")
def unzip_vault_document_by_id(
    document_id: int,
    thread_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Decomprime un archivio ZIP specificato per ID nel caveau."""
    return _handle_unzip_vault_document(target_id=document_id, file_url=None, thread_id=thread_id, db=db)

@router.post("/unzip")
def unzip_vault_document_generic(
    payload: Optional[UnzipVaultRequest] = None,
    document_id: Optional[int] = None,
    file_url: Optional[str] = None,
    thread_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Decomprime un archivio ZIP specificato via JSON body, query param o deduce l'ultimo archivio."""
    target_id = payload.document_id if (payload and payload.document_id) else document_id
    target_url = payload.file_url if (payload and payload.file_url) else file_url
    target_thread = payload.thread_id if (payload and payload.thread_id) else thread_id
    return _handle_unzip_vault_document(target_id=target_id, file_url=target_url, thread_id=target_thread, db=db)

@router.get("/{document_id}/file")
def get_document_file(document_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc or not Path(doc.file_path).exists():
        raise HTTPException(status_code=404, detail="File non trovato")
    from fastapi.responses import Response
    from app.services.document_service import read_decrypted_file
    decrypted_bytes = read_decrypted_file(doc.file_path)
    media_type = "application/pdf" if doc.file_type == "pdf" else f"image/{doc.file_type}"
    return Response(content=decrypted_bytes, media_type=media_type)

@router.get("/{document_id}/download")
def download_document_file(document_id: int, db: Session = Depends(get_db)):
    """Permette lo scaricamento immediato del file decifrato al volo con nome pulito."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc or not Path(doc.file_path).exists():
        raise HTTPException(status_code=404, detail="File non trovato")
    from fastapi.responses import Response
    from app.services.document_service import read_decrypted_file
    decrypted_bytes = read_decrypted_file(doc.file_path)
    nfkd = unicodedata.normalize('NFKD', doc.title)
    ascii_title = nfkd.encode('ASCII', 'ignore').decode('ASCII')
    clean_title = re.sub(r'[^a-zA-Z0-9_\-]+', '_', ascii_title).strip('_') or f"documento_{doc.id}"
    file_ext = Path(doc.file_path).suffix.lstrip(".") or doc.file_type or "bin"
    if not clean_title.lower().endswith(f".{file_ext.lower()}"):
        download_filename = f"{clean_title}.{file_ext}"
    else:
        download_filename = clean_title
    headers = {"Content-Disposition": f'attachment; filename="{download_filename}"'}
    return Response(
        content=decrypted_bytes,
        media_type="application/octet-stream",
        headers=headers
    )


@router.post("/{document_id}/save-to-downloads")
def save_to_downloads(document_id: int, db: Session = Depends(get_db)):
    """
    Salva il file decifrato direttamente nella cartella Download dell'utente
    e apre Explorer su quel file. Soluzione per pywebview che non gestisce
    i download browser nativamente.
    """
    import subprocess
    from app.services.document_service import read_decrypted_file

    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc or not Path(doc.file_path).exists():
        raise HTTPException(status_code=404, detail="File non trovato")

    decrypted_bytes = read_decrypted_file(doc.file_path)

    # Costruisce nome file pulito
    nfkd = unicodedata.normalize('NFKD', doc.title)
    ascii_title = nfkd.encode('ASCII', 'ignore').decode('ASCII')
    clean_title = re.sub(r'[^a-zA-Z0-9_\-]+', '_', ascii_title).strip('_') or f"documento_{doc.id}"
    file_ext = Path(doc.file_path).suffix.lstrip(".") or doc.file_type or "bin"
    if not clean_title.lower().endswith(f".{file_ext.lower()}"):
        filename = f"{clean_title}.{file_ext}"
    else:
        filename = clean_title

    # Salva nella cartella Download dell'utente corrente
    downloads_dir = Path.home() / "Downloads"
    downloads_dir.mkdir(exist_ok=True)
    dest = downloads_dir / filename

    # Se esiste già, aggiunge suffisso numerico
    counter = 1
    while dest.exists():
        dest = downloads_dir / f"{clean_title}_{counter}.{file_ext}"
        counter += 1

    dest.write_bytes(decrypted_bytes)

    # Apre Explorer selezionando il file appena salvato
    try:
        subprocess.Popen(["explorer", "/select,", str(dest)])
    except Exception:
        pass

    return {
        "success": True,
        "saved_to": str(dest),
        "filename": dest.name,
        "message": f"File salvato in: {dest}"
    }

@router.patch("/{document_id}/status")
def update_document_status(
    document_id: int,
    payload: DocumentStatusUpdate,
    db: Session = Depends(get_db)
):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento non trovato")

    doc.status = payload.status
    db.commit()
    db.refresh(doc)

    return {
        "document_id": doc.id,
        "title": doc.title,
        "issuer": doc.issuer,
        "amount": doc.amount,
        "due_date": doc.due_date.isoformat() if doc.due_date else None,
        "status": doc.status
    }

@router.delete("/bulk", response_model=BulkDeleteResponse)
def delete_documents_bulk(payload: BulkDeleteRequest, db: Session = Depends(get_db)):
    """Elimina in blocco una lista di documenti o tutti i documenti di un canale/caveau dal database e dal disco."""
    query = db.query(Document)
    if payload.document_ids:
        query = query.filter(Document.id.in_(payload.document_ids))
    elif payload.thread_id and payload.thread_id != "all":
        query = query.filter(Document.thread_id == payload.thread_id)

    docs = query.all()
    count = len(docs)
    deleted_ids = []
    for doc in docs:
        deleted_ids.append(doc.id)
        if doc.file_path and not doc.is_local_file:
            try:
                p = Path(doc.file_path)
                if p.exists():
                    p.unlink(missing_ok=True)
            except Exception:
                pass
        db.delete(doc)
    db.commit()

    return {
        "success": True,
        "count": count,
        "message": f"{count} {'documento eliminato' if count == 1 else 'documenti eliminati'} con successo dal caveau.",
        "deleted_ids": deleted_ids
    }

@router.delete("/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento non trovato")

    title = doc.title
    # Try removing physical file (only if not a local computer folder file)
    if doc.file_path and not doc.is_local_file:
        try:
            p = Path(doc.file_path)
            if p.exists():
                p.unlink(missing_ok=True)
        except Exception:
            pass

    db.delete(doc)
    db.commit()
    return {
        "success": True,
        "message": f"Documento '{title}' eliminato con successo.",
        "document_id": document_id
    }
