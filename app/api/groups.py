"""
Router API per la gestione dei gruppi condivisi, codici d'invito e adesione membri.
"""
import uuid
import secrets
import json
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.database import get_db, Group, GroupMember, User, ActivityEvent, ChatThread
from app.services.auth_service import get_current_user
from app.services.websocket_manager import group_ws_manager

router = APIRouter(prefix="/api/groups", tags=["Groups"])


def _generate_invite_code() -> str:
    """Genera un codice d'invito leggibile e mnemonico (es. ROX-8821)."""
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    digits = "23456789"
    prefix = "".join(secrets.choice(chars) for _ in range(3))
    suffix = "".join(secrets.choice(digits) for _ in range(4))
    return f"{prefix}-{suffix}"


def _ensure_user_exists(db: Session, current_user: dict) -> User:
    """Garantisce che l'utente corrente sia presente nella tabella users locale/cloud."""
    user = db.query(User).filter(User.id == current_user["id"]).first()
    if not user:
        user = User(
            id=current_user["id"],
            email=current_user.get("email") or f"{current_user['id']}@cloud.internal",
            full_name=current_user.get("full_name") or "Utente Caveau",
            avatar_url=current_user.get("avatar_url")
        )
        db.add(user)
        db.flush()
    return user


class GroupCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255, description="Nome del gruppo (es. Famiglia Rossi)")
    description: Optional[str] = Field(None, max_length=1000, description="Descrizione o scopo del gruppo")
    icon: Optional[str] = Field("fa-house", max_length=50, description="Icona FontAwesome")


class GroupJoinRequest(BaseModel):
    invite_code: str = Field(..., min_length=3, max_length=50, description="Codice d'invito ricevuto")


class GroupMemberResponse(BaseModel):
    user_id: str
    email: str
    full_name: str
    avatar_url: Optional[str] = None
    role: str
    joined_at: str


class GroupResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    icon: str
    invite_code: str
    created_by: Optional[str] = None
    created_at: str
    role: str = "member"
    members_count: int = 1


