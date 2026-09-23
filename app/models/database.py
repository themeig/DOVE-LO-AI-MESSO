import json
from datetime import datetime, date, timezone
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, DateTime, Text, inspect, text, types
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.config import get_settings
from app.services.crypto_service import get_vault_manager, encrypt_str, decrypt_str

Base = declarative_base()


class EncryptedString(types.TypeDecorator):
    """Stringa trasparente cifrata su SQLite con la chiave del caveau e decifrata in memoria RAM."""
    impl = types.String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        mgr = get_vault_manager()
        key = mgr.get_active_key()
        if key:
            try:
                return encrypt_str(str(value), key)
            except Exception:
                return str(value)
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        mgr = get_vault_manager()
        key = mgr.get_active_key()
        if isinstance(value, str) and value.startswith("gAAAAAB"):
            if key:
                try:
                    return decrypt_str(value, key)
                except Exception:
                    return ""
            return ""
        return value


class EncryptedText(types.TypeDecorator):
    """Testo lungo trasparente cifrato su SQLite con la chiave del caveau e decifrato in memoria RAM."""
    impl = types.Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        mgr = get_vault_manager()
        key = mgr.get_active_key()
        if key:
            try:
                return encrypt_str(str(value), key)
            except Exception:
                return str(value)
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        mgr = get_vault_manager()
        key = mgr.get_active_key()
        if isinstance(value, str) and value.startswith("gAAAAAB"):
            if key:
                try:
                    return decrypt_str(value, key)
                except Exception:
                    return ""
            return ""
        return value


