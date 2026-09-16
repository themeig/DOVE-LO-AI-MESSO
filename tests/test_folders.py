import os
import io
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.database import get_engine, init_db, Document, WatchedFolder, PendingFileProposal, ChatMessage, get_session_maker
from app.services.folder_service import (
    scan_local_folder,
    open_path_in_explorer,
    select_folder_dialog,
    get_system_folder_presets,
    is_sensitive_file,
    scan_folder_for_sensitive_proposals,
    check_all_watched_folders_for_sensitive_files,
    approve_file_proposal,
    dismiss_file_proposal
)
from app.services.agent_service import AgenticChatService
from app.services.crypto_service import get_vault_manager, decrypt_bytes

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_test_db():
    mgr = get_vault_manager()
    mgr.initialize_if_needed()
    mgr.unlock("1234")
    init_db()

def test_watched_folder_model_and_crud():
    engine = get_engine()
    SessionLocal = get_session_maker(engine)
    with SessionLocal() as db:
        # Create
        wf = WatchedFolder(
            path="C:\\Test\\Fatture_2026",
            name="Fatture 2026",
            thread_id="lavoro",
            is_active=True,
            auto_scan=True
        )
        db.add(wf)
        db.commit()
        db.refresh(wf)
        assert wf.id is not None
        assert wf.name == "Fatture 2026"
        assert wf.file_count == 0

        # Query
        saved = db.query(WatchedFolder).filter(WatchedFolder.path == "C:\\Test\\Fatture_2026").first()
        assert saved is not None
        assert saved.thread_id == "lavoro"

        # Delete
        db.delete(saved)
        db.commit()
        assert db.query(WatchedFolder).filter(WatchedFolder.path == "C:\\Test\\Fatture_2026").first() is None


def test_scan_local_folder_service(tmp_path):
    # Crea file fittizi nella cartella temporanea
    f1 = tmp_path / "bolletta_luce.pdf"
    f1.write_bytes(b"%PDF-1.4 test enel invoice")

    f2 = tmp_path / "ricevuta_spesa.png"
    f2.write_bytes(b"\x89PNG\r\n\x1a\n test png image")

    f3 = tmp_path / "note_ignore.txt"
    f3.write_text("file di testo non supportato")

    engine = get_engine()
    SessionLocal = get_session_maker(engine)
    with SessionLocal() as db:
        # 1. Prima scansione
        res1 = scan_local_folder(str(tmp_path), db, thread_id="general")
        assert res1.scanned_files_count == 2
        assert res1.new_indexed_count == 2
        assert res1.skipped_count == 0
        assert res1.error_count == 0

        # Verifica che i documenti siano stati registrati nel DB come file locali
        doc = db.query(Document).filter(Document.original_path == os.path.normpath(str(f1.resolve()))).first()
        assert doc is not None
        assert doc.is_local_file is True
        assert doc.file_type == "pdf"

        # 2. Seconda scansione (nessun nuovo file -> saltati)
        res2 = scan_local_folder(str(tmp_path), db, thread_id="general")
        assert res2.scanned_files_count == 2
        assert res2.new_indexed_count == 0
        assert res2.skipped_count == 2


def test_open_path_in_explorer_service(tmp_path):
    test_file = tmp_path / "documento.pdf"
    test_file.write_bytes(b"test")

    with patch("subprocess.Popen") as mock_popen, patch("os.startfile", create=True) as mock_startfile:
        res = open_path_in_explorer(str(test_file))
        assert res is True
        # Verifica chiamata explorer
        if os.name == "nt":
            assert mock_popen.called or mock_startfile.called

    # Test file inesistente
    assert open_path_in_explorer("C:\\percorso_completamente_inesistente_12345.xyz") is False


def test_select_folder_dialog_mock():
    with patch("tkinter.filedialog.askdirectory", return_value="C:\\Users\\Leo\\Documenti"):
        path = select_folder_dialog()
        assert path == os.path.normpath("C:\\Users\\Leo\\Documenti")


