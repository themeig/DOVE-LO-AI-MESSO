import re
import unicodedata
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.models.database import get_db, Document, ChatMessage
from app.models.schemas import DocumentStatusUpdate, BulkDeleteRequest, BulkDeleteResponse
from app.services.ai_service import get_ai_service
from app.services.document_service import save_uploaded_file

router = APIRouter(prefix="/api/documents", tags=["documents"])

from typing import List


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

    # 5. Save Document in DB
    is_payable = (extracted.amount is not None) and (extracted.doc_type in ["bolletta", "f24", "fattura", "tributo", "avviso"])
    doc_status = "da_pagare" if is_payable else "archiviato"

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
        summary=extracted.summary
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

    is_payable = (doc.amount is not None) and (doc.doc_type in ["bolletta", "f24", "fattura", "tributo", "avviso"])
    if is_payable:
        amount_str = f" ({doc.amount:.2f} €)" if doc.amount is not None else ""
        due_str = f" con scadenza {doc.due_date.strftime('%d/%m/%Y')}" if doc.due_date else ""
        chat_reply = f"📄 Ho registrato la bolletta/scadenza: {doc.title}{amount_str}{due_str}."
    else:
        should_ask_rename = doc.doc_type in ["foto", "foto_oggetto", "oggetto_fisico", "screenshot", "generico"]
        if should_ask_rename:
            chat_reply = (
                f"📸 Ho analizzato e salvato il file nel caveau come: **{doc.title}**.\n"
                f"💡 {doc.summary}\n\n"
                f"*Desideri dargli un nome specifico o dirmi dove lo conservi?* (es. 'Chiamalo Base Volante' oppure 'Mettilo nello studio')"
            )
        else:
            chat_reply = f"📸 Ho analizzato e archiviato il file: {doc.title}.\n💡 {doc.summary}"

    user_msg = ChatMessage(
        thread_id=thread_id,
        sender="user",
        message_type="document",
        content=f"Caricato file: {filename}",
        metadata_json=f'{{"document_id": {doc.id}}}'
    )
    asst_msg = ChatMessage(
        thread_id=thread_id,
        sender="assistant",
        message_type="document",
        content=chat_reply,
        metadata_json=f'{{"document_id": {doc.id}}}'
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
        "summary": doc.summary
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
    payable_docs = [d for d in saved_docs if d.amount is not None and d.status == "da_pagare"]
    total_payable_amount = sum(d.amount for d in payable_docs if d.amount is not None)

    # Costruzione della risposta aggregata dell'assistente
    if total_count == 1:
        doc = saved_docs[0]
        if payable_docs:
            amount_str = f" ({doc.amount:.2f} €)" if doc.amount is not None else ""
            due_str = f" con scadenza {doc.due_date.strftime('%d/%m/%Y')}" if doc.due_date else ""
            chat_reply = f"📄 Ho registrato la bolletta/scadenza: {doc.title}{amount_str}{due_str}."
        else:
            chat_reply = f"📸 Ho analizzato e archiviato il file: **{doc.title}**.\n💡 {doc.summary}"
    else:
        lines = []
        for d in saved_docs:
            icon = "📄" if d.file_type == "pdf" else "📸"
            extra = ""
            if d.amount is not None:
                due_info = f", scad. {d.due_date.strftime('%d/%m/%Y')}" if d.due_date else ""
                extra = f" — **{d.amount:.2f} €**{due_info}"
            lines.append(f"- {icon} **{d.title}** ({d.doc_type}){extra}")

        summary_parts = [f"📁 Ho caricato e analizzato con successo **{total_count} documenti** nel caveau!"]
        if payable_docs:
            summary_parts.append(f"💳 **{len(payable_docs)} pagamenti/scadenze registrati** per un totale di **{total_payable_amount:.2f} €**.")
        summary_parts.append("\n**Documenti archiviati:**\n" + "\n".join(lines))
        summary_parts.append("\nPuoi visualizzarli o scaricarli singolarmente dalle schede qui sotto! ⬇️")
        chat_reply = "\n\n".join(summary_parts)

    user_names_str = ", ".join(file_names[:4]) + (f" e altri {total_count - 4} file" if total_count > 4 else "")
    doc_ids = [d.id for d in saved_docs]

    user_msg = ChatMessage(
        thread_id=thread_id,
        sender="user",
        message_type="document",
        content=f"Caricati {total_count} file: {user_names_str}",
        metadata_json=f'{{"document_ids": {doc_ids}}}'
    )
    asst_msg = ChatMessage(
        thread_id=thread_id,
        sender="assistant",
        message_type="document",
        content=chat_reply,
        metadata_json=f'{{"document_ids": {doc_ids}}}'
    )
    db.add(user_msg)
    db.add(asst_msg)
    db.commit()

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
            "summary": d.summary
        })

    return {
        "success": True,
        "count": total_count,
        "documents": docs_output,
        "chat_reply": chat_reply
    }

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
