from datetime import date, datetime
from app.models.database import Document, PhysicalItem, ChatMessage, init_db, get_engine
from sqlalchemy.orm import Session

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
        
        # 2. Item creation
        item = PhysicalItem(
            item_name="Passaporto",
            category="documenti",
            primary_location="Scrivania",
            detailed_location="1° Cassetto"
        )
        session.add(item)
        session.commit()
        
        saved_doc = session.query(Document).first()
        saved_item = session.query(PhysicalItem).first()
        assert saved_doc.amount == 64.20
        assert saved_item.detailed_location == "1° Cassetto"
