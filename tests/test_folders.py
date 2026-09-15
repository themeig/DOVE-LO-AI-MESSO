import os
import io
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.database import get_engine, init_db, Document, WatchedFolder, get_session_maker
from app.services.folder_service import scan_local_folder, open_path_in_explorer, select_folder_dialog
from app.services.agent_service import AgenticChatService
from app.services.crypto_service import get_vault_manager

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_test_db():
    mgr = get_vault_manager()
    mgr.initialize_if_needed()
    mgr.unlock("Leonardo2005")
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
