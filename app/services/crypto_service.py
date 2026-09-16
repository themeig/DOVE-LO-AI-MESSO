import os
import json
import base64
import hmac
import secrets
import time
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


class LoginRateLimiter:
    """
    Protezione anti-bruteforce a blocchi con backoff esponenziale.
    Regola:
    - Primi 3 tentativi: immediati. Al 3° fallimento: blocco di 30 secondi.
    - Successivi 3 tentativi: immediati. Al 6° fallimento (totale): blocco di 1 minuto (60s).
    - Successivi 3 tentativi: immediati. Al 9° fallimento: blocco di 2 minuti (120s).
    - E così via raddoppiando per ogni blocco fino al ritardo massimo (default 3600s).
    Al login riuscito, il conteggio fallimenti per la chiave viene azzerato.
    """

    def __init__(
        self,
        attempts_per_block: int = 3,
        base_block_delay: float = 30.0,
        max_delay: float = 3600.0,
        backoff_factor: float = 2.0
    ):
        self.attempts_per_block = attempts_per_block
        self.base_block_delay = base_block_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        # Struttura: key -> {"failures": int, "locked_until": float, "last_attempt": float}
        self._attempts: Dict[str, Dict[str, float]] = {}

    def get_remaining_wait(self, key: str) -> float:
        """Restituisce i secondi rimanenti di blocco per la chiave specificata (0.0 se non bloccato)."""
        record = self._attempts.get(key)
        if not record:
            return 0.0
        now = time.time()
        remaining = record.get("locked_until", 0.0) - now
        return max(0.0, remaining)

    def is_rate_limited(self, key: str) -> tuple[bool, float]:
        """Restituisce (is_limited, remaining_wait_seconds)."""
        rem = self.get_remaining_wait(key)
        return (rem > 0.0, rem)

    def record_failure(self, key: str) -> float:
        """
        Registra un tentativo fallito.
        Se il conteggio fallimenti raggiunge un multiplo di attempts_per_block (es. 3, 6, 9...),
        applica il blocco temporaneo con tempo raddoppiato (30s, 60s, 120s...) e restituisce il ritardo.
        Se non ha ancora esaurito i tentativi del blocco, restituisce 0.0.
        """
        now = time.time()
        record = self._attempts.setdefault(key, {"failures": 0, "locked_until": 0.0, "last_attempt": now})
        record["failures"] += 1
        record["last_attempt"] = now
        failures = int(record["failures"])

        if failures % self.attempts_per_block == 0:
            block_index = failures // self.attempts_per_block  # 1 per 3 tentativi, 2 per 6, 3 per 9...
            delay = min(self.base_block_delay * (self.backoff_factor ** (block_index - 1)), self.max_delay)
            record["locked_until"] = now + delay
            return delay
        else:
            return 0.0

    def get_remaining_attempts_in_block(self, key: str) -> int:
        """Restituisce il numero di tentativi rimasti nel blocco corrente prima dello scatto del lockout."""
        record = self._attempts.get(key)
        if not record:
            return self.attempts_per_block
        failures = int(record.get("failures", 0))
        remainder = failures % self.attempts_per_block
        if remainder == 0:
            if self.is_rate_limited(key)[0]:
                return 0
            return self.attempts_per_block
        return self.attempts_per_block - remainder

    def record_success(self, key: str) -> None:
        """Azzera il contatore dei fallimenti per la chiave specificata."""
        if key in self._attempts:
            del self._attempts[key]

    def get_failure_count(self, key: str) -> int:
        """Restituisce il numero attuale di tentativi consecutivi falliti."""
        record = self._attempts.get(key)
        return int(record["failures"]) if record else 0

    def reset(self, key: Optional[str] = None) -> None:
        """Azzera la cronologia dei tentativi (per una singola chiave o per tutte)."""
        if key is not None:
            self._attempts.pop(key, None)
        else:
            self._attempts.clear()


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
        self.rate_limiter = LoginRateLimiter()

    def initialize_if_needed(self, default_password: str = "1234", auto_unlock: bool = False):
        """
        Inizializza i metadati del caveau se non esistono.
        Per sicurezza predefinita, il caveau rimane BLOCCATO finché l'utente non inserisce
        esplicitamente la password master corretta.
        """
        self.meta_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.meta_file.exists():
            meta = hash_password(default_password)
            self.meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            if auto_unlock:
                self.unlock(default_password)
        elif auto_unlock:
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
            self.initialize_if_needed(default_password=password, auto_unlock=False)

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
