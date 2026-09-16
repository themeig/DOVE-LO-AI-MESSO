import json
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.models.database import get_db, ChatMessage
from app.models.schemas import ChatRequest, ChatResponse
from app.services.agent_service import AgenticChatService

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

    # 1. Save incoming user message with optional quoted text metadata
    user_metadata = {}
    if payload.quoted_message:
        user_metadata["quoted_message"] = payload.quoted_message

    user_msg = ChatMessage(
        thread_id=thread_id,
        sender="user",
        message_type="text",
        content=payload.message,
        metadata_json=json.dumps(user_metadata) if user_metadata else None
    )
    db.add(user_msg)
    db.commit()

    # 2. Run intelligent agent with real tools, thread context and quoted reference
    agent = get_agent()
    chat_response = agent.run_turn(
        payload.message,
        db=db,
        thread_id=thread_id,
        quoted_message=payload.quoted_message
    )

    # 3. Save assistant reply to chat history
    meta_dict = {"action": chat_response.action}
    if chat_response.documents:
        meta_dict["documents"] = chat_response.documents
    if chat_response.confirmation:
        meta_dict["confirmation"] = chat_response.confirmation

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
