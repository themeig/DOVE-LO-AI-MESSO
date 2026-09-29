import io
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import init_db, get_db, Document
from app.models.schemas import ExtractedDocument
from app.api.documents import _process_and_save_single_doc

client = TestClient(app)

def setup_module():
    init_db()


def test_title_sanitization_removes_summary_prefixes():
    """Verifica che titoli con prefissi come 'Riassunto di...' o 'Sintesi del...' vengano bonificati."""
    db = next(get_db())
    try:
        # Caso 1: Riassunto con testo utile seguente
        mock_extracted = ExtractedDocument(
            title="Riassunto del verbale di riunione condominiale",
            doc_type="verbale",
            issuer="Condominio Sole",
            summary="Sintesi dei punti all'ordine del giorno.",
            tags=["condominio"]
        )
        with patch("app.api.documents.get_ai_service") as mock_ai:
            mock_ai.return_value.extract_document.return_value = mock_extracted
            doc = _process_and_save_single_doc(
                b"contenuto verbale", "verbale_riunione.pdf", "application/pdf", "general", db
            )
            assert not doc.title.lower().startswith("riassunto")
            assert "verbale di riunione condominiale" in doc.title.lower()

        # Caso 2: Sintesi troppo lunga (> 9 parole) -> fallback sul nome file
        mock_extracted_long = ExtractedDocument(
            title="Sintesi dettagliata ed esaustiva di tutte le condizioni generali e particolari del contratto di locazione commerciale stipulato nel 2026",
            doc_type="generico",
            summary="Contratto lungo di affitto.",
            tags=[]
        )
        with patch("app.api.documents.get_ai_service") as mock_ai:
            mock_ai.return_value.extract_document.return_value = mock_extracted_long
            doc2 = _process_and_save_single_doc(
                b"contenuto contratto", "contratto_locazione_milano.pdf", "application/pdf", "general", db
            )
            assert not doc2.title.lower().startswith("sintesi")
            assert doc2.title == "Contratto locazione milano"
    finally:
        db.close()


def test_upload_chat_reply_confirms_integral_storage():
    """Verifica che il messaggio di risposta del caricamento rassicuri sull'archiviazione integrale del file."""
    fake_pdf = io.BytesIO(b"%PDF-1.4 test document content original")
    res = client.post(
        "/api/documents/upload",
        files={"file": ("certificato_medico.pdf", fake_pdf, "application/pdf")}
    )
    assert res.status_code == 201
    data = res.json()
    reply = data.get("chat_reply", "")
    assert "File originale integrale" in reply or "File integrale" in reply
    assert "Vedi" in reply or "Scarica" in reply


def test_upload_batch_due_date_and_integrity():
    """Verifica che il caricamento batch non incappi in NameError su due_date e ritorni i documenti integri."""
    file1 = ("doc1.pdf", io.BytesIO(b"%PDF-1.4 content 1"), "application/pdf")
    file2 = ("doc2.pdf", io.BytesIO(b"%PDF-1.4 content 2"), "application/pdf")

    res = client.post(
        "/api/documents/upload-batch",
        files=[("files", file1), ("files", file2)]
    )
    assert res.status_code == 201
    data = res.json()
    assert data["uploaded_count"] == 2
    assert "documents" in data
    assert len(data["documents"]) == 2
    for d in data["documents"]:
        assert "title" in d
        assert "download_url" in d
        assert "file_url" in d


def test_chat_inspect_document_text_content_and_card():
    """Verifica che domande come 'cosa c'è scritto nel documento' chiamino read_vault_document_content e forniscano la scheda."""
    # 1. Carica un documento
    fake_txt = io.BytesIO(b"Articolo 1: Il presente contratto ha durata di anni 4 rinnovabili.")
    upload_res = client.post(
        "/api/documents/upload",
        files={"file": ("accordo_quadro.txt", fake_txt, "text/plain")}
    )
    assert upload_res.status_code == 201

    # 2. Chiedi in chat cosa c'è scritto nel documento
    chat_res = client.post(
        "/api/chat",
        json={"message": "Cosa c'è scritto nel documento accordo quadro?"}
    )
    assert chat_res.status_code == 200
    chat_data = chat_res.json()
    assert chat_data["action"] == "read_vault_document_content"
    assert "Contenuto estratto" in chat_data["reply"] or "Articolo 1" in chat_data["reply"]
    # Verifica che la scheda documento sia allegata
    docs = chat_data.get("documents") or []
    assert len(docs) > 0
    assert any("accordo" in (d.get("title") or "").lower() for d in docs)
