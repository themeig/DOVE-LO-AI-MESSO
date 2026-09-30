"""
Modulo Normalizzatore & Pre-Filtro Deterministico ad Alta Precisione (< 1ms, zero token).
Esegue l'estrazione e la validazione algoritmica certificata di codici rigidi:
- Codice Fiscale italiano (D.M. 23/12/1976 con validazione CIN ed omocodie)
- Partita IVA italiana (11 cifre con checksum di Luhn / Agenzia delle Entrate)
- IBAN europeo (ISO 13616 con verifica MOD-97)
- Targhe automobilistiche italiane (1994-presente e provinciali)
- Numeri fattura standard (es. FT-2024/01, Fatt. 98/BIS)
- Date puntuali (ISO, slash, punto, trattino e formato testuale italiano)
- Importi in Euro (€, euro, eur)
"""
import re
from dataclasses import dataclass, field
from datetime import date
from typing import List, Dict, Optional, Tuple

# Tabella caratteri dispari (posizioni 1, 3, 5, ..., 15 - 1-indexed) per Codice Fiscale
_CF_ODD_TABLE: Dict[str, int] = {
    "0": 1, "1": 0, "2": 5, "3": 7, "4": 9, "5": 13, "6": 15, "7": 17, "8": 19, "9": 21,
    "A": 1, "B": 0, "C": 5, "D": 7, "E": 9, "F": 13, "G": 15, "H": 17, "I": 19, "J": 21,
    "K": 2, "L": 4, "M": 18, "N": 20, "O": 11, "P": 3, "Q": 6, "R": 8, "S": 12, "T": 14,
    "U": 16, "V": 10, "W": 22, "X": 25, "Y": 24, "Z": 23
}

# Tabella caratteri pari (posizioni 2, 4, 6, ..., 14 - 1-indexed) per Codice Fiscale
_CF_EVEN_TABLE: Dict[str, int] = {
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    "A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "F": 5, "G": 6, "H": 7, "I": 8, "J": 9,
    "K": 10, "L": 11, "M": 12, "N": 13, "O": 14, "P": 15, "Q": 16, "R": 17, "S": 18, "T": 19,
    "U": 20, "V": 21, "W": 22, "X": 23, "Y": 24, "Z": 25
}

# Mappatura mesi in italiano
_ITALIAN_MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
    "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11, "dic": 12
}


@dataclass
class DeterministicEntities:
    """Contenitore strutturato per le entità deterministiche estratte dalla query."""
    codici_fiscali: List[str] = field(default_factory=list)
    partite_iva: List[str] = field(default_factory=list)
    iban: List[str] = field(default_factory=list)
    targhe: List[str] = field(default_factory=list)
    numeri_fattura: List[str] = field(default_factory=list)
    date_puntuali: List[date] = field(default_factory=list)
    importi: List[float] = field(default_factory=list)
    cleaned_query: str = ""
    raw_query: str = ""
    has_exact_identifiers: bool = False

    def to_dict(self) -> Dict:
        return {
            "codici_fiscali": self.codici_fiscali,
            "partite_iva": self.partite_iva,
            "iban": self.iban,
            "targhe": self.targhe,
            "numeri_fattura": self.numeri_fattura,
            "date_puntuali": [d.isoformat() for d in self.date_puntuali],
            "importi": self.importi,
            "cleaned_query": self.cleaned_query,
            "has_exact_identifiers": self.has_exact_identifiers
        }


def normalize_query(query: str) -> str:
    """Normalizzazione leggera e rapida della stringa query."""
    if not query:
        return ""
    # Sostituisce virgolette e apostrofi tipografici con standard
    text = query.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    # Comprime spazi bianchi multipli
    text = re.sub(r"\s+", " ", text).strip()
    return text


def validate_codice_fiscale(cf: str) -> bool:
    """
    Valida un Codice Fiscale italiano con la formula ufficiale del D.M. 23/12/1976.
    Supporta codici regolari e con sostituzioni di omocodia (L, M, N, P, Q, R, S, T, U, V).
    """
    cf_clean = cf.upper().replace(" ", "").strip()
    if len(cf_clean) != 16:
        return False

    pattern = r"^[A-Z]{6}[0-9LMNPQRSTUV]{2}[ABCDEHLMPRST][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]$"
    if not re.match(pattern, cf_clean):
        return False

    total = 0
    for i in range(15):
        char = cf_clean[i]
        if i % 2 == 0:  # Posizione dispari (1st, 3rd, 5th, ..., 15th)
            val = _CF_ODD_TABLE.get(char)
        else:           # Posizione pari (2nd, 4th, 6th, ..., 14th)
            val = _CF_EVEN_TABLE.get(char)

        if val is None:
            return False
        total += val

    expected_cin = chr(ord("A") + (total % 26))
    return cf_clean[15] == expected_cin


