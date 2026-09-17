# tests/test_drive_agent.py
from datetime import date
from sqlalchemy.orm import Session
from app.models.database import Document, GoogleDriveCredential, init_db, get_engine
from app.services.agent_service import AgenticChatService


def test_agent_drive_status_disconnected():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        agent = AgenticChatService()
        agent.settings.OPENROUTER_API_KEY = ""  # offline deterministic test
        
        # 1. Tool direct execution when disconnected
        res = agent.execute_tool("get_google_drive_status", {}, session)
        assert res["connected"] is False
        assert "root_folder" in res
        assert res["root_folder"] == "DoveLoAIMesso"
        assert len(res["categories"]) > 0

        # 2. Intent interception when disconnected
        resp = agent.run_turn("dimmi come sono organizzate le cartelle in google drive e cosa hai salvato finora", session)
        assert resp.action == "get_google_drive_status"
        assert "non è attualmente collegato" in resp.reply.lower() or "non è collegato" in resp.reply.lower()
        assert "strumenti" in resp.reply.lower()


def test_agent_drive_status_connected_and_intent():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        # Crea credenziali Drive
        cred = GoogleDriveCredential(
            user_email="riccardo@example.com",
            storage_mode="cloud_only",
            access_token="fake_access_token",
            refresh_token="fake_refresh_token"
        )
        session.add(cred)

        # Documento 1: senza scadenza (es. file credenziali)
        doc1 = Document(
            title="Credenziali API Google",
            file_path="uploads/client_secret.json",
            file_type="json",
            doc_type="generico",
            issuer="Google Cloud",
            amount=None,
            due_date=None,
            status="archiviato",
            summary="Credenziali OAuth 2.0 per Google Drive",
            drive_file_id="drv_id_secret_123",
            drive_web_url="https://drive.google.com/file/d/drv_id_secret_123/view"
        )
        # Documento 2: con scadenza 2026 (es. bolletta)
        doc2 = Document(
            title="Bolletta Enel Energia Ottobre",
            file_path="uploads/enel_ottobre.pdf",
            file_type="pdf",
            doc_type="bolletta",
            issuer="Enel",
            amount=64.20,
            due_date=date(2026, 10, 28),
            status="da_pagare",
            summary="Bolletta Enel luce",
            drive_file_id="drv_id_enel_456",
            drive_web_url="https://drive.google.com/file/d/drv_id_enel_456/view"
        )
        session.add_all([doc1, doc2])
        session.commit()

        agent = AgenticChatService()
        agent.settings.OPENROUTER_API_KEY = ""  # offline deterministic test

        # 1. Test get_google_drive_status tool
        status_res = agent.execute_tool("get_google_drive_status", {}, session)
        assert status_res["connected"] is True
        assert status_res["user_email"] == "riccardo@example.com"
        assert status_res["storage_mode"] == "cloud_only"
        assert status_res["total_files_on_drive"] == 2
        assert "DoveLoAIMesso / Documenti & Foto" in status_res["folders_overview"]
        assert "DoveLoAIMesso / 2026 / Bollette & Utenze" in status_res["folders_overview"]

        # 2. Test direct user question about Google Drive
        resp = agent.run_turn("dimmi in google drive come hai organizzato le cartelle e cosa hai salvato per ora", session)
        assert resp.action == "get_google_drive_status"
        assert "riccardo@example.com" in resp.reply
        assert "Solo Google Drive" in resp.reply
        assert "DoveLoAIMesso" in resp.reply
        assert "Credenziali API Google" in resp.reply
        assert "Bolletta Enel Energia Ottobre" in resp.reply
        assert len(resp.documents) == 2
        assert resp.documents[0].get("drive_file_id") is not None
        assert resp.documents[0].get("drive_web_url") is not None

        # 3. Test prompt injection awareness
        prompt = agent.build_system_prompt(session)
        assert "[STATO SINCRONIZZAZIONE GOOGLE DRIVE CLOUD SYNC]" in prompt
        assert "riccardo@example.com" in prompt
        assert "cloud_only" in prompt
        assert "Credenziali API Google" in prompt

        # 4. Test search_vault tool includes drive metadata
        search_res = agent.execute_tool("search_vault", {"query": "credenziali"}, session)
        found = search_res.get("found_documents", [])
        assert len(found) >= 1
        assert found[0]["drive_file_id"] == "drv_id_secret_123"
        assert found[0]["drive_web_url"] == "https://drive.google.com/file/d/drv_id_secret_123/view"
        assert found[0]["is_on_drive"] is True

        # 5. Test that document search mentioning drive routes to search_vault and finds doc (not general drive explanation)
        doc_polizza = Document(
            title="Polizza Auto Allianz 2026",
            file_path="uploads/polizza_allianz.pdf",
            file_type="pdf",
            doc_type="contratto",
            issuer="Allianz",
            amount=420.0,
            due_date=date(2026, 12, 1),
            status="archiviato",
            summary="Polizza assicurazione auto annuale",
            drive_file_id="drv_polizza_789",
            drive_web_url="https://drive.google.com/file/d/drv_polizza_789/view"
        )
        session.add(doc_polizza)
        session.commit()

        resp_polizza = agent.run_turn("cerca polizza nel drive", session)
        assert resp_polizza.action in ["search_vault", "show_document_card"]
        found_docs = resp_polizza.documents or (resp_polizza.data or {}).get("found_documents", [])
        assert any("Polizza" in (d.get("title") or "") for d in found_docs)
