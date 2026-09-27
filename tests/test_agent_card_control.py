import pytest
from datetime import date, timedelta
from unittest.mock import patch, MagicMock
from sqlalchemy.orm import Session

from app.models.database import init_db, get_engine, Document, ChatMessage
from app.services.agent_service import AgentService

def setup_module():
    init_db()

def test_upcoming_deadlines_attaches_documents_offline():
    engine = get_engine()
    with Session(engine) as db:
        d1 = Document(
            title="Bolletta Enel Luce Offline",
            issuer="Enel Energia",
            amount=64.20,
            due_date=date.today() + timedelta(days=5),
            status="da_pagare",
            file_path="uploads/bolletta_enel_off.pdf",
            file_type="application/pdf",
            summary="Bolletta bimestrale luce",
            thread_id="test_cards_thread_offline"
        )
        d2 = Document(
            title="Bolletta Hera Gas Offline",
            issuer="Hera Comm",
            amount=85.00,
            due_date=date.today() + timedelta(days=12),
            status="da_pagare",
            file_path="uploads/bolletta_hera_off.pdf",
            file_type="application/pdf",
            summary="Bolletta gas riscaldamento",
            thread_id="test_cards_thread_offline"
        )
        db.add_all([d1, d2])
        db.commit()

        agent = AgentService()
        agent.settings.OPENROUTER_API_KEY = ""
        resp = agent.run_turn("Cosa ho in scadenza o scaduto da pagare?", db=db, thread_id="test_cards_thread_offline")
        assert resp.documents is not None
        assert len(resp.documents) >= 2
        titles = [d["title"] for d in resp.documents]
        assert "Bolletta Enel Luce Offline" in titles
        assert "Bolletta Hera Gas Offline" in titles

def test_non_vedo_le_schede_recovers_documents_from_previous_turn():
    engine = get_engine()
    with Session(engine) as db:
        d = db.query(Document).filter(Document.title.like("%Enel%")).first()
        if not d:
            d = Document(
                title="Bolletta Enel Luce",
                issuer="Enel Energia",
                amount=64.20,
                due_date=date.today() + timedelta(days=5),
                status="da_pagare",
                file_path="uploads/bolletta_enel_rec.pdf",
                file_type="application/pdf",
                summary="Bolletta bimestrale luce",
                thread_id="test_thread_recovery"
            )
            db.add(d)
            db.commit()

        asst_msg = ChatMessage(
            thread_id="test_thread_recovery",
            sender="assistant",
            message_type="text",
            content="Hai 2 bollette da pagare:\n- Bolletta Enel Luce da 64,20 € scad. tra 5 giorni\n- Bolletta Hera Gas da 85,00 € scad. tra 12 giorni\nEcco le schede di entrambe le bollette, così puoi visualizzarle o scaricarle per procedere al pagamento."
        )
        db.add(asst_msg)
        db.commit()

        agent = AgentService()
        agent.settings.OPENROUTER_API_KEY = ""
        resp = agent.run_turn("non vedo le schede", db=db, thread_id="test_thread_recovery")

        assert resp.action == "show_document_card"
        assert resp.documents is not None
        assert len(resp.documents) >= 1
        # Must never complain about UI anomalies or malfunctions
        assert "anomalia" not in resp.reply.lower()
        assert "malfunzionamento" not in resp.reply.lower()
        assert "inconveniente tecnico" not in resp.reply.lower()

def test_dove_sono_le_schede_not_treated_as_physical_item():
    lower_t = "dove sono le schede?"
    is_cards = any(k in lower_t for k in [
        "non vedo le schede", "dove sono le schede", "non ci sono le schede", "mostra le schede"
    ])
    assert is_cards is True

    is_where = (
        any(k in lower_t for k in ["dove sono", "dov'è"])
        and not is_cards
    )
    assert is_where is False

