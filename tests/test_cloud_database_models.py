"""
Test suite per i modelli database multi-account, gruppi e registro attività (ActivityEvent).
"""
import pytest
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.models.database import (
    init_db,
    get_engine,
    User,
    Group,
    GroupMember,
    ActivityEvent,
    Document,
    PhysicalItem
)


def test_create_group_and_membership():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as db:
        user1 = User(id="user-123", email="marco@test.it", full_name="Marco Rossi")
        group = Group(id="group-abc", name="Famiglia Rossi", invite_code="ROX-8821", created_by=user1.id)
        db.add_all([user1, group])
        db.flush()

        member = GroupMember(group_id=group.id, user_id=user1.id, role="admin")
        event = ActivityEvent(
            group_id=group.id,
            actor_user_id=user1.id,
            actor_name="Marco",
            event_type="DOCUMENT_UPLOADED",
            title="Bolletta Enel",
            content="Importo: 64,20 €",
            payload={"amount": 64.20, "due_date": "2026-10-28"}
        )
        db.add_all([member, event])
        db.commit()

        assert group.name == "Famiglia Rossi"
        assert group.invite_code == "ROX-8821"
        assert event.event_type == "DOCUMENT_UPLOADED"
        assert event.payload["amount"] == 64.20
        assert member.role == "admin"


def test_document_and_item_group_id_support():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as db:
        user = User(id="user-456", email="giulia@test.it", full_name="Giulia Bianchi")
        group = Group(id="group-xyz", name="Studio Conti", invite_code="CONTI-99", created_by=user.id)
        db.add_all([user, group])
        db.flush()

        doc = Document(
            title="Contratto Locazione",
            file_path="uploads/contratto.pdf",
            file_type="pdf",
            doc_type="contratto",
            summary="Contratto di locazione registrato",
            group_id=group.id,
            user_id=user.id
        )
        item = PhysicalItem(
            item_name="Chiave Cassaforte",
            primary_location="Studio",
            detailed_location="Cassetto 2",
            group_id=group.id,
            user_id=user.id
        )
        db.add_all([doc, item])
        db.commit()

        assert doc.group_id == "group-xyz"
        assert item.group_id == "group-xyz"
        assert doc.user_id == "user-456"
