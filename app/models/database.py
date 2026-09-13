from datetime import datetime, date
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import get_settings

Base = declarative_base()

class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, autoincrement=True)
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
    item_name = Column(String(255), nullable=False, index=True)
    category = Column(String(100), nullable=True)
    primary_location = Column(String(255), nullable=False)
    detailed_location = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sender = Column(String(20), nullable=False)  # 'user' or 'assistant'
    message_type = Column(String(20), default="text")
    content = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

def get_engine(db_url: str = None):
    url = db_url or get_settings().DATABASE_URL
    return create_engine(url, connect_args={"check_same_thread": False})

def init_db(engine=None):
    eng = engine or get_engine()
    Base.metadata.create_all(bind=eng)

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
