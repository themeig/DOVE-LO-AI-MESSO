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

    # 1. Save incoming user message
    user_msg = ChatMessage(
        thread_id=thread_id,
        sender="user",
        message_type="text",
        content=payload.message
    )
    db.add(user_msg)
    db.commit()

    # 2. Run intelligent agent with real tools and thread context
    agent = get_agent()
    chat_response = agent.run_turn(payload.message, db=db, thread_id=thread_id)

    # 3. Save assistant reply to chat history
    asst_msg = ChatMessage(
        thread_id=thread_id,
        sender="assistant",
        message_type="text",
        content=chat_response.reply,
        metadata_json=json.dumps({"action": chat_response.action})
    )
    db.add(asst_msg)
    db.commit()

    return chat_response
