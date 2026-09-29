"""
Router API e controller per la simulazione multi-utente e testing della chat di gruppo.
Consente di simulare contemporaneamente più utenti connessi (Marco, Laura, Giuseppe, Marcone),
scambiare account in un click, lanciare finestre desktop secondarie e visualizzare la chat in split-screen.
"""
import os
import sys
import subprocess
import jwt
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.database import get_db, User, Group, GroupMember, ChatThread

router = APIRouter(tags=["Simulator"])

SIMULATOR_PERSONAS = [
    {
        "key": "marco",
        "id": "sim-user-marco-0001",
        "email": "marco.rossi@test.it",
        "full_name": "Marco Rossi",
        "avatar": "M",
        "color": "#3C5A48",
        "role_desc": "Capofamiglia & Gestore Bollette"
    },
    {
        "key": "laura",
        "id": "sim-user-laura-0002",
        "email": "laura.bianchi@test.it",
        "full_name": "Laura Bianchi",
        "avatar": "L",
        "color": "#C84B31",
        "role_desc": "Membro Famiglia & Contabile Spese"
    },
    {
        "key": "giuseppe",
        "id": "sim-user-giuseppe-0003",
        "email": "giuseppe.verdi@test.it",
        "full_name": "Giuseppe Verdi",
        "avatar": "G",
        "color": "#1E3A8A",
        "role_desc": "Ospite Condiviso / Collaboratore"
    },
    {
        "key": "marcone",
        "id": "f7892976-9bf4-4476-9dc4-258c0a1c3154",
        "email": "marcone@gmail.com",
        "full_name": "Marcone",
        "avatar": "M",
        "color": "#D97706",
        "role_desc": "Amministratore Gruppo"
    }
]


def create_jwt_for_user(user: User) -> str:
    settings = get_settings()
    jwt_secret = settings.SUPABASE_JWT_SECRET or "local-dev-jwt-secret-key-32-chars-long!"
    exp = datetime.now(timezone.utc) + timedelta(days=30)
    token_payload = {
        "sub": user.id,
        "id": user.id,
        "email": user.email,
        "role": "authenticated",
        "user_metadata": {
            "full_name": user.full_name
        },
        "exp": exp
    }
    return jwt.encode(token_payload, jwt_secret, algorithm="HS256")


def ensure_simulator_personas_and_shared_group(db: Session):
    """Garantisce la presenza degli utenti di simulazione e la loro adesione al gruppo condiviso."""
    group = db.query(Group).filter(Group.name.in_(["famiglia marcone", "Spese Condivise & Famiglia 👨‍👩‍👧"])).first()
    if not group:
        group = db.query(Group).first()
    if not group:
        group = Group(
            id="sim-group-famiglia-001",
            name="Spese Condivise & Famiglia 👨‍👩‍👧",
            description="Registro comune per testare la sincronizzazione in tempo reale tra più utenti.",
            icon="fa-house",
            invite_code="FAM-2026",
            created_by="sim-user-marco-0001"
        )
        db.add(group)
        db.flush()

    # Assicura che esista il thread chat corrispondente
    thread = db.query(ChatThread).filter((ChatThread.id == group.id) | (ChatThread.id == f"group_{group.id}")).first()
    if not thread:
        thread = ChatThread(
            id=group.id,
            name=group.name,
            thread_type="group",
            icon=group.icon or "fa-house",
            color="bg-emerald-600",
            description=group.description,
            members='["Marco Rossi", "Laura Bianchi", "Giuseppe Verdi", "Marcone"]'
        )
        db.add(thread)
        db.flush()

    # Crea/aggiorna ogni utente persona e assicura l'adesione al gruppo
    for p in SIMULATOR_PERSONAS:
        u = db.query(User).filter((User.id == p["id"]) | (User.email == p["email"])).first()
        if not u:
            u = User(
                id=p["id"],
                email=p["email"],
                full_name=p["full_name"]
            )
            db.add(u)
            db.flush()

        gm = db.query(GroupMember).filter(GroupMember.group_id == group.id, GroupMember.user_id == u.id).first()
        if not gm:
            gm = GroupMember(
                group_id=group.id,
                user_id=u.id,
                role="admin" if u.id == group.created_by else "member"
            )
            db.add(gm)

    db.commit()
    return group


class SwitchUserRequest(BaseModel):
    user_key: Optional[str] = None
    email: Optional[str] = None


class LaunchWindowRequest(BaseModel):
    user_key: Optional[str] = "laura"
    profile: Optional[str] = None


@router.get("/api/simulator/users")
def get_simulator_users(db: Session = Depends(get_db)):
    """Restituisce la lista degli utenti disponibili per simulare la chat condivisa."""
    ensure_simulator_personas_and_shared_group(db)
    result = []
    for p in SIMULATOR_PERSONAS:
        u = db.query(User).filter(User.email == p["email"]).first()
        if u:
            token = create_jwt_for_user(u)
            result.append({
                "key": p["key"],
                "id": u.id,
                "email": u.email,
                "full_name": u.full_name,
                "avatar": p["avatar"],
                "color": p["color"],
                "role_desc": p["role_desc"],
                "token": token
            })
    return {"users": result}


