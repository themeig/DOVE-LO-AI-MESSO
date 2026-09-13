import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models.database import Base, get_db, init_db

@pytest.fixture(scope="session", autouse=True)
def isolate_test_database():
    """
    Fixture ad esecuzione automatica che isola l'intera suite di test API
    su un database SQLite in-memory, garantendo che NESSUN test possa
    scrivere o inquinare il database reale di produzione (storage/vault.db).
    """
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    init_db(test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