def test_upcoming_deadlines_online_flow_attaches_cards_when_model_cites_schede():
    """Riproduce lo screenshot utente: l'AI chiama get_upcoming_deadlines e scrive 'Ecco le schede di entrambe le bollette'.
    Verifica che il backend NON azzeri filtered_docs a None e che le schede vengano passate al frontend."""
    engine = get_engine()
    with Session(engine) as db:
        d1 = Document(
            title="Bolletta Enel Luce 2026",
            issuer="Enel Energia",
            amount=64.20,
            due_date=date.today() + timedelta(days=3),
            status="da_pagare",
            file_path="uploads/enel_2026.pdf",
            file_type="application/pdf",
            summary="Bolletta Enel Luce bimestre corrente",
            thread_id="test_online_deadlines"
        )
        d2 = Document(
            title="Bolletta Hera Gas 2026",
            issuer="Hera Comm",
            amount=85.00,
            due_date=date.today() + timedelta(days=10),
            status="da_pagare",
            file_path="uploads/hera_2026.pdf",
            file_type="application/pdf",
            summary="Bolletta gas naturale",
            thread_id="test_online_deadlines"
        )
        db.add_all([d1, d2])
        db.commit()

        agent = AgentService()
        agent.settings.OPENROUTER_API_KEY = "test-sk-key"

        mock_r1 = MagicMock()
        mock_r1.status_code = 200
        mock_r1.json.return_value = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_deadlines_1",
                        "type": "function",
                        "function": {
                            "name": "get_upcoming_deadlines",
                            "arguments": "{}"
                        }
                    }]
                }
            }]
        }

        mock_r2 = MagicMock()
        mock_r2.status_code = 200
        mock_r2.json.return_value = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Ecco le schede di entrambe le bollette, così puoi visualizzarle o scaricarle per procedere al pagamento:\n- Bolletta Enel Luce 2026 da 64,20 €\n- Bolletta Hera Gas 2026 da 85,00 €"
                }
            }]
        }

        with patch("httpx.post", side_effect=[mock_r1, mock_r2]):
            resp = agent.run_turn("Cosa ho in scadenza o scaduto da pagare?", db=db, thread_id="test_online_deadlines")
            assert resp.documents is not None, "Le schede documento dovevano essere allegate!"
            assert len(resp.documents) >= 2
            assert resp.action == "show_document_card"
            titles = [d["title"] for d in resp.documents]
            assert "Bolletta Enel Luce 2026" in titles
            assert "Bolletta Hera Gas 2026" in titles

def test_non_vedo_le_schede_online_direct_reply_sanitizes_and_shows_cards():
    """Se il modello nel turno 'non vedo le schede' risponde direttamente con un testo di scuse e link grezzi,
    il backend intercetta l'intento is_download_or_show, ripulisce la risposta e allega le schede ufficiali."""
    engine = get_engine()
    with Session(engine) as db:
        # Messaggio precedente
        asst_msg = ChatMessage(
            thread_id="test_online_direct",
            sender="assistant",
            message_type="text",
            content="Ecco le schede di entrambe le bollette:\n- Bolletta Enel Luce 2026 da 64,20 €\n- Bolletta Hera Gas 2026 da 85,00 €"
        )
        db.add(asst_msg)
        db.commit()

        agent = AgentService()
        agent.settings.OPENROUTER_API_KEY = "test-sk-key"

        mock_r1 = MagicMock()
        mock_r1.status_code = 200
        mock_r1.json.return_value = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Mi scuso per l'inconveniente tecnico con l'interfaccia che impedisce la visualizzazione corretta delle schede. Ecco i link per scaricare direttamente: /api/documents/1/download"
                }
            }]
        }

        with patch("httpx.post", return_value=mock_r1):
            resp = agent.run_turn("non vedo le schede", db=db, thread_id="test_online_direct")
            assert resp.action == "show_document_card"
            assert resp.documents is not None
            assert len(resp.documents) >= 1
            assert "anomalia" not in resp.reply.lower()
            assert "malfunzionamento" not in resp.reply.lower()
            assert "inconveniente" not in resp.reply.lower()
