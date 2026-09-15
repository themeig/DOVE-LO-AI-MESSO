from app.services.document_service import (
    save_uploaded_file,
    get_safe_filename,
    read_decrypted_file,
    migrate_unencrypted_files
)
from app.services.crypto_service import get_vault_manager
from pathlib import Path

def test_save_uploaded_file_is_encrypted_on_disk(tmp_path):
    # Ensure vault is initialized and unlocked
    mgr = get_vault_manager()
    mgr.initialize_if_needed("1234")

    raw_content = b"Contenuto riservato bolletta o foto cassetto"
    saved_path = save_uploaded_file(raw_content, "bolletta.pdf", target_dir=tmp_path)
    
    p = Path(saved_path)
    assert p.exists()
    
    # 1. On disk, bytes MUST be encrypted ciphertext (not plaintext)
    on_disk = p.read_bytes()
    assert on_disk != raw_content
    assert b"Contenuto riservato" not in on_disk
    
    # 2. Reading via read_decrypted_file returns original plaintext in memory
    decrypted = read_decrypted_file(saved_path)
    assert decrypted == raw_content

def test_read_decrypted_file_fallback_legacy_plain(tmp_path):
    plain_file = tmp_path / "legacy.txt"
    plain_file.write_bytes(b"Vecchio file non cifrato")

    # read_decrypted_file handles unencrypted files gracefully
    content = read_decrypted_file(plain_file)
    assert content == b"Vecchio file non cifrato"

def test_migrate_unencrypted_files(tmp_path):
    mgr = get_vault_manager()
    mgr.initialize_if_needed("1234")

    legacy_file = tmp_path / "unencrypted.pdf"
    legacy_file.write_bytes(b"File da migrare a cifrato")

    migrate_unencrypted_files(target_dir=tmp_path)

    # Now it must be encrypted on disk
    on_disk = legacy_file.read_bytes()
    assert on_disk != b"File da migrare a cifrato"
    assert read_decrypted_file(legacy_file) == b"File da migrare a cifrato"
