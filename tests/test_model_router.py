import json
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import get_db, set_app_setting, ChatMessage
from app.services.agent_service import AgenticChatService

client = TestClient(app)

def test_resolve_agent_model_heuristics():
    service = AgenticChatService()

    # 1. Storage intents in "auto" mode -> Flash Lite
    storage_queries = [
        "Ho messo il passaporto nel primo cassetto della scrivania",
        "Memorizza che le chiavi di scorta sono all'ingresso",
        "Ho riposto la tenda da campeggio in garage",
        "Ti allego la foto della posizione per il piano",
        "Sposta il caricatore in camera da letto",
        "Salva la posizione della patente nello studio",
        "Patente nel cassetto"
    ]
    for q in storage_queries:
        routed = service.resolve_agent_model(q, q.lower(), "auto")
        assert routed == "google/gemini-2.5-flash-lite", f"Failed for storage query: {q} (got {routed})"

    # 2. Search, deadlines, questions and explanations in "auto" mode -> Pro Thinking
    reasoning_queries = [
        "Dov'è il passaporto?",
        "Dove ho messo le chiavi di scorta?",
        "Cerca la polizza dell'auto nel caveau",
        "Quali sono le prossime scadenze da pagare?",
        "Quanto ho speso in bollette nell'ultimo trimestre?",
        "Somma i totali delle fatture",
        "Spiegami cosa copre la polizza vita",
        "Come funziona l'organizzazione del drive?",
        "Cosa c'è dentro al faldone verde?"
    ]
    for q in reasoning_queries:
        routed = service.resolve_agent_model(q, q.lower(), "auto")
        assert routed == "google/gemini-2.5-pro", f"Failed for reasoning query: {q} (got {routed})"

def test_manual_model_override():
    service = AgenticChatService()

    # If configured model is explicitly set to Pro, storage requests must stay Pro
    assert service.resolve_agent_model("Ho messo il passaporto nel cassetto", "ho messo il passaporto nel cassetto", "google/gemini-2.5-pro") == "google/gemini-2.5-pro"

    # If configured model is explicitly set to Free, search requests must stay Free
    assert service.resolve_agent_model("Dov'è il passaporto?", "dov'è il passaporto?", "nex-agi/nex-n2.5-pro:free") == "nex-agi/nex-n2.5-pro:free"

    # If configured model is explicitly Flash Lite, reasoning requests must stay Flash Lite
    assert service.resolve_agent_model("Spiegami la polizza", "spiegami la polizza", "google/gemini-2.5-flash-lite") == "google/gemini-2.5-flash-lite"

def test_chat_api_routed_model_persisted():
    db_gen = get_db()
    db = next(db_gen)
    try:
        # Set to auto
        set_app_setting(db, "ai_model", "auto")

        # 1. Storage message via Chat API
        res1 = client.post("/api/chat", json={"message": "Ho messo la valigia in soffitta", "thread_id": "general"})
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1.get("routed_model") == "google/gemini-2.5-flash-lite"

        # Check DB metadata_json
        last_msg1 = db.query(ChatMessage).filter(ChatMessage.sender == "assistant").order_by(ChatMessage.id.desc()).first()
        assert last_msg1 is not None
        meta1 = json.loads(last_msg1.metadata_json or "{}")
        assert meta1.get("routed_model") == "google/gemini-2.5-flash-lite"

        # 2. Search message via Chat API
        res2 = client.post("/api/chat", json={"message": "Dov'è la valigia?", "thread_id": "general"})
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2.get("routed_model") == "google/gemini-2.5-pro"

        last_msg2 = db.query(ChatMessage).filter(ChatMessage.sender == "assistant").order_by(ChatMessage.id.desc()).first()
        meta2 = json.loads(last_msg2.metadata_json or "{}")
        assert meta2.get("routed_model") == "google/gemini-2.5-pro"
    finally:
        db.close()
