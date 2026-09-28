"""
Test suite per il servizio di object storage Cloudflare R2 (documenti di gruppo condivisi).
"""
from app.services.r2_service import MockR2StorageService, get_r2_service


def test_mock_r2_upload_and_presigned_url():
    r2 = MockR2StorageService()
    file_key = r2.upload_group_file(
        file_bytes=b"%PDF-1.4 test document content",
        filename="fattura_utenze.pdf",
        group_id="group-123",
        category="utenze"
    )
    assert "group-123" in file_key
    assert file_key.endswith(".pdf")
    assert r2.file_exists(file_key) is True

    url = r2.generate_presigned_download_url(file_key, expires_in=900)
    assert "https://" in url
    assert "group-123" in url
    assert "expires" in url.lower() or "signature" in url.lower()


def test_mock_r2_delete():
    r2 = MockR2StorageService()
    file_key = r2.upload_group_file(b"data", "test.txt", "group-456")
    assert r2.file_exists(file_key) is True

    res = r2.delete_group_file(file_key)
    assert res is True
    assert r2.file_exists(file_key) is False


def test_get_r2_service_fallback():
    # In assenza di chiavi Cloudflare R2 configurate, restituisce il Mock deterministico
    service = get_r2_service()
    assert service is not None
    assert isinstance(service, MockR2StorageService)