def test_api_folders_crud_and_scan(tmp_path):
    subfolder = tmp_path / "Contratti"
    subfolder.mkdir()
    pdf_file = subfolder / "contratto_affitto.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 contratto")

    # 1. Select endpoint
    with patch("app.api.folders.select_folder_dialog", return_value=str(subfolder)):
        res_sel = client.post("/api/folders/select")
        assert res_sel.status_code == 200
        assert res_sel.json()["selected_path"] == str(subfolder)
        assert res_sel.json()["cancelled"] is False

    # 2. Add Watched Folder
    res_add = client.post("/api/folders", json={
        "path": str(subfolder),
        "name": "I Miei Contratti",
        "thread_id": "casa",
        "auto_scan": True
    })
    assert res_add.status_code == 201
    data = res_add.json()
    folder_id = data["id"]
    assert data["name"] == "I Miei Contratti"
    assert data["file_count"] >= 1

    # 3. List Watched Folders
    res_list = client.get("/api/folders")
    assert res_list.status_code == 200
    folders = res_list.json()
    assert any(f["id"] == folder_id for f in folders)

    # 4. Trigger Scan Endpoint
    res_scan = client.post(f"/api/folders/{folder_id}/scan")
    assert res_scan.status_code == 200
    scan_data = res_scan.json()
    assert scan_data["scanned_files_count"] >= 1

    # 5. Open in explorer endpoint
    with patch("app.api.folders.open_path_in_explorer", return_value=True):
        res_open = client.post("/api/folders/open-in-explorer", json={"path": str(pdf_file)})
        assert res_open.status_code == 200
        assert res_open.json()["success"] is True

    # 6. Delete Watched Folder
    res_del = client.delete(f"/api/folders/{folder_id}")
    assert res_del.status_code == 200
    assert res_del.json()["success"] is True

    # Verifica che il file sul disco NON sia stato cancellato
    assert pdf_file.exists()


def test_agent_folder_tools(tmp_path):
    subfolder = tmp_path / "FattureStudio"
    subfolder.mkdir()
    inv_file = subfolder / "fattura_enel_studio.pdf"
    inv_file.write_bytes(b"%PDF-1.4 enel")

    agent = AgenticChatService()
    engine = get_engine()
    SessionLocal = get_session_maker(engine)
    with SessionLocal() as db:
        # Aggiungi cartella monitorata
        wf = WatchedFolder(path=str(subfolder), name="Studio", thread_id="lavoro")
        db.add(wf)
        db.commit()

        # 1. Tool list_watched_folders
        list_res = agent.execute_tool("list_watched_folders", {}, db, thread_id="lavoro")
        assert list_res["watched_folders_count"] >= 1
        assert any(f["name"] == "Studio" for f in list_res["folders"])

        # 2. Tool scan_local_folder
        scan_res = agent.execute_tool("scan_local_folder", {"folder_path": str(subfolder)}, db, thread_id="lavoro")
        assert scan_res["success"] is True
        assert scan_res["total_new_indexed"] >= 1

        # 3. Tool open_local_file_in_explorer
        with patch("app.services.folder_service.open_path_in_explorer", return_value=True):
            open_res = agent.execute_tool("open_local_file_in_explorer", {"document_title": "Bolletta Enel"}, db, thread_id="lavoro")
            assert open_res["success"] is True


def test_system_folder_presets():
    engine = get_engine()
    SessionLocal = get_session_maker(engine)
    with SessionLocal() as db:
        presets = get_system_folder_presets(db)
        assert len(presets) >= 3
        keys = [p["key"] for p in presets]
        assert "downloads" in keys
        assert "documents" in keys
        assert "desktop" in keys


def test_is_sensitive_file(tmp_path):
    # 1. File sensibile (bolletta)
    f_sensitive = tmp_path / "bolletta_luce_agosto.pdf"
    f_sensitive.write_bytes(b"%PDF-1.4 test enel bill content")
    is_sens, reason, extracted = is_sensitive_file(f_sensitive)
    assert is_sens is True
    assert "Importo" in reason or "Bolletta" in reason or "Scadenza" in reason

    # 2. File ignorato (eseguibile)
    f_exe = tmp_path / "installer.exe"
    f_exe.write_bytes(b"MZ fake exe")
    is_sens_exe, _, _ = is_sensitive_file(f_exe)
    assert is_sens_exe is False

    # 3. File non supportato
    f_tmp = tmp_path / "download.crdownload"
    f_tmp.write_bytes(b"temp download content")
    is_sens_tmp, _, _ = is_sensitive_file(f_tmp)
    assert is_sens_tmp is False


