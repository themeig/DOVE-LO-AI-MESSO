import json
import re
import uuid
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.database import get_db, ChatThread, ChatMessage, Document, PhysicalItem
from app.models.schemas import (
    ChatThreadCreate,
    ChatThreadResponse,
    ThreadListResponse
)

router = APIRouter(prefix="/api/threads", tags=["threads"])

def slugify(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    return re.sub(r"[-\s]+", "-", s) or "chat"

@router.get("", response_model=ThreadListResponse)
@router.get("/", response_model=ThreadListResponse, include_in_schema=False)
def list_threads(db: Session = Depends(get_db)):
    threads = db.query(ChatThread).order_by(ChatThread.created_at.asc()).all()
    result = []
    for t in threads:
        # Get last message
        last_msg = (
            db.query(ChatMessage)
            .filter(ChatMessage.thread_id == t.id)
            .order_by(ChatMessage.id.desc())
            .first()
        )
        msg_count = db.query(ChatMessage).filter(ChatMessage.thread_id == t.id).count()

        members_list = []
        if t.members:
            try:
                members_list = json.loads(t.members)
            except Exception:
                members_list = [t.members]

        last_iso = None
        last_time_str = ""
        if last_msg and last_msg.timestamp:
            last_utc = last_msg.timestamp.replace(tzinfo=timezone.utc) if last_msg.timestamp.tzinfo is None else last_msg.timestamp
            last_iso = last_utc.isoformat()
            last_time_str = last_msg.timestamp.strftime("%H:%M")

        result.append(
            ChatThreadResponse(
                id=t.id,
                name=t.name,
                thread_type=t.thread_type,
                icon=t.icon,
                color=t.color,
                description=t.description,
                members=members_list,
                created_at=t.created_at.isoformat() if t.created_at else None,
                last_message=last_msg.content if last_msg else (t.description or "Inizia a scrivere..."),
                last_message_time=last_time_str,
                last_message_iso=last_iso,
                message_count=msg_count,
                unread_count=0
            )
        )
    return ThreadListResponse(threads=result)

@router.post("", response_model=ChatThreadResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=ChatThreadResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_thread(payload: ChatThreadCreate, db: Session = Depends(get_db)):
    base_slug = slugify(payload.name)
    thread_id = base_slug
    # Guarantee uniqueness
    existing = db.query(ChatThread).filter(ChatThread.id == thread_id).first()
    if existing:
        thread_id = f"{base_slug}-{uuid.uuid4().hex[:4]}"

    icon = payload.icon
    if not icon:
        icon = "fa-users" if payload.thread_type == "group" else "fa-briefcase"

    color = payload.color
    if not color:
        color = "bg-emerald-600" if payload.thread_type == "group" else "bg-indigo-600"

    members = payload.members or ["Io"]
    if payload.thread_type == "group" and "Io" not in members:
        members.insert(0, "Io")

    new_thread = ChatThread(
        id=thread_id,
        name=payload.name,
        thread_type=payload.thread_type,
        icon=icon,
        color=color,
        description=payload.description or ("Gruppo di persone" if payload.thread_type == "group" else "Area tematica"),
        members=json.dumps(members),
        created_at=datetime.now(timezone.utc)
    )
    db.add(new_thread)
    db.commit()
    db.refresh(new_thread)

    # Initial welcome message in this thread
    welcome_text = (
        f"👋 Benvenuto nel gruppo **{payload.name}**! "
        f"Membri: {', '.join(members)}. "
        f"Potete scambiarvi informazioni, memorizzare posizioni e archiviare documenti comuni qui."
        if payload.thread_type == "group"
        else f"📁 Spazio creato: **{payload.name}**. Invia qui documenti o appunti relativi a quest'area tematica per tenerli separati e organizzati!"
    )
    welcome_msg = ChatMessage(
        thread_id=new_thread.id,
        sender="assistant",
        message_type="text",
        content=welcome_text,
        metadata_json=json.dumps({"action": "WELCOME"})
    )
    db.add(welcome_msg)
    db.commit()

    return ChatThreadResponse(
        id=new_thread.id,
        name=new_thread.name,
        thread_type=new_thread.thread_type,
        icon=new_thread.icon,
        color=new_thread.color,
        description=new_thread.description,
        members=members,
        created_at=new_thread.created_at.isoformat() if new_thread.created_at else None,
        last_message=welcome_text,
        last_message_time=datetime.now(timezone.utc).strftime("%H:%M"),
        message_count=1,
        unread_count=0
    )

@router.get("/{thread_id}/messages")
def get_thread_messages(thread_id: str, db: Session = Depends(get_db)):
    thread = db.query(ChatThread).filter(ChatThread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Chat o gruppo non trovato.")

    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.thread_id == thread_id)
        .order_by(ChatMessage.id.asc())
        .all()
    )

    items = []
    for m in messages:
        meta = {}
        if m.metadata_json:
            try:
                meta = json.loads(m.metadata_json)
            except Exception:
                meta = {}

        # Risolvi e arricchisci automaticamente i documenti per garantire che
        # i widget delle schede documento persistano SEMPRE alla riapertura della chat
        doc_id = meta.get("document_id")
        doc_ids = meta.get("document_ids")
        resolved_ids = []
        if isinstance(doc_ids, list):
            for did in doc_ids:
                try:
                    resolved_ids.append(int(did))
                except (ValueError, TypeError):
                    pass
        elif doc_id is not None:
            try:
                resolved_ids.append(int(doc_id))
            except (ValueError, TypeError):
                pass

        if resolved_ids and not meta.get("documents"):
            found_docs = db.query(Document).filter(Document.id.in_(resolved_ids)).all()
            if found_docs:
                docs_payload = []
                for d in found_docs:
                    fn = Path(d.file_path).name if d.file_path else ""
                    docs_payload.append({
                        "id": d.id,
                        "document_id": d.id,
                        "title": d.title,
                        "issuer": d.issuer,
                        "amount": d.amount,
                        "due_date": d.due_date.isoformat() if d.due_date else None,
                        "status": d.status,
                        "file_url": f"/uploads/{fn}" if fn else None,
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
                meta["documents"] = docs_payload
                if m.sender == "user":
                    first_d = found_docs[0]
                    first_fn = Path(first_d.file_path).name if first_d.file_path else ""
                    meta.setdefault("file_url", f"/uploads/{first_fn}")
                    meta.setdefault("download_url", f"/api/documents/{first_d.id}/download")
                    meta.setdefault("file_type", first_d.file_type)
                    meta.setdefault("file_name", first_d.title)

        iso_str = None
        time_str = ""
        date_str = ""
        if m.timestamp:
            utc_dt = m.timestamp.replace(tzinfo=timezone.utc) if m.timestamp.tzinfo is None else m.timestamp
            iso_str = utc_dt.isoformat()
            time_str = m.timestamp.strftime("%H:%M")
            date_str = m.timestamp.strftime("%Y-%m-%d")

        items.append({
            "id": m.id,
            "sender": m.sender,
            "message_type": m.message_type,
            "content": m.content,
            "timestamp": time_str,
            "created_at": iso_str,
            "date": date_str,
            "metadata": meta
        })
    return {"thread_id": thread_id, "name": thread.name, "messages": items}

@router.delete("/{thread_id}")
def delete_thread(thread_id: str, db: Session = Depends(get_db)):
    if thread_id == "general":
        raise HTTPException(status_code=400, detail="Impossibile eliminare il canale principale.")

    thread = db.query(ChatThread).filter(ChatThread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Chat o gruppo non trovato.")

    # Delete messages associated with this thread
    db.query(ChatMessage).filter(ChatMessage.thread_id == thread_id).delete()
    # Relink documents and physical items to 'general'
    db.query(Document).filter(Document.thread_id == thread_id).update({"thread_id": "general"})
    db.query(PhysicalItem).filter(PhysicalItem.thread_id == thread_id).update({"thread_id": "general"})

    db.delete(thread)
    db.commit()

    return {"success": True, "message": f"Gruppo/Area '{thread.name}' eliminato con successo."}
