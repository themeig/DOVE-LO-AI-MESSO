import re
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.models.database import get_db, ChatMessage, PhysicalItem, Document
from app.models.schemas import ChatRequest, ChatResponse
from app.services.ai_service import get_ai_service

router = APIRouter(prefix="/api/chat", tags=["chat"])

@router.post("", response_model=ChatResponse)
@router.post("/", response_model=ChatResponse, include_in_schema=False)
def handle_chat_message(
    payload: ChatRequest,
    db: Session = Depends(get_db)
):
    # 1. Save incoming user message
    user_msg = ChatMessage(
        sender="user",
        message_type="text",
        content=payload.message
    )
    db.add(user_msg)
    db.commit()

    # 2. Extract intent via AI service
    ai_service = get_ai_service()
    intent = ai_service.classify_and_extract_intent(payload.message)

    reply = ""
    item_id = None

    if intent.intent == "STORE_LOCATION":
        raw_name = (intent.item_name or "Oggetto").strip()
        cleaned_name = re.sub(r"^(il|lo|la|i|gli|le|l'|un|uno|una|un')\s*", "", raw_name, flags=re.IGNORECASE).strip()
        item_name = (cleaned_name if cleaned_name else raw_name).capitalize()

        # Check existing item
        existing = db.query(PhysicalItem).filter(PhysicalItem.item_name.ilike(item_name)).first()
        if existing:
            existing.primary_location = intent.primary_location or existing.primary_location
            if intent.detailed_location:
                existing.detailed_location = intent.detailed_location
            item = existing
        else:
            item = PhysicalItem(
                item_name=item_name,
                primary_location=intent.primary_location or "Non specificato",
                detailed_location=intent.detailed_location,
                category="documenti" if any(k in item_name.lower() for k in ["passaporto", "carta", "patente", "chiav"]) else "generico"
            )
            db.add(item)
        db.commit()
        db.refresh(item)
        item_id = item.id

        loc_str = item.primary_location
        if item.detailed_location:
            loc_str += f" ({item.detailed_location})"
        reply = f"✅ Memorizzato! Ho salvato la posizione di '{item.item_name}': {loc_str}."

    elif intent.intent == "QUERY_LOCATION":
        raw_query = (intent.item_name or "").strip()
        cleaned_query = re.sub(r"^(il|lo|la|i|gli|le|l'|un|uno|una|un')\s*", "", raw_query, flags=re.IGNORECASE).strip()

        # Find matching item
        found_item = None
        if cleaned_query:
            found_item = db.query(PhysicalItem).filter(PhysicalItem.item_name.ilike(f"%{cleaned_query}%")).first()
            if not found_item:
                all_items = db.query(PhysicalItem).all()
                for it in all_items:
                    if cleaned_query.lower() in it.item_name.lower() or it.item_name.lower() in cleaned_query.lower():
                        found_item = it
                        break

        if found_item:
            loc_str = found_item.primary_location
            if found_item.detailed_location:
                loc_str += f" ({found_item.detailed_location})"
            reply = f"📍 Il tuo {found_item.item_name} si trova in: {loc_str}."
        else:
            search_label = cleaned_query or raw_query or "questo oggetto"
            reply = f"Non ho trovato dove si trova '{search_label}' tra i tuoi oggetti registrati. Se vuoi posso salvarlo ora: dimmi pure dove l'hai riposto (es. 'Ho messo {search_label} nell\'armadio') e lo ricorderò per te!"

    elif intent.intent == "QUERY_DEADLINES":
        docs = db.query(Document).filter(Document.status == "da_pagare").order_by(Document.due_date.asc().nulls_last()).all()
        if docs:
            lines = []
            for d in docs:
                due_info = d.due_date.strftime("%d/%m/%Y") if d.due_date else "data da definire"
                amt_info = f"{d.amount:.2f} €" if d.amount is not None else "importo non specificato"
                lines.append(f"• {d.title} ({d.issuer or 'Ente'}): {amt_info} - entro il {due_info}")
            reply = "📅 Ecco le tue scadenze in sospeso:\n" + "\n".join(lines)
        else:
            reply = "🎉 Non ci sono scadenze o bollette da pagare in questo momento!"

    else:  # GENERAL
        # Retrieve recent messages for conversational context
        recent_msgs = db.query(ChatMessage).order_by(ChatMessage.id.desc()).limit(6).all()
        history = []
        for m in reversed(recent_msgs):
            if m.content != payload.message:
                history.append({"role": "assistant" if m.sender == "assistant" else "user", "content": m.content})
        
        reply = ai_service.generate_conversational_reply(payload.message, chat_history=history)

    # 3. Save assistant reply to chat history
    asst_msg = ChatMessage(
        sender="assistant",
        message_type="text",
        content=reply,
        metadata_json=f'{{"item_id": {item_id}}}' if item_id else None
    )
    db.add(asst_msg)
    db.commit()

    return ChatResponse(
        reply=reply,
        action=intent.intent,
        data={"item_id": item_id} if item_id else None
    )
