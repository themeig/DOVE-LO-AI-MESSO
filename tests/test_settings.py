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


def test_get_openrouter_credits_mocked():
    from unittest.mock import patch, MagicMock

    mock_credits = MagicMock()
    mock_credits.status_code = 200
    mock_credits.json.return_value = {
        "data": {
            "total_credits": 50.0,
            "total_usage": 20.0
        }
    }

    mock_key = MagicMock()
    mock_key.status_code = 200
    mock_key.json.return_value = {
        "data": {
            "label": "Test Key",
            "usage": 5.0,
            "usage_daily": 0.5,
            "usage_weekly": 1.0,
            "usage_monthly": 5.0,
            "is_free_tier": False,
            "free_model_daily_requests": {"remaining": 1000}
        }
    }

    with patch("app.api.settings.get_app_setting", return_value="sk-or-v1-mock1234567890abcdef"), \
         patch("httpx.get", side_effect=[mock_credits, mock_key]):
        res = client.get("/api/settings/openrouter-credits")
        assert res.status_code == 200
        data = res.json()
        assert data["connected"] is True
        assert data["is_configured"] is True
        assert data["total_credits"] == 50.0
        assert data["total_usage"] == 20.0
        assert data["remaining_credits"] == 30.0
        assert data["percentage_remaining"] == 60.0
        assert data["status_level"] == "healthy"
        assert data["key_label"] == "Test Key"


def test_get_openrouter_credits_no_key_scenario():
    from unittest.mock import patch
    from app.config import get_settings

    with patch.object(get_settings(), "OPENROUTER_API_KEY", ""):
        with patch("app.api.settings.get_app_setting", return_value=""):
            res = client.get("/api/settings/openrouter-credits")
            assert res.status_code == 200
            data = res.json()
            assert data["connected"] is False
            assert data["has_key"] is False
            assert data["remaining_credits"] == 0.0