def validate_partita_iva(piva: str) -> bool:
    """
    Valida una Partita IVA italiana a 11 cifre tramite l'algoritmo ufficiale di controllo (Luhn modificato).
    """
    piva_clean = piva.strip()
    if len(piva_clean) != 11 or not piva_clean.isdigit():
        return False

    # Somma cifre in posizione dispari (1, 3, 5, 7, 9 - 0-indexed: 0, 2, 4, 6, 8)
    s1 = sum(int(piva_clean[i]) for i in range(0, 9, 2))

    # Somma cifre in posizione pari (2, 4, 6, 8, 10 - 0-indexed: 1, 3, 5, 7, 9)
    # Moltiplicate per 2; se il prodotto >= 10, somma le cifre (es. d*2 - 9)
    s2 = 0
    for i in range(1, 10, 2):
        d = int(piva_clean[i]) * 2
        s2 += d if d < 10 else (d - 9)

    total = s1 + s2
    check_digit = (10 - (total % 10)) % 10
    return int(piva_clean[10]) == check_digit


def validate_iban(iban: str) -> bool:
    """
    Valida un codice IBAN europeo secondo lo standard ISO 13616 e algoritmo ISO 7064 MOD-97.
    """
    iban_clean = iban.upper().replace(" ", "").strip()
    if len(iban_clean) < 15 or len(iban_clean) > 34:
        return False
    if not iban_clean[:2].isalpha() or not iban_clean[2:4].isdigit():
        return False

    # Sposta i primi 4 caratteri alla fine
    rearranged = iban_clean[4:] + iban_clean[:4]

    # Converte lettere in cifre (A=10, ..., Z=35)
    digits = []
    for ch in rearranged:
        if ch.isdigit():
            digits.append(ch)
        elif ch.isalpha():
            digits.append(str(ord(ch) - 55))
        else:
            return False

    num_str = "".join(digits)
    try:
        return (int(num_str) % 97) == 1
    except ValueError:
        return False


def validate_targa_italiana(targa: str) -> bool:
    """
    Valida una targa automobilistica italiana.
    Formato moderno (dal 1994): 2 lettere + 3 cifre + 2 lettere (es. 'AB123CD', esclusi caratteri I, O, Q, U).
    Formato storico provinciale (es. 'MI123456', 'RM987654').
    """
    t_clean = targa.upper().replace(" ", "").replace("-", "").strip()
    # Formato standard nazionale
    if re.match(r"^[A-HJ-NPR-TV-Z]{2}[0-9]{3}[A-HJ-NPR-TV-Z]{2}$", t_clean):
        return True
    # Formato storico provinciale (2 lettere provincia + 5 o 6 cifre)
    if re.match(r"^[A-Z]{2}[0-9]{5,6}$", t_clean):
        return True
    return False


