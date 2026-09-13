import json
from datetime import datetime, date
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, DateTime, Text, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.config import get_settings

Base = declarative_base()

class ChatThread(Base):
    __tablename__ = "chat_threads"
    id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    thread_type = Column(String(20), nullable=False, default="thematic")  # 'group' or 'thematic'
    icon = Column(String(50), nullable=False, default="fa-compass")
    color = Column(String(50), nullable=False, default="bg-[#128C7E]")
    description = Column(String(255), nullable=True)
    members = Column(Text, nullable=True)  # JSON array string, e.g. '["Io", "Chiara"]'
    created_at = Column(DateTime, default=datetime.utcnow)

class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String(50), nullable=False, default="general", index=True)
    title = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_type = Column(String(50), nullable=False)
    doc_type = Column(String(50), nullable=False, default="generico")
    issuer = Column(String(255), nullable=True)
    amount = Column(Float, nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(String(50), nullable=False, default="da_pagare")
    summary = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class PhysicalItem(Base):
    __tablename__ = "physical_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String(50), nullable=False, default="general", index=True)
    item_name = Column(String(255), nullable=False, index=True)
    category = Column(String(100), nullable=True)
    primary_location = Column(String(255), nullable=False)
    detailed_location = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String(50), nullable=False, default="general", index=True)
    sender = Column(String(20), nullable=False)  # 'user' or 'assistant'
    message_type = Column(String(20), default="text")
    content = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

class AppSetting(Base):
    __tablename__ = "app_settings"
    key = Column(String(50), primary_key=True)
    value = Column(Text, nullable=False)

def get_app_setting(db: Session, key: str, default: str = "") -> str:
    s = db.query(AppSetting).filter(AppSetting.key == key).first()
    return s.value if s else default

def set_app_setting(db: Session, key: str, value: str):
    s = db.query(AppSetting).filter(AppSetting.key == key).first()
    if s:
        s.value = value
    else:
        s = AppSetting(key=key, value=value)
        db.add(s)
    db.commit()

def get_engine(db_url: str = None):
    url = db_url or get_settings().DATABASE_URL
    return create_engine(url, connect_args={"check_same_thread": False})

def init_db(engine=None):
    eng = engine or get_engine()
    Base.metadata.create_all(bind=eng)

    # SQLite migration: ensure thread_id column exists on pre-existing tables
    inspector = inspect(eng)
    table_names = inspector.get_table_names()
    with eng.connect() as conn:
        for table in ["chat_messages", "documents", "physical_items"]:
            if table in table_names:
                cols = [c["name"] for c in inspector.get_columns(table)]
                if "thread_id" not in cols:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN thread_id VARCHAR(50) DEFAULT 'general'"))
                    conn.commit()

        # Seed default threads if table exists and is empty
        if "chat_threads" in table_names:
            count = conn.execute(text("SELECT COUNT(*) FROM chat_threads")).scalar()
            if count == 0:
                now_str = datetime.utcnow().isoformat()
                defaults = [
                    ("general", "Dove lo AI messo", "thematic", "fa-compass", "bg-[#128C7E]", "Assistente Personale & Caveau Globale", json.dumps(["Io"])),
                    ("famiglia", "Famiglia 👨‍👩‍👧", "group", "fa-users", "bg-emerald-600", "Documenti di casa, bollette e posizioni condivise", json.dumps(["Io", "Famiglia"])),
                    ("lavoro", "Lavoro & Studio 💼", "thematic", "fa-briefcase", "bg-blue-600", "Contratti, note, buste paga e attrezzatura", json.dumps(["Io"])),
                    ("casa", "Casa & Utenze 🏠", "thematic", "fa-house", "bg-amber-600", "Utenze, manutenzioni e chiavi di riserva", json.dumps(["Io"]))
                ]
                for tid, tname, ttype, ticon, tcolor, tdesc, tmembers in defaults:
                    conn.execute(
                        text("INSERT INTO chat_threads (id, name, thread_type, icon, color, description, members, created_at) "
                             "VALUES (:id, :name, :type, :icon, :color, :desc, :members, :now)"),
                        {"id": tid, "name": tname, "type": ttype, "icon": ticon, "color": tcolor, "desc": tdesc, "members": tmembers, "now": now_str}
                    )
                conn.commit()

def get_session_maker(engine=None):
    eng = engine or get_engine()
    return sessionmaker(autocommit=False, autoflush=False, bind=eng)

def get_db():
    SessionLocal = get_session_maker()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

