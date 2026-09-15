import os
import pytest
from app.services.crypto_service import (
    derive_key,
    encrypt_bytes,
    decrypt_bytes,
    hash_password,
    verify_password,
    get_vault_manager,
    VaultManager
)

def test_derive_key_deterministic():
    password = "Leonardo2005"
    salt = b"test_salt_12345678"
    key1 = derive_key(password, salt)
    key2 = derive_key(password, salt)
    assert key1 == key2
    assert len(key1) > 0

def test_encrypt_decrypt_bytes():
    password = "Leonardo2005"
    salt = os.urandom(16)
    key = derive_key(password, salt)

    plaintext = b"Contenuto segreto del documento PDF o foto"
    ciphertext = encrypt_bytes(plaintext, key)

    assert ciphertext != plaintext
    assert b"Contenuto segreto" not in ciphertext

    decrypted = decrypt_bytes(ciphertext, key)
    assert decrypted == plaintext

def test_decrypt_invalid_key_fails():
    salt = os.urandom(16)
    key1 = derive_key("password_giusta", salt)
    key2 = derive_key("password_errata", salt)

    ciphertext = encrypt_bytes(b"Dati protetti", key1)
    with pytest.raises(Exception):
        decrypt_bytes(ciphertext, key2)

def test_password_hash_and_verify():
    meta = hash_password("Leonardo2005")
    assert "salt" in meta
    assert "hash" in meta

    assert verify_password("Leonardo2005", meta) is True
    assert verify_password("PasswordSbagliata", meta) is False

def test_vault_manager_unlock_and_lock(tmp_path):
    meta_file = tmp_path / "vault_meta.json"
    mgr = VaultManager(meta_file=meta_file)
    mgr.initialize_if_needed(default_password="Leonardo2005")

    # Initially unlocked on fresh init
    assert mgr.is_unlocked() is True
    mgr.lock()
    assert mgr.is_unlocked() is False

    # Unlock with wrong password fails
    success = mgr.unlock("PasswordErrata")
    assert success is False
    assert mgr.is_unlocked() is False

    # Unlock with correct password succeeds
    success = mgr.unlock("Leonardo2005")
    assert success is True
    assert mgr.is_unlocked() is True
    assert mgr.get_active_key() is not None
