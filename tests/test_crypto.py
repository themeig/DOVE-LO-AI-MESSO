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
    password = "1234"
    salt = b"test_salt_12345678"
    key1 = derive_key(password, salt)
    key2 = derive_key(password, salt)
    assert key1 == key2
    assert len(key1) > 0

def test_encrypt_decrypt_bytes():
    password = "1234"
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
    meta = hash_password("1234")
    assert "salt" in meta
    assert "hash" in meta

    assert verify_password("1234", meta) is True
    assert verify_password("PasswordSbagliata", meta) is False

def test_vault_manager_unlock_and_lock(tmp_path):
    meta_file = tmp_path / "vault_meta.json"
    mgr = VaultManager(meta_file=meta_file)
    mgr.initialize_if_needed(default_password="1234")

    # Di default sicuro: il caveau resta bloccato all'inizializzazione
    assert mgr.is_unlocked() is False

    # Unlock with wrong password fails
    success = mgr.unlock("PasswordErrata")
    assert success is False
    assert mgr.is_unlocked() is False

    # Unlock with correct password succeeds
    success = mgr.unlock("1234")
    assert success is True
    assert mgr.is_unlocked() is True
    assert mgr.get_active_key() is not None

    mgr.lock()
    assert mgr.is_unlocked() is False


def test_login_rate_limiter_exponential_backoff():
    from app.services.crypto_service import LoginRateLimiter

    limiter = LoginRateLimiter(attempts_per_block=3, base_block_delay=30.0, backoff_factor=2.0)
    key = "test_ip_client"

    assert limiter.get_failure_count(key) == 0
    assert limiter.get_remaining_attempts_in_block(key) == 3
    is_limited, _ = limiter.is_rate_limited(key)
    assert is_limited is False

    # 1° fallimento: nessun blocco, 2 tentativi rimasti nel blocco
    d1 = limiter.record_failure(key)
    assert d1 == 0.0
    assert limiter.get_failure_count(key) == 1
    assert limiter.get_remaining_attempts_in_block(key) == 2
    assert limiter.is_rate_limited(key)[0] is False

    # 2° fallimento: nessun blocco, 1 tentativo rimasto nel blocco
    d2 = limiter.record_failure(key)
    assert d2 == 0.0
    assert limiter.get_failure_count(key) == 2
    assert limiter.get_remaining_attempts_in_block(key) == 1
    assert limiter.is_rate_limited(key)[0] is False

    # 3° fallimento: scatta il blocco di 30 secondi!
    d3 = limiter.record_failure(key)
    assert d3 == 30.0
    assert limiter.get_failure_count(key) == 3
    assert limiter.is_rate_limited(key)[0] is True

    # 4° fallimento (dopo reset timer): nessun blocco immediato, 2 rimasti
    limiter._attempts[key]["locked_until"] = 0.0
    d4 = limiter.record_failure(key)
    assert d4 == 0.0
    assert limiter.get_failure_count(key) == 4
    assert limiter.get_remaining_attempts_in_block(key) == 2

    # 5° fallimento: nessun blocco
    d5 = limiter.record_failure(key)
    assert d5 == 0.0
    assert limiter.get_remaining_attempts_in_block(key) == 1

    # 6° fallimento (secondo blocco esaurito): scatta il blocco raddoppiato a 60 secondi (1 minuto)!
    d6 = limiter.record_failure(key)
    assert d6 == 60.0
    assert limiter.is_rate_limited(key)[0] is True

    # 7°, 8°, 9° fallimento: scatta blocco a 120 secondi (2 minuti)
    limiter._attempts[key]["locked_until"] = 0.0
    limiter.record_failure(key)  # 7
    limiter.record_failure(key)  # 8
    d9 = limiter.record_failure(key)  # 9
    assert d9 == 120.0

    # Successo: azzera completamente i tentativi
    limiter.record_success(key)
    assert limiter.get_failure_count(key) == 0
    assert limiter.get_remaining_attempts_in_block(key) == 3
    assert limiter.is_rate_limited(key)[0] is False


def test_rate_limiter_persistence_across_restarts(tmp_path):
    from app.services.crypto_service import LoginRateLimiter

    rate_file = tmp_path / "rate_limits.json"
    limiter1 = LoginRateLimiter(storage_file=rate_file)
    key = "127.0.0.1"

    # 3 fallimenti consecutivi -> blocco di 30 secondi
    limiter1.record_failure(key)
    limiter1.record_failure(key)
    d3 = limiter1.record_failure(key)
    assert d3 == 30.0
    assert limiter1.is_rate_limited(key)[0] is True
    assert rate_file.exists()

    # Simula chiusura dell'app e riavvio da zero con nuova istanza del processo
    limiter2 = LoginRateLimiter(storage_file=rate_file)
    assert limiter2.get_failure_count(key) == 3
    is_limited, remaining = limiter2.is_rate_limited(key)
    assert is_limited is True
    assert remaining > 25.0

    # Successo cancella il blocco persistito
    limiter2.record_success(key)
    limiter3 = LoginRateLimiter(storage_file=rate_file)
    assert limiter3.get_failure_count(key) == 0
    assert limiter3.is_rate_limited(key)[0] is False


def test_rate_limiter_tamper_detection(tmp_path):
    import json
    from app.services.crypto_service import LoginRateLimiter

    rate_file = tmp_path / "rate_limits.json"
    signing_key = b"hardware_bound_signing_key_1234"
    key = "127.0.0.1"

    limiter = LoginRateLimiter(storage_file=rate_file, signing_key=signing_key)
    limiter.record_failure(key)
    limiter.record_failure(key)
    limiter.record_failure(key)
    assert limiter.is_rate_limited(key)[0] is True

    # Simula un malintenzionato che modifica manualmente il file per azzerare i fallimenti
    content = json.loads(rate_file.read_text(encoding="utf-8"))
    assert "data" in content and "signature" in content
    content["data"][key]["failures"] = 0  # manomissione senza conoscere la chiave HMAC!
    rate_file.write_text(json.dumps(content), encoding="utf-8")

    # Nuova istanza legge il file manomesso
    limiter2 = LoginRateLimiter(storage_file=rate_file, signing_key=signing_key)

    # La firma HMAC non corrisponde: rilevata manomissione e scatta sanzione massima (1 ora di blocco)
    assert limiter2.is_rate_limited(key)[0] is True
    assert limiter2._attempts[key].get("tamper_detected") is True
    assert limiter2.get_remaining_wait(key) > 3500.0
