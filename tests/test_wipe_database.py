"""Test per l'eliminazione totale del database (Wipe Database) con verifica password e Google Drive."""
import io
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import (
    init_db, get_db, Document, PhysicalItem, ChatMessage,
    WatchedFolder, GoogleDriveCredential
)
from app.services.crypto_service import get_vault_manager

client = TestClient(app)


def setup_module():
    init_db()
    mgr = get_vault_manager()
    mgr.initialize_if_needed("1234")
    # Reset rate limiter state for tests
    mgr.rate_limiter.reset("127.0.0.1")
    mgr.rate_limiter.reset("testclient")


def test_wipe_database_wrong_password():
    """Verifica che una password errata blocchi l'eliminazione con HTTP 401."""
    get_db_func = app.dependency_overrides.get(get_db, get_db)
    db = next(get_db_func())
    try:
        # Inserisci un documento di test
        doc = Document(title="Doc Non Cancellabile", file_path="test.pdf", file_type="pdf", summary="Test")
        db.add(doc)
        db.commit()

        res = client.post(
            "/api/settings/wipe-database",
            json={"password": "password_sbagliata", "delete_drive": False}
        )
        assert res.status_code == 401
        assert "non corretta" in res.json()["detail"].lower()

        # Verifica che il documento esista ancora nel DB
        saved_doc = db.query(Document).filter(Document.id == doc.id).first()
        assert saved_doc is not None
        assert saved_doc.title == "Doc Non Cancellabile"
    finally:
        db.close()


def test_wipe_database_rate_limiting():
    """Verifica che 3 tentativi consecutivi falliti attivino la protezione anti-bruteforce."""
    mgr = get_vault_manager()
    mgr.rate_limiter.reset("127.0.0.1")
    mgr.rate_limiter.reset("testclient")

    # 1° tentativo errato
    r1 = client.post("/api/settings/wipe-database", json={"password": "err1", "delete_drive": False})
    assert r1.status_code == 401

    # 2° tentativo errato
    r2 = client.post("/api/settings/wipe-database", json={"password": "err2", "delete_drive": False})
    assert r2.status_code == 401

    # 3° tentativo errato: scatta il blocco con Retry-After
    r3 = client.post("/api/settings/wipe-database", json={"password": "err3", "delete_drive": False})
    assert r3.status_code in [401, 429]
    assert "Retry-After" in r3.headers

    # Tentativo successivo mentre il blocco è attivo
    r4 = client.post("/api/settings/wipe-database", json={"password": "1234", "delete_drive": False})
    assert r4.status_code == 429

    # Ripristina per i test successivi
    mgr.rate_limiter.reset("127.0.0.1")
    mgr.rate_limiter.reset("testclient")


def test_wipe_database_local_only():
    """Verifica l'eliminazione completa di documenti, oggetti e messaggi con delete_drive=False."""
    get_db_func = app.dependency_overrides.get(get_db, get_db)
    db = next(get_db_func())
    try:
        # Pre-popola dati
        doc = Document(title="Bolletta Da Cancellare", file_path="storage/uploads/fake.pdf", file_type="pdf", summary="Test")
        item = PhysicalItem(item_name="Chiavi cantina", primary_location="Ingresso", thread_id="general")
        msg = ChatMessage(thread_id="general", sender="user", content="Messaggio vecchio")
        db.add_all([doc, item, msg])
        db.commit()

        # Esegui wipe con password corretta
        res = client.post(
            "/api/settings/wipe-database",
            json={"password": "1234", "delete_drive": False}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["drive_deleted"] is False
        assert data["deleted_documents"] >= 1
        assert data["deleted_items"] >= 1

        # Verifica svuotamento tabelle
        assert db.query(Document).count() == 0
        assert db.query(PhysicalItem).count() == 0
        # Solo il messaggio di benvenuto deve essere presente
        messages = db.query(ChatMessage).all()
        assert len(messages) == 1
        assert "azzerato" in messages[0].content.lower()
    finally:
        db.close()


def test_wipe_database_with_drive():
    """Verifica che con delete_drive=True venga invocata la cancellazione remota e cancellate le credenziali."""
    get_db_func = app.dependency_overrides.get(get_db, get_db)
    db = next(get_db_func())
    try:
        cred = GoogleDriveCredential(
            user_email="test@gmail.com",
            access_token="fake_token",
            refresh_token="fake_refresh",
            storage_mode="dual"
        )
        db.add(cred)
        db.commit()

        res = client.post(
            "/api/settings/wipe-database",
            json={"password": "1234", "delete_drive": True}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["drive_deleted"] is True

        # Verifica credenziali rimosse
        assert db.query(GoogleDriveCredential).count() == 0
    finally:
        db.close()
