import pytest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.config as app_config
from app.main import app
import app.models.database as db_module
import app.services.crypto_service as crypto_service


@pytest.fixture(scope="session", autouse=True)
def isolate_test_database(tmp_path_factory):
    """
    Fixture ad esecuzione automatica che isola l'intera suite di test:
    1. Database SQLite temporaneo isolato (mai storage/vault.db).
    2. File vault_meta.json temporaneo (mai storage/vault_meta.json).
    3. Directory uploads temporanea (mai storage/uploads).
    """
    test_dir = tmp_path_factory.mktemp("test_storage")
    test_db_path = test_dir / "test_vault.db"
    test_meta_path = test_dir / "vault_meta.json"
    test_uploads_dir = test_dir / "uploads"
    test_uploads_dir.mkdir(parents=True, exist_ok=True)

    # Configura settings per i test
    settings = app_config.Settings(
        STORAGE_DIR=test_uploads_dir,
        DB_PATH=test_db_path,
        DATABASE_URL=f"sqlite:///{test_db_path}"
    )
    app_config._settings = settings

    # Inizializza VaultManager di test con password 1234
    test_vault_mgr = crypto_service.VaultManager(meta_file=test_meta_path)
    test_vault_mgr.initialize_if_needed("1234")
    crypto_service._vault_manager = test_vault_mgr

    # Inizializza motore DB di test e resetta engine/sessionmaker globale
    test_engine = create_engine(
        f"sqlite:///{test_db_path}",
        connect_args={"check_same_thread": False}
    )
    db_module._engine = test_engine
    db_module._session_maker = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db_module.init_db(test_engine)

    def override_get_db():
        db = db_module._session_maker()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[db_module.get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
