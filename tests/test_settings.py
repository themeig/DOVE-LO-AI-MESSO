from fastapi.testclient import TestClient
from app.main import app
from app.models.database import init_db

client = TestClient(app)


def test_get_and_update_ai_model_setting():
    # 1. Get model setting
    res = client.get('/api/settings/ai-model')
    assert res.status_code == 200
    data = res.json()
    assert 'current_model' in data
    assert 'available_models' in data
    assert len(data['available_models']) >= 2
    
    # 2. Switch to free model
    update_res = client.post('/api/settings/ai-model', json={'model_id': 'nex-agi/nex-n2.5-pro:free'})
    assert update_res.status_code == 200
    assert update_res.json()['current_model'] == 'nex-agi/nex-n2.5-pro:free'
    assert update_res.json()['is_free'] is True
    
    # 3. Switch back to Gemini 2.5 Flash Lite
    back_res = client.post('/api/settings/ai-model', json={'model_id': 'google/gemini-2.5-flash-lite'})
    assert back_res.status_code == 200
    assert back_res.json()['current_model'] == 'google/gemini-2.5-flash-lite'
    assert back_res.json()['is_free'] is False

    # 4. Switch to thinking model (Gemini 2.5 Pro)
    pro_res = client.post('/api/settings/ai-model', json={'model_id': 'google/gemini-2.5-pro'})
    assert pro_res.status_code == 200
    assert pro_res.json()['current_model'] == 'google/gemini-2.5-pro'
    assert pro_res.json()['current_info']['is_thinking'] is True

    # 5. Switch to auto smart router model
    auto_res = client.post('/api/settings/ai-model', json={'model_id': 'auto'})
    assert auto_res.status_code == 200
    assert auto_res.json()['current_model'] == 'auto'
    assert auto_res.json()['current_info']['name'] == 'Router Intelligente Dinamico'
    assert auto_res.json()['current_info']['tag'] == '🎯 Consigliato'