def test_scan_folder_for_sensitive_proposals_and_approval(tmp_path):
    download_folder = tmp_path / "SimulatedDownloads"
    download_folder.mkdir()

    # Crea un file sensibile (F24)
    f24_file = download_folder / "F24_tributi_settembre.pdf"
    f24_file.write_bytes(b"%PDF-1.4 F24 content")

    engine = get_engine()
    SessionLocal = get_session_maker(engine)
    with SessionLocal() as db:
        # Scansiona cartella per proposte
        proposals = scan_folder_for_sensitive_proposals(
            folder_path=str(download_folder),
            db=db,
            folder_name="Download",
            thread_id="general",
            auto_notify=True
        )
        assert len(proposals) == 1
        prop = proposals[0]
        assert prop.file_name == "F24_tributi_settembre.pdf"
        assert prop.status == "pending"
        assert prop.amount == 2450.0

        # Verifica che sia stato creato il messaggio interattivo in chat
        chat_msg = db.query(ChatMessage).filter(ChatMessage.message_type == "sensitive_proposal").first()
        assert chat_msg is not None
        assert "F24_tributi_settembre.pdf" in chat_msg.content
        assert "SENSITIVE_FILE_PROPOSAL" in chat_msg.metadata_json

        # Seconda scansione: non deve creare duplicati
        proposals_repeat = scan_folder_for_sensitive_proposals(
            folder_path=str(download_folder),
            db=db,
            folder_name="Download",
            thread_id="general",
            auto_notify=True
        )
        assert len(proposals_repeat) == 0

        # Approva la proposta
        success, msg, doc = approve_file_proposal(prop.id, db)
        assert success is True
        assert doc is not None
        assert doc.amount == 2450.0
        assert doc.status == "da_pagare"
        assert doc.is_local_file is False

        # Verifica crittografia del file salvato nel caveau
        mgr = get_vault_manager()
        key = mgr.get_active_key()
        raw_disk_bytes = Path(doc.file_path).read_bytes()
        # Non deve contenere testo in chiaro
        assert raw_disk_bytes != b"%PDF-1.4 F24 content"
        # Deve essere decifrabile correttamente con la chiave
        decrypted = decrypt_bytes(raw_disk_bytes, key)
        assert decrypted == b"%PDF-1.4 F24 content"

        # Verifica stato proposta aggiornato
        db.refresh(prop)
        assert prop.status == "approved"


def test_dismiss_proposal(tmp_path):
    f = tmp_path / "bolletta_scartata.pdf"
    f.write_bytes(b"%PDF-1.4 test")

    engine = get_engine()
    SessionLocal = get_session_maker(engine)
    with SessionLocal() as db:
        proposals = scan_folder_for_sensitive_proposals(str(tmp_path), db, auto_notify=False)
        assert len(proposals) == 1
        prop_id = proposals[0].id

        success, msg = dismiss_file_proposal(prop_id, db)
        assert success is True

        prop = db.query(PendingFileProposal).filter(PendingFileProposal.id == prop_id).first()
        assert prop.status == "dismissed"


def test_api_presets_and_proposals_endpoints(tmp_path):
    # 1. Test GET /api/folders/presets
    res_presets = client.get("/api/folders/presets")
    assert res_presets.status_code == 200
    p_data = res_presets.json()
    assert "presets" in p_data
    assert len(p_data["presets"]) >= 3

    # Crea un file sensibile
    test_pdf = tmp_path / "fattura_enel_test.pdf"
    test_pdf.write_bytes(b"%PDF-1.4 enel")

    engine = get_engine()
    SessionLocal = get_session_maker(engine)
    with SessionLocal() as db:
        # Aggiungi cartella monitorata
        wf = WatchedFolder(path=str(tmp_path), name="Test Temp", thread_id="general")
        db.add(wf)
        db.commit()

    # 2. Trigger scan-sensitive
    res_scan = client.post("/api/folders/scan-sensitive")
    assert res_scan.status_code == 200
    assert res_scan.json()["new_proposals_count"] >= 1

    # 3. GET /api/folders/proposals
    res_props = client.get("/api/folders/proposals")
    assert res_props.status_code == 200
    props_list = res_props.json()["proposals"]
    assert len(props_list) >= 1
    target_prop = props_list[0]
    p_id = target_prop["id"]

    # 4. POST /api/folders/proposals/{id}/approve
    res_app = client.post(f"/api/folders/proposals/{p_id}/approve")
    assert res_app.status_code == 200
    assert res_app.json()["success"] is True

    # 5. Verifica che non sia più nei pending
    res_pending = client.get("/api/folders/proposals?status=pending")
    assert not any(p["id"] == p_id for p in res_pending.json()["proposals"])

