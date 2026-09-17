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
