import datetime
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.database import get_db, Document, init_db

client = TestClient(app)

def test_dashboard_scadenzario_filter():
    init_db()
    # Recupera sessione db per creare documenti con date varie
    db_gen = get_db()
    db: Session = next(db_gen)

    # Crea 3 documenti con scadenze diverse e 1 senza scadenza
    d_unpaid = Document(
        title="Bolletta Luce Enel Ottobre",
        file_path="storage/fake_enel.pdf",
        file_type="pdf",
        doc_type="bolletta",
        issuer="Enel",
        amount=85.50,
        due_date=datetime.date(2026, 10, 15),
        status="da_pagare",
        summary="Bolletta energia elettrica da pagare"
    )
    d_paid = Document(
        title="Tributo F24 Settembre",
        file_path="storage/fake_f24.pdf",
        file_type="pdf",
        doc_type="f24",
        issuer="Agenzia Entrate",
        amount=450.00,
        due_date=datetime.date(2026, 9, 16),
        status="quietanzato",
        summary="Modello F24 già versato"
    )
    d_idcard = Document(
        title="Carta d'Identita Elettronica",
        file_path="storage/fake_cie.pdf",
        file_type="pdf",
        doc_type="carta_identita",
        issuer="Ministero Interno",
        amount=None,
        due_date=datetime.date(2035, 1, 1),
        status="archiviato",
        summary="Documento d'identità personale valido fino al 2035"
    )
    d_nodesc = Document(
        title="Canzone Poesia Senza Scadenza",
        file_path="storage/fake_song.txt",
        file_type="txt",
        doc_type="canzone",
        issuer=None,
        amount=None,
        due_date=None,
        status="archiviato",
        summary="Testo poetico"
    )

    db.add_all([d_unpaid, d_paid, d_idcard, d_nodesc])
    db.commit()

    # Richiesta con filtro scadenzario
    res = client.get("/api/dashboard?filter=scadenzario")
    assert res.status_code == 200
    data = res.json()

    assert "kpi" in data
    assert data["kpi"]["total_deadlines_count"] >= 3

    records = data["records"]
    rec_ids = [r["id"] for r in records]
    
    # Devono essere presenti tutti e tre i documenti con scadenza
    assert d_unpaid.id in rec_ids
    assert d_paid.id in rec_ids
    assert d_idcard.id in rec_ids
    # Non deve essere presente il documento senza scadenza
    assert d_nodesc.id not in rec_ids

    # Verifica che tutti i record abbiano i campi di urgenza e countdown valorizzati
    for r in records:
        assert r["due_date"] is not None
        assert r["urgency"] is not None
        assert r["urgency_label"] is not None
        assert r["download_url"] is not None

    # Verifica alias scadenziario e calendar
    res_alias1 = client.get("/api/dashboard?filter=scadenziario")
    assert res_alias1.status_code == 200
    assert len(res_alias1.json()["records"]) == len(records)

    res_alias2 = client.get("/api/dashboard?filter=calendar")
    assert res_alias2.status_code == 200
    assert len(res_alias2.json()["records"]) == len(records)
