# tests/test_voice_chat.py
import base64
import io
import wave
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.database import get_db, ChatMessage, init_db, get_engine
from app.models.schemas import ChatRequest
from app.services.agent_service import AgenticChatService

client = TestClient(app)

def create_synthetic_wav_base64(duration_seconds: float = 0.5, sample_rate: int = 16000) -> str:
    buf = io.BytesIO()
    num_samples = int(duration_seconds * sample_rate)
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b'\x00\x00' * num_samples)
    return base64.b64encode(buf.getvalue()).decode('utf-8')


def test_chat_request_schema_with_audio():
    b64_audio = create_synthetic_wav_base64(0.2)
    req = ChatRequest(
        message='',
        audio_base64=b64_audio,
        audio_format='wav',
        audio_duration=3.5,
        thread_id='general'
    )
    assert req.audio_base64 == b64_audio
    assert req.audio_format == 'wav'
    assert req.audio_duration == 3.5
    assert req.message == ''


def test_agent_run_turn_offline_with_audio():
    engine = get_engine('sqlite:///:memory:')
    init_db(engine)
    with Session(engine) as session:
        agent = AgenticChatService()
        agent.settings.OPENROUTER_API_KEY = ''
        b64_audio = create_synthetic_wav_base64(0.2)
        resp = agent.run_turn(
            '🎤 Messaggio vocale',
            db=session,
            thread_id='general',
            audio_base64=b64_audio,
            audio_format='wav'
        )
        assert resp is not None
        assert '🎤' in resp.reply or 'vocale' in resp.reply.lower()


def test_api_chat_voice_message_flow():
    b64_audio = create_synthetic_wav_base64(0.5)
    payload = {
        'message': '',
        'audio_base64': b64_audio,
        'audio_format': 'wav',
        'audio_duration': 4.2,
        'thread_id': 'general'
    }

    res = client.post('/api/chat', json=payload)
    assert res.status_code == 200
    data = res.json()
    assert 'reply' in data
    assert len(data['reply']) > 0

    msgs_res = client.get('/api/threads/general/messages')
    assert msgs_res.status_code == 200
    msgs = msgs_res.json()['messages']
    
    user_voice_msgs = [m for m in msgs if m.get('message_type') == 'audio' and m.get('sender') == 'user']
    assert len(user_voice_msgs) > 0
    latest_voice = user_voice_msgs[-1]
    assert latest_voice['metadata'] is not None
    audio_url = latest_voice['metadata'].get('audio_url')
    assert audio_url is not None
    assert audio_url.startswith('/uploads/')
    assert latest_voice['metadata'].get('duration') == 4.2

    audio_res = client.get(audio_url)
    assert audio_res.status_code == 200
    assert audio_res.headers.get('content-type') == 'audio/wav'
    assert len(audio_res.content) > 44


def test_voice_silence_returns_helpful_message_without_vault_search():
    """Verifica che un audio silenzioso non cerchi '🎤 Messaggio vocale' nel caveau ma dia un messaggio cortese."""
    b64_audio = create_synthetic_wav_base64(0.3)
    payload = {
        'message': '',
        'audio_base64': b64_audio,
        'audio_format': 'wav',
        'audio_duration': 1.0,
        'thread_id': 'general'
    }

    res = client.post('/api/chat', json=payload)
    assert res.status_code == 200
    data = res.json()
    reply = data['reply']
    # Non deve MAI dire "Non ho trovato nessun documento o oggetto corrispondente a '🎤 Messaggio vocale'"
    assert "corrispondente a '🎤 Messaggio vocale'" not in reply
    assert "corrispondente a '🎤 messaggio vocale'" not in reply
    assert "parole" in reply.lower() or "vocale" in reply.lower() or "comprendere" in reply.lower()


def test_voice_with_transcribed_speech_stores_and_queries_location():
    """Verifica che un messaggio vocale con testo trascritto esegua l'azione richiesta."""
    b64_audio = create_synthetic_wav_base64(0.4)
    # 1. Memorizza posizione tramite vocale
    store_payload = {
        'message': 'Ho messo il passaporto nella scrivania dello studio',
        'audio_base64': b64_audio,
        'audio_format': 'wav',
        'audio_duration': 2.5,
        'thread_id': 'general'
    }
    r_store = client.post('/api/chat', json=store_payload)
    assert r_store.status_code == 200
    d_store = r_store.json()
    assert "memorizzato" in d_store['reply'].lower() or "scrivania" in d_store['reply'].lower() or "salvato" in d_store['reply'].lower() or "passaporto" in d_store['reply'].lower()

    # 2. Chiedi dov'è l'oggetto tramite vocale
    query_payload = {
        'message': "Dov'è il passaporto?",
        'audio_base64': b64_audio,
        'audio_format': 'wav',
        'audio_duration': 1.8,
        'thread_id': 'general'
    }
    r_query = client.post('/api/chat', json=query_payload)
    assert r_query.status_code == 200
    d_query = r_query.json()
    assert "passaporto" in d_query['reply'].lower()
    assert "scrivania" in d_query['reply'].lower() or "studio" in d_query['reply'].lower()


def test_anti_placeholder_guard_direct_call():
    """Verifica che chiamare direttamente agent.run_turn con il testo placeholder non cerchi nel caveau."""
    engine = get_engine('sqlite:///:memory:')
    init_db(engine)
    with Session(engine) as session:
        agent = AgenticChatService()
        resp = agent.run_turn('🎤 Messaggio vocale', db=session, thread_id='general')
        assert "Non ho trovato nessun documento o oggetto corrispondente a '🎤 Messaggio vocale'" not in resp.reply
        assert "vocale" in resp.reply.lower() or "comando" in resp.reply.lower()
