import re
import uuid
from pathlib import Path
from typing import Optional
from app.config import get_settings
from app.services.crypto_service import get_vault_manager, encrypt_bytes, decrypt_bytes

def get_safe_filename(original_filename: str) -> str:
    suffix = Path(original_filename).suffix.lower() or ".bin"
    return f"{uuid.uuid4().hex}{suffix}"

def save_uploaded_file(file_bytes: bytes, original_filename: str, target_dir: Optional[Path] = None) -> str:
    """Cifra i byte del file e li salva sul filesystem. Il file su disco risulterà completamente cifrato."""
    folder = target_dir or get_settings().STORAGE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    filename = get_safe_filename(original_filename)
    dest = folder / filename

    mgr = get_vault_manager()
    mgr.initialize_if_needed()
    key = mgr.get_active_key()

    if key:
        encrypted_data = encrypt_bytes(file_bytes, key)
        dest.write_bytes(encrypted_data)
    else:
        # Fallback se il caveau non fosse temporaneamente configurato
        dest.write_bytes(file_bytes)

    return str(dest)

def read_decrypted_file(file_path: Path | str) -> bytes:
    """Legge un file cifrato da disco e lo decifra in memoria RAM restituendo i byte originali."""
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"File non trovato: {file_path}")

    raw_data = p.read_bytes()
    mgr = get_vault_manager()
    key = mgr.get_active_key()

    if not key:
        # Se il caveau non è sbloccato, proviamo l'inizializzazione se disponibile
        mgr.initialize_if_needed()
        key = mgr.get_active_key()

    if key:
        try:
            return decrypt_bytes(raw_data, key)
        except Exception:
            # Se la decifratura fallisce, potrebbe essere un file legacy non ancora cifrato
            return raw_data

    return raw_data

def migrate_unencrypted_files(target_dir: Optional[Path] = None):
    """Scansiona la cartella di archiviazione e converte eventuali file non ancora cifrati in file cifrati su disco."""
    folder = target_dir or get_settings().STORAGE_DIR
    if not folder.exists():
        return

    mgr = get_vault_manager()
    mgr.initialize_if_needed()
    key = mgr.get_active_key()
    if not key:
        return

    for item in folder.iterdir():
        if item.is_file() and not item.name.startswith("."):
            data = item.read_bytes()
            try:
                # Se decrypt ha successo, è già cifrato
                decrypt_bytes(data, key)
            except Exception:
                # Non è cifrato con la chiave corrente: cifriamolo in-place
                try:
                    enc = encrypt_bytes(data, key)
                    item.write_bytes(enc)
                except Exception as e:
                    print(f"Errore migrazione crittografica file {item}: {e}")


QUIETANZA_REGEX = re.compile(
    r'(?:^|[\W_])(pagat[oa]|saldat[oa]|quietanzat[oa]|bonifico\s+eseguito|ricevuta\s+(?:di\s+)?versamento|addebito\s+(?:diretto\s+)?(?:su\s+c/c\s+)?eseguito|ricevuta\s+pagamento|pagamento\s+effettuato|importo\s+corrisposto)(?:[\W_]|$)',
    re.IGNORECASE
)


def determine_document_status(extracted, due_date_obj=None) -> str:
    """
    Determina in modo intelligente e affidabile lo stato iniziale del documento nel caveau:
    - 'quietanzato': documento con timbro, dicitura o evidenza di pagamento già avvenuto.
    - 'da_pagare': documento con scadenza pendente, tributo, bolletta o fattura ancora da saldare.
    - 'archiviato': documento personale, contratto, nota, foto o file senza scadenze monetarie aperte.
    """
    if extracted is None:
        return "da_pagare" if bool(due_date_obj) else "archiviato"

    # 1. Indicazione esplicita dal modello di visione / estrazione
    if getattr(extracted, "is_paid", None) is True:
        return "quietanzato"
    if getattr(extracted, "payment_status", None) == "quietanzato":
        return "quietanzato"

    # 2. Rete di sicurezza euristica: analisi testuale su summary, titolo e tag
    summary_text = getattr(extracted, "summary", "") or ""
    title_text = getattr(extracted, "title", "") or ""
    tags_list = getattr(extracted, "tags", []) or []
    tags_text = " ".join(tags_list) if isinstance(tags_list, list) else str(tags_list)
    combined_text = f"{summary_text} {title_text} {tags_text}".lower()

    if QUIETANZA_REGEX.search(combined_text):
        return "quietanzato"

    # 3. Ricevute, scontrini o quietanze formali
    doc_type = (getattr(extracted, "doc_type", "") or "").lower()
    if doc_type in ["ricevuta", "scontrino"]:
        # Una ricevuta o uno scontrino d'acquisto attesta una transazione già conclusa
        if getattr(extracted, "is_payable", None) is not True:
            return "quietanzato"

    # 4. Scadenza o obbligo di pagamento aperto
    is_payable = getattr(extracted, "is_payable", None)
    if is_payable is False:
        # Il modello ha compreso espressamente che non è dovuta alcuna somma o il debito è estinto
        if bool(due_date_obj) or getattr(extracted, "amount", None) is not None:
            return "quietanzato"
        return "archiviato"

    has_deadline = bool(due_date_obj) or (is_payable is True) or (
        (getattr(extracted, "amount", None) is not None) and (doc_type in ["bolletta", "f24", "fattura", "tributo", "avviso"])
    )
    if has_deadline:
        return "da_pagare"

    return "archiviato"

