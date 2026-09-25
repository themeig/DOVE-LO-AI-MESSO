from datetime import date
import pytest
from app.models.schemas import ExtractedDocument
from app.services.document_service import determine_document_status


def test_document_status_is_paid_explicit():
    doc = ExtractedDocument(
        doc_type="fattura",
        issuer="Fornitore Elettrico",
        amount=150.00,
        due_date="2026-10-20",
        is_paid=True,
        payment_status="quietanzato",
        summary="Fattura per fornitura energia elettrica"
    )
    status = determine_document_status(doc, due_date_obj=date(2026, 10, 20))
    assert status == "quietanzato"


def test_document_status_timbro_pagato_in_summary_safety_net():
    # Anche se is_paid non è stato impostato dal modello, il timbro nel riassunto/titolo attiva la quietanza
    doc = ExtractedDocument(
        doc_type="bolletta",
        issuer="Acquedotto",
        amount=45.20,
        due_date="2026-09-15",
        summary="Bolletta acqua con timbro PAGATO in data 12/09/2026",
        tags=["acqua", "pagato"]
    )
    status = determine_document_status(doc, due_date_obj=date(2026, 9, 15))
    assert status == "quietanzato"


def test_document_status_is_payable_false_on_invoice():
    # Fattura con scadenza ma is_payable esplicitamente False (debito saldato)
    doc = ExtractedDocument(
        doc_type="fattura",
        issuer="Studio Tecnico",
        amount=300.00,
        due_date="2026-11-01",
        is_payable=False,
        summary="Fattura saldata con bonifico bancario"
    )
    status = determine_document_status(doc, due_date_obj=date(2026, 11, 1))
    assert status == "quietanzato"


def test_document_status_unpaid_bill_remains_da_pagare():
    # Bolletta non pagata in scadenza
    doc = ExtractedDocument(
        doc_type="bolletta",
        issuer="Enel Energia",
        amount=64.20,
        due_date="2026-10-28",
        is_payable=True,
        is_paid=False,
        payment_status="da_pagare",
        summary="Bolletta Enel luce bimestre in scadenza a fine ottobre"
    )
    status = determine_document_status(doc, due_date_obj=date(2026, 10, 28))
    assert status == "da_pagare"


def test_document_status_identity_card_has_deadline():
    # Documento con scadenza da monitorare (senza importo)
    doc = ExtractedDocument(
        doc_type="documento_identita",
        issuer="Comune di Milano",
        amount=None,
        due_date="2034-03-15",
        is_payable=True,
        summary="Carta d'identità elettronica valida fino al 2034"
    )
    status = determine_document_status(doc, due_date_obj=date(2034, 3, 15))
    assert status == "da_pagare"


def test_document_status_archived_file_without_deadline():
    # Documento personale o foto senza alcuna scadenza
    doc = ExtractedDocument(
        doc_type="testo_personale",
        issuer=None,
        amount=None,
        due_date=None,
        is_payable=False,
        summary="Note e appunti personali"
    )
    status = determine_document_status(doc, due_date_obj=None)
    assert status == "archiviato"


def test_upload_paid_document_endpoint():
    import io
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models.database import init_db

    init_db()
    client = TestClient(app)
    fake_pdf = io.BytesIO(b"%PDF-1.4 fake content")
    res = client.post(
        "/api/documents/upload",
        files={"file": ("fattura_consulenza_pagata.pdf", fake_pdf, "application/pdf")}
    )
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "quietanzato"
    assert "quietanzato" in data["chat_reply"].lower() or "saldato" in data["chat_reply"].lower()


def test_upload_batch_mixed_documents_endpoint():
    import io
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models.database import init_db

    init_db()
    client = TestClient(app)
    pdf1 = ("bolletta_enel.pdf", io.BytesIO(b"%PDF-1.4 content1"), "application/pdf")
    pdf2 = ("f24_versamento_pagato.pdf", io.BytesIO(b"%PDF-1.4 content2"), "application/pdf")

    res = client.post(
        "/api/documents/upload-batch",
        files=[("files", pdf1), ("files", pdf2)]
    )
    assert res.status_code == 201
    data = res.json()
    assert data["count"] == 2
    statuses = {d["status"] for d in data["documents"]}
    assert "da_pagare" in statuses
    assert "quietanzato" in statuses
    assert "già saldati/quietanzati" in data["chat_reply"]


def test_fast_extract_document_metadata_paid():
    from app.services.archive_service import fast_extract_document_metadata
    
    extracted = fast_extract_document_metadata(
        b"Fattura n. 120/2026 Fornitura materiali. Timbro PAGATO in data 10/03/2026. Totale Euro 340,00",
        "fattura_materiali.txt",
        "text/plain"
    )
    assert extracted.is_paid is True
    assert extracted.payment_status == "quietanzato"
    assert determine_document_status(extracted) == "quietanzato"
