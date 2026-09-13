from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.models.database import get_db, Document, ChatMessage
from app.models.schemas import DocumentStatusUpdate
from app.services.ai_service import get_ai_service
from app.services.document_service import save_uploaded_file

router = APIRouter(prefix="/api/documents", tags=["documents"])

@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # 1. Read file contents and save to disk
    contents = await file.read()
    filename = file.filename or "upload.bin"
    saved_path = save_uploaded_file(contents, filename)

    # 2. Extract structured data with AI service
    ai_service = get_ai_service()
    content_type = file.content_type or "application/octet-stream"
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
    title = f"{extracted.doc_type.capitalize()} {extracted.issuer}".strip()
    if not title:
        title = filename

    # 5. Save Document in DB
    is_payable = (extracted.amount is not None) and (extracted.doc_type in ["bolletta", "f24", "fattura", "tributo", "avviso"])
    doc_status = "da_pagare" if is_payable else "archiviato"

    doc = Document(
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
    db.commit()
    db.refresh(doc)

    # 6. Generate chat reply and record in chat history
    if is_payable:
        amount_str = f" ({doc.amount:.2f} €)" if doc.amount is not None else ""
        due_str = f" con scadenza {doc.due_date.strftime('%d/%m/%Y')}" if doc.due_date else ""
        chat_reply = f"📄 Ho registrato la bolletta/scadenza: {doc.title}{amount_str}{due_str}."
    else:
        chat_reply = f"📸 Ho analizzato e archiviato il file: {doc.title}.\n💡 {doc.summary}"

    user_msg = ChatMessage(
        sender="user",
        message_type="document",
        content=f"Caricato file: {filename}",
        metadata_json=f'{{"document_id": {doc.id}}}'
    )
    asst_msg = ChatMessage(
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
        "file_type": doc.file_type,
        "summary": doc.summary
    }

@router.get("/{document_id}/file")
def get_document_file(document_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc or not Path(doc.file_path).exists():
        raise HTTPException(status_code=404, detail="File non trovato")
    from fastapi.responses import FileResponse
    media_type = "application/pdf" if doc.file_type == "pdf" else f"image/{doc.file_type}"
    return FileResponse(doc.file_path, media_type=media_type, filename=Path(doc.file_path).name)

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

@router.delete("/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento non trovato")

    title = doc.title
    # Try removing physical file
    if doc.file_path:
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