def extract_deterministic_entities(query: str) -> DeterministicEntities:
    """
    Pre-filtro istantaneo (< 1ms, zero token).
    Analizza la query utente, estrae e valida tutte le entità rigide deterministiche,
    restituendo l'oggetto DeterministicEntities e la query depurata per eventuale ricerca semantica residua.
    """
    norm = normalize_query(query)
    entities = DeterministicEntities(raw_query=query)

    query_remainder = norm

    # 1. Rilevamento IBAN europeo (spaziato o continuo)
    # Formato spaziato (es. 'IT60 X054 2811 1010 ...')
    for m in re.finditer(r"\b([A-Z]{2}[0-9]{2}(?:\s+[A-Z0-9]{2,6}){3,7})\b", query_remainder, flags=re.I):
        val = m.group(1).replace(" ", "").upper()
        if validate_iban(val):
            if val not in entities.iban:
                entities.iban.append(val)
            query_remainder = query_remainder.replace(m.group(0), " ")

    # Formato compatto continuo (es. 'IT60X0542811101000000123456')
    for m in re.finditer(r"\b([A-Z]{2}[0-9]{2}[A-Z0-9]{11,30})\b", query_remainder, flags=re.I):
        val = m.group(1).upper()
        if validate_iban(val):
            if val not in entities.iban:
                entities.iban.append(val)
            query_remainder = query_remainder.replace(m.group(0), " ")

    # 2. Rilevamento Codice Fiscale italiano
    cf_candidates = re.findall(
        r"\b([A-Z]{6}[0-9LMNPQRSTUV]{2}[ABCDEHLMPRST][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z])\b",
        query_remainder,
        flags=re.IGNORECASE
    )
    for candidate in cf_candidates:
        cand_upper = candidate.upper()
        if validate_codice_fiscale(cand_upper):
            if cand_upper not in entities.codici_fiscali:
                entities.codici_fiscali.append(cand_upper)
            query_remainder = re.sub(r"\b" + re.escape(candidate) + r"\b", "", query_remainder, flags=re.I)

    # 3. Rilevamento Partita IVA (11 cifre isolate o precedute da piva / p.iva)
    piva_candidates = re.findall(r"\b([0-9]{11})\b", query_remainder)
    for candidate in piva_candidates:
        if validate_partita_iva(candidate):
            if candidate not in entities.partite_iva:
                entities.partite_iva.append(candidate)
            query_remainder = re.sub(r"\b" + candidate + r"\b", "", query_remainder)

    # 4. Rilevamento Targhe automobilistiche
    plate_candidates = re.findall(r"\b([A-HJ-NPR-TV-Z]{2}[0-9]{3}[A-HJ-NPR-TV-Z]{2})\b", query_remainder, flags=re.I)
    for candidate in plate_candidates:
        cand_upper = candidate.upper()
        if validate_targa_italiana(cand_upper):
            if cand_upper not in entities.targhe:
                entities.targhe.append(cand_upper)
            query_remainder = re.sub(r"\b" + re.escape(candidate) + r"\b", "", query_remainder, flags=re.I)

    # 5. Rilevamento Date puntuali
    # Formato numerico DD/MM/YYYY o DD-MM-YYYY
    date_matches = re.finditer(r"\b([0-3]?[0-9])[/-]([0-1]?[0-9])[/-](20[0-9]{2}|19[0-9]{2})\b", query_remainder)
    for m in date_matches:
        try:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            entities.date_puntuali.append(date(y, mo, d))
            query_remainder = query_remainder.replace(m.group(0), " ")
        except (ValueError, OverflowError):
            pass

    # Formato numerico YYYY-MM-DD
    iso_matches = re.finditer(r"\b(20[0-9]{2}|19[0-9]{2})[-/]([0-1]?[0-9])[-/]([0-3]?[0-9])\b", query_remainder)
    for m in iso_matches:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            entities.date_puntuali.append(date(y, mo, d))
            query_remainder = query_remainder.replace(m.group(0), " ")
        except (ValueError, OverflowError):
            pass

    # Formato testuale italiano (es. "15 marzo 2026")
    text_date_matches = re.finditer(
        r"\b([0-3]?[0-9])\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+(20[0-9]{2}|19[0-9]{2})\b",
        query_remainder,
        flags=re.IGNORECASE
    )
    for m in text_date_matches:
        try:
            d = int(m.group(1))
            m_name = m.group(2).lower()
            mo = _ITALIAN_MONTHS.get(m_name, 1)
            y = int(m.group(3))
            entities.date_puntuali.append(date(y, mo, d))
            query_remainder = query_remainder.replace(m.group(0), " ")
        except (ValueError, OverflowError):
            pass

    # 6. Rilevamento Importi in Euro (€ 1.250,50 o 64,20 euro o 500€)
    amount_matches = re.finditer(
        r"(?:€\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{1,2})?|[0-9]+(?:[.,][0-9]{1,2})?)|([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{1,2})?|[0-9]+(?:[.,][0-9]{1,2})?)\s*(?:€|euro\b|eur\b))",
        query_remainder,
        flags=re.IGNORECASE
    )
    for m in amount_matches:
        raw_val = m.group(1) or m.group(2)
        if raw_val:
            try:
                cleaned_val = raw_val.replace(".", "").replace(",", ".")
                parsed_amt = float(cleaned_val)
                entities.importi.append(parsed_amt)
                query_remainder = query_remainder.replace(m.group(0), " ")
            except ValueError:
                pass

    # 7. Rilevamento Numeri Fattura
    # Pattern con prefisso esplicito (es. "fattura FT-2024/01", "fatt. 98/BIS", "doc. n. 123/2026")
    inv_prefixed = re.findall(
        r"(?:fattura|fatt\.?|ft\.?|inv\.?|doc\.?|n\.|num\.|nr\.)\s*(?:n\.?|num\.?|nr\.?)?\s*([A-Za-z0-9]+(?:[-_/][A-Za-z0-9]+)+|[0-9]{1,8})\b",
        query_remainder,
        flags=re.IGNORECASE
    )
    for candidate in inv_prefixed:
        cand_clean = candidate.strip()
        if cand_clean and cand_clean not in entities.numeri_fattura:
            entities.numeri_fattura.append(cand_clean)
            query_remainder = re.sub(r"\b" + re.escape(candidate) + r"\b", "", query_remainder, flags=re.I)

    # Pattern per codici fattura strutturati standalone (es. "FT-2024/01", "98/BIS", "2024/001")
    inv_standalone = re.findall(
        r"\b([A-Za-z]{1,6}[-_/][0-9]{1,6}(?:[-_/][A-Za-z0-9]+)*|[0-9]{1,6}[-_/][A-Za-z0-9]+)\b",
        query_remainder
    )
    for candidate in inv_standalone:
        cand_clean = candidate.strip()
        if cand_clean and cand_clean not in entities.numeri_fattura:
            entities.numeri_fattura.append(cand_clean)
            query_remainder = re.sub(r"\b" + re.escape(candidate) + r"\b", "", query_remainder, flags=re.I)

    # Pulizia finale della query residua
    query_remainder = re.sub(r"\s+", " ", query_remainder).strip()
    entities.cleaned_query = query_remainder

    # Flag presenza identificativi rigidi
    entities.has_exact_identifiers = bool(
        entities.codici_fiscali
        or entities.partite_iva
        or entities.iban
        or entities.targhe
        or entities.numeri_fattura
    )

    return entities