@router.post("/api/simulator/switch-user")
def switch_simulator_user(payload: SwitchUserRequest, db: Session = Depends(get_db)):
    """Effettua il cambio istantaneo dell'utente attivo restituendo il JWT e il profilo."""
    ensure_simulator_personas_and_shared_group(db)
    target = None
    if payload.user_key:
        for p in SIMULATOR_PERSONAS:
            if p["key"].lower() == payload.user_key.lower():
                target = p
                break
    elif payload.email:
        clean_email = payload.email.strip().lower()
        for p in SIMULATOR_PERSONAS:
            if p["email"].lower() == clean_email:
                target = p
                break

    if not target:
        # Fallback su primo utente
        target = SIMULATOR_PERSONAS[0]

    user = db.query(User).filter(User.email == target["email"]).first()
    if not user:
        user = User(id=target["id"], email=target["email"], full_name=target["full_name"])
        db.add(user)
        db.commit()
        db.refresh(user)

    token = create_jwt_for_user(user)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name
        }
    }


@router.post("/api/simulator/launch-window")
def launch_simulator_window(payload: LaunchWindowRequest):
    """Avvia una seconda finestra desktop per simulare un secondo utente in parallelo."""
    user_key = payload.user_key or "laura"
    prof = payload.profile or f"sessione_{user_key}"
    cmd = [sys.executable, "run_desktop.py", "--user", user_key, "--profile", prof]
    try:
        subprocess.Popen(cmd, cwd=str(get_settings().BASE_DIR))
        return {
            "success": True,
            "message": f"Finestra desktop per '{user_key}' avviata con successo."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Impossibile avviare la finestra: {e}")


@router.get("/simulator/split", response_class=HTMLResponse)
def get_split_screen_simulator():
    """Restituisce la pagina HTML interattiva per testare 2 utenti affiancati (Split-Screen)."""
    html_content = """<!DOCTYPE html>
<html lang="it" class="h-full">
<head>
  <meta charset="UTF-8">
  <title>Simulatore Chat Condivisa Multi-Utente • Dove lo AI messo</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <link rel="stylesheet" href="/static/css/olivetti.css">
  <style>
    body { background-color: #EFECE3; font-family: 'Space Grotesk', sans-serif; }
  </style>
</head>
<body class="h-full flex flex-col overflow-hidden">
  <!-- Top Bar Simulatore -->
  <header class="h-[52px] bg-[#F8F5EE] border-b border-[#E3DDD1] px-4 flex items-center justify-between shrink-0 select-none shadow-xs">
    <div class="flex items-center gap-3">
      <div class="w-7 h-7 rounded-xs bg-[#3C5A48] text-white flex items-center justify-center text-xs font-black shadow-xs">
        <i class="fa-solid fa-users"></i>
      </div>
      <div>
        <h1 class="font-bold text-xs uppercase tracking-tight text-[#222220]">Simulatore Chat Multi-Utente (Split-Screen)</h1>
        <p class="text-[9px] text-[#7A7568] font-mono-code">Test in tempo reale: invia da sinistra e visualizza subito la ricezione a destra</p>
      </div>
    </div>

    <!-- Quick Info -->
    <div class="flex items-center gap-3">
      <span class="stamp-oli stamp-solid-sage text-[9px]">LIVE WEBSOCKET SYNC</span>
      <a href="/" target="_blank" class="px-3 py-1 bg-white border border-[#3C5A48] text-[#3C5A48] hover:bg-[#3C5A48] hover:text-white rounded-xs text-[10px] font-bold transition flex items-center gap-1.5 shadow-2xs">
        <i class="fa-solid fa-arrow-up-right-from-square"></i>
        <span>Apri Finestra Singola</span>
      </a>
    </div>
  </header>

  <!-- Dual Split-Screen Viewport -->
  <div class="flex-1 flex overflow-hidden p-2 gap-2">
    <!-- Utente 1 (Sinistra) -->
    <div class="flex-1 flex flex-col bg-white rounded-xs border-2 border-[#3C5A48] shadow-sm overflow-hidden">
      <div class="h-8 bg-[#3C5A48] text-white px-3 flex items-center justify-between text-xs font-bold font-space">
        <div class="flex items-center gap-2">
          <i class="fa-solid fa-user"></i>
          <span>UTENTE 1: Marco Rossi</span>
        </div>
        <span class="text-[9px] font-mono-code bg-white/20 px-1.5 py-0.5 rounded-xs">marco.rossi@test.it</span>
      </div>
      <iframe src="/?sim_user=marco" class="flex-1 w-full h-full border-none"></iframe>
    </div>

    <!-- Utente 2 (Destra) -->
    <div class="flex-1 flex flex-col bg-white rounded-xs border-2 border-[#C84B31] shadow-sm overflow-hidden">
      <div class="h-8 bg-[#C84B31] text-white px-3 flex items-center justify-between text-xs font-bold font-space">
        <div class="flex items-center gap-2">
          <i class="fa-solid fa-user-check"></i>
          <span>UTENTE 2: Laura Bianchi</span>
        </div>
        <span class="text-[9px] font-mono-code bg-white/20 px-1.5 py-0.5 rounded-xs">laura.bianchi@test.it</span>
      </div>
      <iframe src="/?sim_user=laura" class="flex-1 w-full h-full border-none"></iframe>
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html_content)