class ChatThread(Base):
    __tablename__ = "chat_threads"
    id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    thread_type = Column(String(20), nullable=False, default="thematic")  # 'group' or 'thematic'
    icon = Column(String(50), nullable=False, default="fa-compass")
    color = Column(String(50), nullable=False, default="bg-[#128C7E]")
    description = Column(String(255), nullable=True)
    members = Column(Text, nullable=True)  # JSON array string, e.g. '["Io", "Chiara"]'
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String(50), nullable=False, default="general", index=True)
    physical_item_id = Column(Integer, nullable=True, index=True)
    title = Column(EncryptedString(500), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_type = Column(String(50), nullable=False)
    doc_type = Column(String(50), nullable=False, default="generico")
    issuer = Column(EncryptedString(500), nullable=True)
    amount = Column(Float, nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(String(50), nullable=False, default="da_pagare")
    summary = Column(EncryptedText, nullable=False)
    is_local_file = Column(types.Boolean, nullable=False, default=False)
    original_path = Column(String(500), nullable=True)
    drive_file_id = Column(String(255), nullable=True, index=True)
    drive_web_url = Column(String(500), nullable=True)
    category = Column(String(100), nullable=True, index=True)
    category_label = Column(EncryptedString(255), nullable=True)
    category_icon = Column(String(50), nullable=True)
    subfolder = Column(EncryptedString(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class WatchedFolder(Base):
    __tablename__ = "watched_folders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    path = Column(String(500), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    thread_id = Column(String(50), nullable=False, default="general", index=True)
    is_active = Column(types.Boolean, nullable=False, default=True)
    auto_scan = Column(types.Boolean, nullable=False, default=True)
    last_scanned_at = Column(DateTime, nullable=True)
    file_count = Column(Integer, nullable=False, default=0)
    baseline_files_json = Column(Text, nullable=True)
    monitoring_started_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class PendingFileProposal(Base):
    __tablename__ = "pending_file_proposals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    folder_id = Column(Integer, nullable=True, index=True)
    folder_name = Column(String(255), nullable=True)
    file_path = Column(String(500), nullable=False, unique=True, index=True)
    file_name = Column(String(255), nullable=False)
    file_size = Column(Integer, nullable=False, default=0)
    doc_type = Column(String(50), nullable=False, default="generico")
    issuer = Column(EncryptedString(500), nullable=True)
    amount = Column(Float, nullable=True)
    due_date = Column(Date, nullable=True)
    sensitivity_reason = Column(EncryptedString(500), nullable=False)
    summary = Column(EncryptedText, nullable=False)
    status = Column(String(50), nullable=False, default="pending", index=True)  # 'pending', 'approved', 'dismissed'
    thread_id = Column(String(50), nullable=False, default="general", index=True)
    detected_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime, nullable=True)



class PhysicalItem(Base):
    __tablename__ = "physical_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String(50), nullable=False, default="general", index=True)
    document_id = Column(Integer, nullable=True, index=True)
    item_name = Column(EncryptedString(500), nullable=False, index=True)
    category = Column(String(100), nullable=True)
    primary_location = Column(EncryptedString(500), nullable=False)
    detailed_location = Column(EncryptedString(500), nullable=True)
    notes = Column(EncryptedText, nullable=True)
    image_path = Column(String(500), nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String(50), nullable=False, default="general", index=True)
    sender = Column(String(20), nullable=False)  # 'user' or 'assistant'
    message_type = Column(String(20), default="text")
    content = Column(EncryptedText, nullable=False)
    metadata_json = Column(EncryptedText, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class UIEvent(Base):
    __tablename__ = "ui_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String(50), nullable=False, default="general", index=True)
    event_type = Column(String(50), nullable=False)  # 'CARD_RENDER_ERROR', 'FILE_DOWNLOAD_ERROR', 'MEDIA_PREVIEW_ERROR', 'BUTTON_NOT_VISIBLE'
    target_type = Column(String(50), nullable=True)  # 'document', 'physical_item'
    target_id = Column(Integer, nullable=True)
    title = Column(String(255), nullable=True)
    error_details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class GoogleDriveCredential(Base):
    __tablename__ = "google_drive_credentials"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_email = Column(String(255), nullable=True)
    access_token = Column(EncryptedText, nullable=False)
    refresh_token = Column(EncryptedText, nullable=False)
    token_expiry = Column(DateTime, nullable=True)
    storage_mode = Column(String(50), default="dual")  # 'dual', 'cloud_only' o 'local_only'
    root_folder_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


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


_engine = None
_session_maker = None


def get_engine(db_url: str = None):
    global _engine
    if db_url:
        return create_engine(db_url, connect_args={"check_same_thread": False})
    if _engine is None:
        _engine = create_engine(get_settings().DATABASE_URL, connect_args={"check_same_thread": False})
    return _engine


def init_db(engine=None):
    eng = engine or get_engine()
    Base.metadata.create_all(bind=eng)

    # SQLite migration: ensure thread_id and image_path columns exist on pre-existing tables
    inspector = inspect(eng)
    table_names = inspector.get_table_names()
    with eng.connect() as conn:
        for table in ["chat_messages", "documents", "physical_items"]:
            if table in table_names:
                cols = [c["name"] for c in inspector.get_columns(table)]
                if "thread_id" not in cols:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN thread_id VARCHAR(50) DEFAULT 'general'"))
                    conn.commit()

        # Ensure image_path and document_id in physical_items
        if "physical_items" in table_names:
            cols = [c["name"] for c in inspector.get_columns("physical_items")]
            if "image_path" not in cols:
                conn.execute(text("ALTER TABLE physical_items ADD COLUMN image_path VARCHAR(500)"))
                conn.commit()
            if "document_id" not in cols:
                conn.execute(text("ALTER TABLE physical_items ADD COLUMN document_id INTEGER"))
                conn.commit()

        # Ensure physical_item_id, is_local_file, original_path in documents
        if "documents" in table_names:
            cols = [c["name"] for c in inspector.get_columns("documents")]
            if "physical_item_id" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN physical_item_id INTEGER"))
                conn.commit()
            if "is_local_file" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN is_local_file BOOLEAN DEFAULT 0"))
                conn.commit()
            if "original_path" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN original_path VARCHAR(500)"))
                conn.commit()
            if "drive_file_id" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN drive_file_id VARCHAR(255)"))
                conn.commit()
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_drive_file_id ON documents(drive_file_id)"))
            conn.commit()
            if "drive_web_url" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN drive_web_url VARCHAR(500)"))
                conn.commit()
            if "category" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN category VARCHAR(100)"))
                conn.commit()
            if "category_label" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN category_label VARCHAR(255)"))
                conn.commit()
            if "category_icon" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN category_icon VARCHAR(50)"))
                conn.commit()
            if "subfolder" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN subfolder VARCHAR(255)"))
                conn.commit()
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_category ON documents(category)"))
            conn.commit()

        if "watched_folders" in table_names:
            wf_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(watched_folders)")).fetchall()]
            if "baseline_files_json" not in wf_cols:
                conn.execute(text("ALTER TABLE watched_folders ADD COLUMN baseline_files_json TEXT"))
                conn.commit()
            if "monitoring_started_at" not in wf_cols:
                conn.execute(text("ALTER TABLE watched_folders ADD COLUMN monitoring_started_at DATETIME"))
                conn.commit()

        # Seed default threads if table exists and is empty
        if "chat_threads" in table_names:
            count = conn.execute(text("SELECT COUNT(*) FROM chat_threads")).scalar()
            if count == 0:
                now_str = datetime.now(timezone.utc).isoformat()
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
    global _session_maker
    if engine is not None:
        return sessionmaker(autocommit=False, autoflush=False, bind=engine)
    if _session_maker is None:
        _session_maker = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return _session_maker


def get_db():
    SessionLocal = get_session_maker()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