@router.post("", status_code=status.HTTP_201_CREATED, response_model=GroupResponse)
def create_group(
    payload: GroupCreateRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Crea un nuovo gruppo condiviso e associa il creatore come amministratore con codice d'invito univoco.
    """
    _ensure_user_exists(db, current_user)

    # Genera codice d'invito univoco
    code = _generate_invite_code()
    while db.query(Group).filter(Group.invite_code == code).first():
        code = _generate_invite_code()

    group_id = str(uuid.uuid4())
    new_group = Group(
        id=group_id,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        icon=payload.icon or "fa-house",
        invite_code=code,
        created_by=current_user["id"]
    )
    db.add(new_group)
    db.flush()

    # Aggiungi il creatore come admin
    admin_member = GroupMember(
        group_id=new_group.id,
        user_id=current_user["id"],
        role="admin"
    )
    db.add(admin_member)

    # Registra evento iniziale di creazione gruppo
    init_event = ActivityEvent(
        group_id=new_group.id,
        actor_user_id=current_user["id"],
        actor_name=current_user.get("full_name") or "Amministratore",
        event_type="AI_ASSISTANT_QUERY",
        title=f"Gruppo '{new_group.name}' creato",
        content="Benvenuti nel Caveau condiviso. Tutte le fatture, bollette e posizioni condivise compariranno in questo registro.",
        payload={"invite_code": code}
    )
    db.add(init_event)

    # Sincronizza il thread nella tabella chat_threads per la visualizzazione nella sidebar
    thread = db.query(ChatThread).filter(ChatThread.id == new_group.id).first()
    if not thread:
        thread = ChatThread(
            id=new_group.id,
            name=new_group.name,
            thread_type="group",
            icon=new_group.icon or "fa-house",
            color="bg-[#3C5A48]",
            description=f"Gruppo Online • Codice Invito: {code}",
            members=json.dumps([current_user.get("full_name") or "Amministratore"])
        )
        db.add(thread)

    db.commit()
    db.refresh(new_group)

    return GroupResponse(
        id=new_group.id,
        name=new_group.name,
        description=new_group.description,
        icon=new_group.icon,
        invite_code=new_group.invite_code,
        created_by=new_group.created_by,
        created_at=new_group.created_at.isoformat() if new_group.created_at else "",
        role="admin",
        members_count=1
    )


@router.get("", response_model=List[GroupResponse])
def list_my_groups(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Restituisce tutti i gruppi di cui l'utente corrente è membro con il proprio ruolo.
    """
    memberships = db.query(GroupMember).filter(GroupMember.user_id == current_user["id"]).all()
    if not memberships:
        return []

    role_map = {m.group_id: m.role for m in memberships}
    group_ids = list(role_map.keys())

    groups = db.query(Group).filter(Group.id.in_(group_ids)).all()

    result = []
    for g in groups:
        count = db.query(GroupMember).filter(GroupMember.group_id == g.id).count()
        result.append(GroupResponse(
            id=g.id,
            name=g.name,
            description=g.description,
            icon=g.icon,
            invite_code=g.invite_code,
            created_by=g.created_by,
            created_at=g.created_at.isoformat() if g.created_at else "",
            role=role_map.get(g.id, "member"),
            members_count=count
        ))
    return result


@router.post("/join")
def join_group(
    payload: GroupJoinRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Consente a un utente di aderire a un gruppo tramite codice d'invito.
    """
    _ensure_user_exists(db, current_user)
    code = payload.invite_code.strip().upper()

    group = db.query(Group).filter(Group.invite_code == code).first()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Codice invito non valido o inesistente."
        )

    # Verifica se già iscritto
    existing = db.query(GroupMember).filter(
        GroupMember.group_id == group.id,
        GroupMember.user_id == current_user["id"]
    ).first()

    if not existing:
        new_member = GroupMember(
            group_id=group.id,
            user_id=current_user["id"],
            role="member"
        )
        db.add(new_member)

        # Registra evento di adesione
        join_event = ActivityEvent(
            group_id=group.id,
            actor_user_id=current_user["id"],
            actor_name=current_user.get("full_name") or "Nuovo Membro",
            event_type="AI_ASSISTANT_QUERY",
            title=f"{current_user.get('full_name', 'Un utente')} è entrato nel gruppo",
            content=f"Accesso confermato al Caveau condiviso '{group.name}'.",
            payload={"action": "MEMBER_JOINED"}
        )
        db.add(join_event)

        # Assicura presenza del thread nella sidebar locale dell'utente
        thread = db.query(ChatThread).filter(ChatThread.id == group.id).first()
        if not thread:
            thread = ChatThread(
                id=group.id,
                name=group.name,
                thread_type="group",
                icon=group.icon or "fa-house",
                color="bg-[#3C5A48]",
                description=f"Gruppo Online • Codice: {group.invite_code}",
                members=json.dumps(["Membri"])
            )
            db.add(thread)

        db.commit()

    return {
        "group_id": group.id,
        "name": group.name,
        "role": "member",
        "message": f"Adesione al gruppo '{group.name}' completata con successo."
    }


@router.get("/{group_id}/members", response_model=List[GroupMemberResponse])
def get_group_members(
    group_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Restituisce l'elenco dei membri di un gruppo (solo se l'utente richiedente fa parte del gruppo).
    """
    # Controllo appartenenza: 403 se non fa parte del gruppo
    membership = db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == current_user["id"]
    ).first()

    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Non hai i permessi per accedere a questo gruppo."
        )

    members = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
    user_ids = [m.user_id for m in members]
    users = db.query(User).filter(User.id.in_(user_ids)).all()
    user_map = {u.id: u for u in users}

    response = []
    for m in members:
        u = user_map.get(m.user_id)
        response.append(GroupMemberResponse(
            user_id=m.user_id,
            email=u.email if u else "",
            full_name=u.full_name if u else "Membro",
            avatar_url=u.avatar_url if u else None,
            role=m.role,
            joined_at=m.joined_at.isoformat() if m.joined_at else ""
        ))
    return response


@router.get("/{group_id}/feed")
def get_group_activity_feed(
    group_id: str,
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Restituisce il registro cronologico delle attività e atti del gruppo (esclusivamente eventi ufficiali).
    """
    from app.services.activity_service import list_group_activity_feed

    membership = db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == current_user["id"]
    ).first()

    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Non hai i permessi per visualizzare il registro di questo gruppo."
        )

    events = list_group_activity_feed(db, group_id, limit=limit, offset=offset)
    return [
        {
            "id": ev.id,
            "group_id": ev.group_id,
            "actor_user_id": ev.actor_user_id,
            "actor_name": ev.actor_name,
            "event_type": ev.event_type,
            "title": ev.title,
            "content": ev.content,
            "document_id": ev.document_id,
            "item_id": ev.item_id,
            "payload": ev.payload or {},
            "created_at": ev.created_at.isoformat() if ev.created_at else ""
        }
        for ev in events
    ]


@router.websocket("/{group_id}/ws")
async def group_websocket_endpoint(
    websocket: WebSocket,
    group_id: str
):
    """
    Endpoint WebSocket per ricevere gli aggiornamenti di protocollo in tempo reale per un gruppo.
    """
    await group_ws_manager.connect(group_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        group_ws_manager.disconnect(group_id, websocket)
    except Exception:
        group_ws_manager.disconnect(group_id, websocket)


