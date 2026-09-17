"""Test per l'endpoint di esportazione del caveau ZIP."""
import io
import json
import zipfile
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def get_auth_headers():
    """Ottieni headers autenticazione (vault sbloccato o non richiesto)."""
    return {}  # conftest.py non richiede auth nei test


def test_export_metadata_empty_vault():
    """Esportazione metadata: deve restituire JSON valido con struttura corretta."""
    res = client.get("/api/export/metadata")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/json")
    cd = res.headers.get("content-disposition", "")
    assert "metadata_" in cd and ".json" in cd

    data = res.json()
    assert data["app"] == "Dove lo AI messo"
    assert data["version"] == "1.0"
    assert "export_date" in data
    assert "stats" in data
    assert isinstance(data["documents"], list)
    assert isinstance(data["physical_items"], list)
    assert isinstance(data["watched_folders"], list)


def test_export_vault_zip_structure():
    """Esportazione ZIP: deve essere un archivio ZIP valido contenente metadata.json."""
    res = client.get("/api/export/vault")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    cd = res.headers.get("content-disposition", "")
    assert "caveau_backup_" in cd and ".zip" in cd

    zip_bytes = io.BytesIO(res.content)
    assert zipfile.is_zipfile(zip_bytes)

    zip_bytes.seek(0)
    with zipfile.ZipFile(zip_bytes, "r") as zf:
        names = zf.namelist()
        assert "metadata.json" in names
        meta = json.loads(zf.read("metadata.json").decode("utf-8"))
        assert meta["app"] == "Dove lo AI messo"
        assert meta["version"] == "1.0"
        assert "stats" in meta
        assert "documents" in meta
        assert "physical_items" in meta


def test_export_metadata_contains_items_after_upload():
    """Upload + export: il documento caricato deve comparire nei metadati."""
    dummy_pdf = io.BytesIO(b"%PDF-1.4 test export document content")
    res_up = client.post(
        "/api/documents/upload",
        files={"file": ("test_export_doc.pdf", dummy_pdf, "application/pdf")},
        data={"thread_id": "general"},
    )
    assert res_up.status_code in (200, 201)

    res = client.get("/api/export/metadata")
    assert res.status_code == 200
    data = res.json()
    assert data["stats"]["total_documents"] >= 1
    titles = [d["title"] for d in data["documents"]]
    assert any(t for t in titles)  # almeno un titolo presente


def test_export_vault_zip_contains_uploaded_file():
    """Upload + export ZIP: il file deve essere nella cartella documents/ dello ZIP."""
    dummy = io.BytesIO(b"%PDF-1.4 zip export verification test")
    res_up = client.post(
        "/api/documents/upload",
        files={"file": ("zip_test_doc.pdf", dummy, "application/pdf")},
        data={"thread_id": "general"},
    )
    assert res_up.status_code in (200, 201)

    res = client.get("/api/export/vault")
    assert res.status_code == 200

    zip_bytes = io.BytesIO(res.content)
    with zipfile.ZipFile(zip_bytes, "r") as zf:
        names = zf.namelist()
        doc_files = [n for n in names if n.startswith("documents/")]
        # Ci deve essere almeno un file nella cartella documents/
        assert len(doc_files) >= 1
        # metadata.json deve sempre esserci
        assert "metadata.json" in names


def test_import_vault_zip_restore():
    """Esporta un backup ZIP e poi lo reimporta tramite /api/export/import."""
    # 1. Carica un documento specifico per il test
    dummy = io.BytesIO(b"%PDF-1.4 unique restore test content")
    res_up = client.post(
        "/api/documents/upload",
        files={"file": ("restore_test_doc.pdf", dummy, "application/pdf")},
        data={"thread_id": "general"},
    )
    assert res_up.status_code in (200, 201)

    # 2. Esporta il backup ZIP
    res_export = client.get("/api/export/vault")
    assert res_export.status_code == 200
    zip_bytes = res_export.content

    # 3. Reimporta lo ZIP
    res_import = client.post(
        "/api/export/import",
        files={"file": ("backup.zip", io.BytesIO(zip_bytes), "application/zip")}
    )
    assert res_import.status_code == 200
    data = res_import.json()
    assert data["success"] is True
    assert data["type"] == "backup"
    assert "restored" in data
    assert "documents" in data["restored"]


def test_import_invalid_file():
    """Verifica che un file non-ZIP venga rifiutato con 400."""
    res = client.post(
        "/api/export/import",
        files={"file": ("fake.zip", io.BytesIO(b"not a valid zip content"), "application/zip")}
    )
    assert res.status_code == 400


def test_import_generic_zip():
    """Verifica l'importazione di uno ZIP generico senza metadata.json."""
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("test1.pdf", b"%PDF-1.4 file 1")
        zf.writestr("test2.txt", b"plain text notes")
    zip_buf.seek(0)

    res = client.post(
        "/api/export/import",
        files={"file": ("generic_docs.zip", zip_buf, "application/zip")}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["restored"]["documents"] == 2

