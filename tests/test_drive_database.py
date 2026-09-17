from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from app.models.database import get_engine, init_db, GoogleDriveCredential, Document

def test_google_drive_credential_model():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        cred = GoogleDriveCredential(
            user_email="test@gmail.com",
            access_token="fake-access-token",
            refresh_token="fake-refresh-token",
            storage_mode="dual",
            root_folder_id="root-123"
        )
        session.add(cred)

        doc = Document(
            title="Bolletta Enel",
            file_path="uploads/test.pdf",
            file_type="pdf",
            doc_type="bolletta",
            summary="Bolletta Enel",
            drive_file_id="drive-file-abc",
            drive_web_url="https://drive.google.com/file/d/drive-file-abc/view"
        )
        session.add(doc)
        session.commit()

        saved_cred = session.query(GoogleDriveCredential).first()
        saved_doc = session.query(Document).first()

        assert saved_cred is not None
        assert saved_cred.user_email == "test@gmail.com"
        assert saved_cred.storage_mode == "dual"
        assert saved_doc.drive_file_id == "drive-file-abc"
        assert "drive.google.com" in saved_doc.drive_web_url


def test_init_db_migration_adds_drive_columns():
    # Simulate an existing database where documents table lacks drive columns
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title VARCHAR(500) NOT NULL,
                file_path VARCHAR(500) NOT NULL,
                file_type VARCHAR(50) NOT NULL,
                summary TEXT NOT NULL
            )
        """))
        conn.commit()

    # Run init_db which should migrate and add drive_file_id and drive_web_url
    init_db(engine)

    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(documents)")).fetchall()]
        assert "drive_file_id" in cols
        assert "drive_web_url" in cols
