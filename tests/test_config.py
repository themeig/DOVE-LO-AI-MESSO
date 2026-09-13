from app.config import get_settings

def test_settings_load_defaults():
    settings = get_settings()
    assert settings.DATABASE_URL.startswith("sqlite:///")
    assert settings.STORAGE_DIR is not None
