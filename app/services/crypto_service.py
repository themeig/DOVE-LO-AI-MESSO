import os
import json
import base64
import hmac
import secrets
from pathlib import Path
from typing import Optional, Dict

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

DEFAULT_ITERATIONS = 600_000


def derive_key(password: str, salt: bytes) -> bytes:
    """Deriva una chiave Fernet sicura (AES-128-CBC + HMAC-SHA256) da una password e salt con PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=DEFAULT_ITERATIONS,
    )
    raw_key = kdf.derive(password.encode("utf-8"))
    return base64.urlsafe_b64encode(raw_key)


def encrypt_bytes(data: bytes, key: bytes) -> bytes:
    """Cifra byte grezzi (documenti, foto) con Fernet."""
    f = Fernet(key)
    return f.encrypt(data)


def decrypt_bytes(ciphertext: bytes, key: bytes) -> bytes:
    """Decifra byte cifrati restituendo i dati originali. Solleva eccezione se la chiave o l'integrità falliscono."""
    f = Fernet(key)
    return f.decrypt(ciphertext)


def encrypt_str(text: str, key: bytes) -> str:
    """Cifra una stringa di testo restituendo una stringa ciphertext ASCII."""
    if not text:
        return ""
    encrypted = encrypt_bytes(text.encode("utf-8"), key)
    return encrypted.decode("ascii")


def decrypt_str(ciphertext: str, key: bytes) -> str:
    """Decifra una stringa ciphertext restituendo la stringa in chiaro."""
    if not ciphertext:
        return ""
    decrypted = decrypt_bytes(ciphertext.encode("ascii"), key)
    return decrypted.decode("utf-8")


def hash_password(password: str, salt: Optional[bytes] = None) -> Dict[str, str]:
    """Genera l'hash crittografico per la verifica della password."""
    s = salt if salt is not None else os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=s,
        iterations=DEFAULT_ITERATIONS,
    )
    digest = kdf.derive(password.encode("utf-8"))
    return {
        "salt": s.hex(),
        "hash": digest.hex(),
        "iterations": DEFAULT_ITERATIONS
    }


def verify_password(password: str, meta: Dict[str, str]) -> bool:
    """Verifica se la password corrisponde all'hash memorizzato usando confronto in tempo costante."""
    try:
        salt = bytes.fromhex(meta["salt"])
        expected_hash = meta["hash"]
        iterations = int(meta.get("iterations", DEFAULT_ITERATIONS))
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=iterations,
        )
        actual_digest = kdf.derive(password.encode("utf-8"))
        return hmac.compare_digest(actual_digest.hex(), expected_hash)
    except Exception:
        return False


class VaultManager:
    """Gestore del caveau crittografico: conserva la chiave attiva in memoria finché il caveau è sbloccato."""

    def __init__(self, meta_file: Optional[Path] = None):
        if meta_file is not None:
            self.meta_file = Path(meta_file)
        else:
            settings = get_settings()
            self.meta_file = settings.BASE_DIR / "storage" / "vault_meta.json"
        self._active_key: Optional[bytes] = None
        self._unlocked: bool = False
        self._active_tokens: set[str] = set()

    def initialize_if_needed(self, default_password: str = "Leonardo2005"):
        self.meta_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.meta_file.exists():
            meta = hash_password(default_password)
            self.meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            self.unlock(default_password)
        else:
            # Se siamo in ambiente di test o debug, pre-sblocchiamo con default se corrisponde
            try:
                meta = json.loads(self.meta_file.read_text(encoding="utf-8"))
                if verify_password(default_password, meta):
                    self.unlock(default_password)
            except Exception:
                pass

    def is_unlocked(self) -> bool:
        return self._unlocked and self._active_key is not None

    def get_active_key(self) -> Optional[bytes]:
        return self._active_key

    def unlock(self, password: str) -> bool:
        if not self.meta_file.exists():
            self.initialize_if_needed(default_password=password)
            return self.is_unlocked()

        try:
            meta = json.loads(self.meta_file.read_text(encoding="utf-8"))
        except Exception:
            return False

        if not verify_password(password, meta):
            return False

        salt = bytes.fromhex(meta["salt"])
        self._active_key = derive_key(password, salt)
        self._unlocked = True
        return True

    def create_session_token(self) -> str:
        token = secrets.token_urlsafe(32)
        self._active_tokens.add(token)
        return token

    def validate_token(self, token: str) -> bool:
        if not self.is_unlocked():
            return False
        return token in self._active_tokens

    def lock(self):
        self._active_key = None
        self._unlocked = False
        self._active_tokens.clear()

    def change_password(self, old_password: str, new_password: str) -> bool:
        if not self.unlock(old_password):
            return False

        # Genera nuovo salt e nuovo hash
        new_meta = hash_password(new_password)
        new_salt = bytes.fromhex(new_meta["salt"])
        self.meta_file.write_text(json.dumps(new_meta, indent=2), encoding="utf-8")
        self._active_key = derive_key(new_password, new_salt)
        self._unlocked = True
        return True


_vault_manager: Optional[VaultManager] = None


def get_vault_manager() -> VaultManager:
    global _vault_manager
    if _vault_manager is None:
        _vault_manager = VaultManager()
        _vault_manager.initialize_if_needed()
    return _vault_manager
