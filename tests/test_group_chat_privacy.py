"""
Test suite per la privacy delle chat di gruppo e le notifiche di inserimento e pagamento:
1. Domande e risposte private con l'assistente visibili SOLO all'utente richiedente.
2. Inserimento documenti con attribuzione visibile a tutto il gruppo.
3. Pagamento bollette con attribuzione visibile a tutto il gruppo.
"""
import io
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.database import init_db
from app.services.crypto_service import get_vault_manager

client = TestClient(app)


def setup_module():
    init_db()
    mgr = get_vault_manager()
    mgr.initialize_if_needed("1234")


def test_group_chat_privacy_and_notifications():
    # 1. Registrazione di due utenti distinti: Marco Rossi e Laura Bianchi
    signup_marco = client.post("/api/auth/cloud/signup", json={
        "email": "marco.privacy@test.it",
        "password": "PasswordMarco123!",
        "full_name": "Marco Rossi"
    })
    assert signup_marco.status_code in (200, 201)
    token_marco = signup_marco.json()["access_token"]
    user_marco = signup_marco.json()["user"]

    signup_laura = client.post("/api/auth/cloud/signup", json={
        "email": "laura.privacy@test.it",
        "password": "PasswordLaura123!",
        "full_name": "Laura Bianchi"
    })
    assert signup_laura.status_code in (200, 201)
    token_laura = signup_laura.json()["access_token"]
    user_laura = signup_laura.json()["user"]

    headers_marco = {"Authorization": f"Bearer {token_marco}"}
    headers_laura = {"Authorization": f"Bearer {token_laura}"}

    # 2. Creazione del thread di gruppo condiviso
    create_thread_res = client.post(
        "/api/threads",
        json={
            "name": "Condominio & Casa",
            "thread_type": "group",
            "members": ["Marco Rossi", "Laura Bianchi"]
        },
        headers=headers_marco
    )
    assert create_thread_res.status_code == 201
    group_thread_id = create_thread_res.json()["id"]

    # 3. Privacy delle conversazioni: Marco fa una domanda personale all'assistente nel gruppo
    chat_res = client.post(
        "/api/chat",
        json={
            "message": "Che giorno è oggi?",
            "thread_id": group_thread_id
        },
        headers=headers_marco
    )
    assert chat_res.status_code == 200

    # Verifica per Marco: Marco vede il suo messaggio e la risposta dell'assistente
    res_msgs_marco = client.get(f"/api/threads/{group_thread_id}/messages", headers=headers_marco)
    assert res_msgs_marco.status_code == 200
    marco_feed = res_msgs_marco.json()["messages"]
    contents_marco = [m["content"] for m in marco_feed]
    assert any("Che giorno è oggi?" in c for c in contents_marco)

    # Verifica per Laura: Laura NON deve vedere la domanda di Marco né la risposta dell'assistente
    res_msgs_laura = client.get(f"/api/threads/{group_thread_id}/messages", headers=headers_laura)
    assert res_msgs_laura.status_code == 200
    laura_feed = res_msgs_laura.json()["messages"]
    contents_laura = [m["content"] for m in laura_feed]
    assert not any("Che giorno è oggi?" in c for c in contents_laura)

    # 4. Inserimento documento con attribuzione: Marco carica una bolletta nel gruppo
    fake_pdf = io.BytesIO(b"%PDF-1.4 Bolletta Enel Condominio")
    upload_res = client.post(
        "/api/documents/upload",
        data={"thread_id": group_thread_id},
        files={"file": ("bolletta_luce.pdf", fake_pdf, "application/pdf")},
        headers=headers_marco
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["document_id"]
    doc_title = upload_res.json()["title"]

    # Verifica per Laura: Laura riceve e visualizza il messaggio dell'inserimento con il nome dell'autore
    res_msgs_laura_after_upload = client.get(f"/api/threads/{group_thread_id}/messages", headers=headers_laura)
    assert res_msgs_laura_after_upload.status_code == 200
    laura_feed_after_upload = res_msgs_laura_after_upload.json()["messages"]
    doc_msg = next((m for m in laura_feed_after_upload if "ha inserito questo documento" in m["content"]), None)
    assert doc_msg is not None
    assert "Marco Rossi" in doc_msg["content"]
    assert doc_title in doc_msg["content"]

    # 5. Notifica di pagamento: Laura paga/quieta la bolletta
    pay_res = client.patch(
        f"/api/documents/{doc_id}/status",
        json={"status": "quietanzato"},
        headers=headers_laura
    )
    assert pay_res.status_code == 200
    assert pay_res.json()["status"] == "quietanzato"

    # Verifica per Marco: Marco vede la notifica che Laura Bianchi ha pagato la bolletta
    res_msgs_marco_after_pay = client.get(f"/api/threads/{group_thread_id}/messages", headers=headers_marco)
    assert res_msgs_marco_after_pay.status_code == 200
    marco_feed_after_pay = res_msgs_marco_after_pay.json()["messages"]
    pay_msg = next((m for m in marco_feed_after_pay if "ha pagato la bolletta" in m["content"]), None)
    assert pay_msg is not None
    assert "Laura Bianchi" in pay_msg["content"]
    assert doc_title in pay_msg["content"]
