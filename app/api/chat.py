import base64
import json
import logging
from pathlib import Path
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.models.database import get_db, ChatMessage
from app.models.schemas import ChatRequest, ChatResponse
from app.services.agent_service import AgenticChatService
from app.services.document_service import save_uploaded_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])
_agent = None

def get_agent() -> AgenticChatService:
    global _agent
    if _agent is None:
        _agent = AgenticChatService()
    return _agent

@router.post("", response_model=ChatResponse)
@router.post("/", response_model=ChatResponse, include_in_schema=False)
def handle_chat_message(
    payload: ChatRequest,
    db: Session = Depends(get_db)
):
    thread_id = payload.thread_id or "general"

    # 1. Save incoming user message with optional quoted text and audio metadata
    user_metadata = {}
    if payload.quoted_message:
        user_metadata["quoted_message"] = payload.quoted_message

    msg_type = "text"
    content_text = (payload.message or "").strip()
    transcribed_text = None

    if payload.audio_base64:
        msg_type = "audio"
        audio_bytes = None
        fmt = (payload.audio_format or "wav").lower().lstrip(".")
        try:
            audio_bytes = base64.b64decode(payload.audio_base64)
            saved_path = save_uploaded_file(audio_bytes, f"voice_note.{fmt}")
            audio_filename = Path(saved_path).name
            user_metadata["audio_url"] = f"/uploads/{audio_filename}"
            if payload.audio_duration is not None:
                user_metadata["duration"] = payload.audio_duration
        except Exception as e:
            logger.warning(f"Errore nel salvataggio del vocale cifrato: {e}")

        # Se il client ha già fornito la trascrizione (Web Speech API), usala prioritariamente
        if content_text and content_text != "🎤 Messaggio vocale":
            transcribed_text = content_text
        elif audio_bytes:
            from app.services.transcription_service import transcribe_audio
            try:
                transcribed_text = transcribe_audio(audio_bytes, audio_format=fmt)
            except Exception as tr_err:
                logger.warning(f"Errore durante trascrizione audio: {tr_err}")
                transcribed_text = None

        if transcribed_text and transcribed_text.strip():
            content_text = transcribed_text.strip()
            user_metadata["transcription"] = content_text
            user_msg_content = f"🎤 {content_text}"
        else:
            content_text = ""
            user_metadata["transcription"] = None
            user_msg_content = "🎤 Messaggio vocale"
    else:
        user_msg_content = content_text

    # Se l'utente ha inviato un audio completamente silenzioso o incomprensibile
    if msg_type == "audio" and not content_text:
        user_msg = ChatMessage(
            thread_id=thread_id,
            sender="user",
            message_type=msg_type,
            content=user_msg_content,
            metadata_json=json.dumps(user_metadata) if user_metadata else None
        )
        db.add(user_msg)
        db.commit()

        silence_reply = (
            "🎤 Non sono riuscito a comprendere chiaramente le parole nel messaggio vocale. "
            "Puoi riprovare scandendo bene le parole oppure scrivermi direttamente nella barra in basso!"
        )
        asst_msg = ChatMessage(
            thread_id=thread_id,
            sender="assistant",
            message_type="text",
            content=silence_reply,
            metadata_json=json.dumps({"action": "REPLY"})
        )
        db.add(asst_msg)
        db.commit()

        return ChatResponse(
            reply=silence_reply,
            action="REPLY",
            transcription=None
        )

    user_msg = ChatMessage(
        thread_id=thread_id,
        sender="user",
        message_type=msg_type,
        content=user_msg_content,
        metadata_json=json.dumps(user_metadata) if user_metadata else None
    )
    db.add(user_msg)
    db.commit()

    # 2. Run intelligent agent with real tools, thread context, quoted reference and audio input
    agent = get_agent()
    chat_response = agent.run_turn(
        content_text,
        db=db,
        thread_id=thread_id,
        quoted_message=payload.quoted_message,
        audio_base64=payload.audio_base64,
        audio_format=payload.audio_format or "wav"
    )
    if msg_type == "audio" and transcribed_text:
        chat_response.transcription = transcribed_text

    # 3. Save assistant reply to chat history
    meta_dict = {"action": chat_response.action}
    if chat_response.documents:
        meta_dict["documents"] = chat_response.documents
    if chat_response.confirmation:
        meta_dict["confirmation"] = chat_response.confirmation
    if chat_response.routed_model:
        meta_dict["routed_model"] = chat_response.routed_model


    asst_msg = ChatMessage(
        thread_id=thread_id,
        sender="assistant",
        message_type="text",
        content=chat_response.reply,
        metadata_json=json.dumps(meta_dict)
    )
    db.add(asst_msg)
    db.commit()

    return chat_response
