from datetime import date, datetime
from app.models.database import Document, PhysicalItem, ChatMessage, init_db, get_engine
from app.services.crypto_service import get_vault_manager
from sqlalchemy.orm import Session
from sqlalchemy import text

def test_document_and_item_crud():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        # 1. Document creation
        doc = Document(
            title="Bolletta Enel",
            file_path="uploads/test.pdf",
            file_type="pdf",
            doc_type="bolletta",
            issuer="Enel",
            amount=64.20,
            due_date=date(2026, 10, 28),
            status="da_pagare",
            summary="Bolletta luce"
        )
        session.add(doc)
        
        # 2. Item creation with image_path
        item = PhysicalItem(
            item_name="Passaporto",
            category="documenti",
            primary_location="Scrivania",
            detailed_location="1° Cassetto",
            image_path="uploads/passaporto_cassetto.jpg"
        )
        session.add(item)
        session.commit()
        
        saved_doc = session.query(Document).first()
        saved_item = session.query(PhysicalItem).first()
        assert saved_doc.amount == 64.20
        assert saved_item.detailed_location == "1° Cassetto"
        assert saved_item.image_path == "uploads/passaporto_cassetto.jpg"

def test_encrypted_columns_in_sqlite():
    mgr = get_vault_manager()
    mgr.initialize_if_needed("Leonardo2005")

    engine = get_engine("sqlite:///:memory:")
    init_db(engine)

    with Session(engine) as session:
        msg = ChatMessage(
            thread_id="general",
            sender="user",
            message_type="text",
            content="Mio messaggio confidenziale con dati sensibili"
        )
        session.add(msg)
        session.commit()

        # 1. Quando letto via SQLAlchemy: il testo viene decifrato trasparentemente
        loaded = session.query(ChatMessage).first()
        assert loaded.content == "Mio messaggio confidenziale con dati sensibili"

    # 2. Quando ispezionato a basso livello su SQLite con SQL puro:
    # il valore deve essere salvato cifrato (ciphertext Fernet)
    with engine.connect() as conn:
        raw_row = conn.execute(text("SELECT content FROM chat_messages")).fetchone()
        raw_content = raw_row[0]
        assert raw_content != "Mio messaggio confidenziale con dati sensibili"
        assert "confidenziale" not in raw_content
