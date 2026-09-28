"""
Modulo di funzioni helper, calcolo scadenze e parsing per l'agente del Caveau.
"""
import json
import re
from datetime import datetime, date, timezone
from typing import Optional, Dict, Any, List

from app.services.search_service import ITALIAN_STOPWORDS

WEEKDAYS_IT = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
MONTHS_IT = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"
]


def get_current_date_info() -> Dict[str, Any]:
    """Restituisce informazioni dettagliate sulla data e l'ora attuale in formato ISO e in lingua italiana."""
    now = datetime.now()
    weekday = WEEKDAYS_IT[now.weekday()]
    month = MONTHS_IT[now.month - 1]
    formatted = f"{weekday} {now.day} {month} {now.year}"
    return {
        "date": now.date().isoformat(),
        "formatted_italian": formatted,
        "weekday": weekday,
        "day": now.day,
        "month": month,
        "year": now.year,
        "time": now.strftime("%H:%M:%S"),
        "current_time": now.strftime("%H:%M")
    }


def categorize_deadline(due_date: Optional[date], today: Optional[date] = None) -> Dict[str, Any]:
    """Calcola i giorni rimanenti e la categoria di urgenza per una scadenza."""
    if today is None:
        today = date.today()
    if not due_date:
        return {
            "days_remaining": None,
            "urgency": "unknown",
            "urgency_label": "DATA NON SPECIFICATA"
        }
    days = (due_date - today).days
    if days < 0:
        abs_d = abs(days)
        label = f"SCADUTA DA {abs_d} {'GIORNO' if abs_d == 1 else 'GIORNI'}"
        return {"days_remaining": days, "urgency": "overdue", "urgency_label": label}
    elif days == 0:
        return {"days_remaining": 0, "urgency": "today", "urgency_label": "SCADE OGGI!"}
    elif days <= 3:
        label = f"SCADE TRA {days} {'GIORNO' if days == 1 else 'GIORNI'}"
        return {"days_remaining": days, "urgency": "urgent", "urgency_label": label}
    elif days <= 7:
        return {"days_remaining": days, "urgency": "soon", "urgency_label": f"IN SCADENZA TRA {days} GIORNI"}
    else:
        return {"days_remaining": days, "urgency": "future", "urgency_label": f"FUTURA (TRA {days} GIORNI)"}


def is_tool_payload(obj: Any) -> bool:
    """Verifica se un dizionario JSON rappresenta una risposta tecnica di un tool o un payload interno."""
    if not isinstance(obj, dict):
        return False
    keys_lower = [str(k).lower() for k in obj.keys()]
    if any(k.endswith("response") or k.endswith("_response") for k in keys_lower):
        return True
    tool_keywords = {
        "confirmation", "target_type", "targettype", "target_id", "targetid",
        "target_ids", "targetids", "delete_vault_record", "deletevaultrecord",
        "found_documents", "founddocuments", "found_physical_items", "foundphysicalitems",
        "physical_items", "physicalitems", "upcoming_documents", "deadlines",
        "search_vault", "searchvault", "list_vault_contents", "listvaultcontents",
        "pending_confirmation", "pendingconfirmation", "tool_call_id", "tool_name",
        "function_call", "functioncall", "card_document", "show_document_card"
    }
    if any(k in tool_keywords for k in keys_lower):
        return True
    if obj.get("status") in ["pending_confirmation", "pendingconfirmation", "not_found", "success"]:
        return True
    obj_str = str(obj).lower()
    if any(k in obj_str for k in ["delete_confirmation", "deleteconfirmation", "show_document_card", "delete_vault_record"]):
        return True
    return False


def strip_tool_tags(text: str) -> str:
    """Rimuove qualsiasi tag <tool_call>...</tool_call>, blocchi di thinking <thought>...</thought>,
    residui XML di chiamata tool e oggetti JSON di risposta tool (es. {"deletevaultrecordresponse": ...})."""
    if not text:
        return ""
    cleaned = text

    # 1. Rimuovi tag XML standard e blocchi di pensiero
    cleaned = re.sub(r"<thought>.*?</thought>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<tool_call>.*?</tool_call>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<tool_response>.*?</tool_response>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<\w+_response>.*?</\w+_response>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<function=.*?</function>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<parameter=.*?</parameter>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"</?(?:thought|think|tool_call|tool_response|function|parameter|arg_key|arg_value|\w+_response)[^>]*>", "", cleaned, flags=re.IGNORECASE)

    # 2. Rimuovi blocchi di codice markdown che racchiudono JSON di tool
    def _clean_code_blocks(match):
        code_body = match.group(1).strip()
        if code_body.startswith("{") and code_body.endswith("}"):
            try:
                parsed = json.loads(code_body)
                if is_tool_payload(parsed):
                    return ""
            except Exception:
                pass
        return match.group(0)

    cleaned = re.sub(r"```(?:json)?\s*(\{.*?\})\s*```", _clean_code_blocks, cleaned, flags=re.DOTALL | re.IGNORECASE)

    # 3. Rimuovi oggetti JSON in testa (leading JSON objects, ciclicamente finché presenti)
    decoder = json.JSONDecoder()
    while True:
        s = cleaned.lstrip()
        if not s.startswith("{"):
            break
        try:
            parsed, end_idx = decoder.raw_decode(s)
            rem = s[end_idx:].strip()
            if is_tool_payload(parsed) or not rem:
                cleaned = rem
                continue
            else:
                break
        except Exception:
            break

    # 4. Rimuovi oggetti JSON in coda (trailing JSON objects)
    s = cleaned.rstrip()
    if s.endswith("}"):
        pos = 0
        while True:
            idx = s.find("{", pos)
            if idx == -1:
                break
            candidate = s[idx:]
            try:
                parsed = json.loads(candidate)
                if is_tool_payload(parsed):
                    cleaned = s[:idx].rstrip()
                    break
            except Exception:
                pass
            pos = idx + 1

    # 5. Pulizia regex di sicurezza per pattern noti anche se malformati o parziali
    cleaned = re.sub(r'\{"\w*response"\s*:\s*\{.*?\}\s*\}', "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'\{"(?:confirmation|target_type|targettype|target_id|targetid|deletevaultrecord|delete_vault_record)"\s*:.*?\}\s*\}?', "", cleaned, flags=re.DOTALL | re.IGNORECASE)

    return cleaned.strip()


def filter_relevant_documents(docs: Optional[List[dict]], assistant_text: str, user_text: str) -> Optional[List[dict]]:
    """Filtra i widget dei documenti inviati alla UI in modo che corrispondano solo a quelli pertinenti o citati."""
    if not docs:
        return None

    asst_lower = assistant_text.lower() if assistant_text else ""
    user_lower = user_text.lower() if user_text else ""

    # 0. Se la richiesta dell'utente è una domanda meta, informativa, di aiuto o di presentazione/saluto, non allegare documenti
    is_meta_or_help = any(
        p in user_lower for p in [
            "cosa puoi fare", "cosa sai fare", "chi sei", "come funzioni", "come ti chiami",
            "cosa posso chiederti", "a cosa servi", "cosa fai", "spiegami cosa puoi fare",
            "aiuto", "help", "funzionalità", "istruzioni", "presentati"
        ]
    ) or user_lower.strip(" ?.!").lower() in [
        "ciao", "buongiorno", "buonasera", "salve", "ehi", "hey", "help", "aiuto", "info"
    ]
    if is_meta_or_help:
        return None

    # 1. Verifica quali documenti sono esplicitamente citati nel testo della risposta dell'assistente
    title_matches = []
    issuer_matches = []
    for d in docs:
        title = (d.get("title") or "").strip().lower()
        issuer = (d.get("issuer") or "").strip().lower()
        title_words = [
            w for w in re.split(r"[^\w]+", title)
            if len(w) > 3 and w not in ITALIAN_STOPWORDS and not re.match(r"^(?:19|20)\d{2}$", w)
        ]
        title_match = (title and re.search(rf"\b{re.escape(title)}\b", asst_lower)) or (
            title_words and sum(1 for w in title_words if re.search(rf"\b{re.escape(w)}\b", asst_lower)) >= max(1, len(title_words) * 0.5)
        )
        acronyms = [
            w for w in re.split(r"[^\w]+", title)
            if w not in ITALIAN_STOPWORDS
            and not re.match(r"^(?:19|20)\d{2}$", w)
            and (re.search(r"\d+", w) or len(w) in (2, 3))
        ]
        if not title_match and acronyms:
            for a in acronyms:
                if re.search(rf"\b{re.escape(a)}\b", asst_lower):
                    if re.search(r"\d+", a):
                        title_match = True
                        break
                    elif title_words and any(re.search(rf"\b{re.escape(w)}\b", asst_lower) for w in title_words):
                        title_match = True
                        break
                    elif not title_words:
                        title_match = True
                        break

        issuer_match = bool(issuer and len(issuer) > 3 and (re.search(rf"\b{re.escape(issuer)}\b", asst_lower)))
        if title_match:
            title_matches.append(d)
        elif issuer_match:
            issuer_matches.append(d)

    if title_matches:
        return title_matches
    if issuer_matches:
        return issuer_matches

    # 2. Posizioni fisiche
    is_store_phrase = any(k in user_lower for k in ["messo", "riposto", "salvato", "lasciato", "conservato", "posizionato"])
    is_where_phrase = any(k in user_lower for k in ["dov'è", "dov'e", "dove è", "dove si trova", "dove sono", "dove sta"])
    is_item_answer = "📍" in asst_lower or "si trova in" in asst_lower or "si trovano in" in asst_lower or "è in " in asst_lower
    has_photo_doc = any(
        d.get("physical_item_id")
        or "📸" in asst_lower
        or "foto" in asst_lower
        or "foto" in (d.get("title") or "").lower()
        or (d.get("file_type") or "").lower() in ["image", "jpg", "jpeg", "png", "webp"]
        for d in docs
    )
    if is_where_phrase and is_item_answer and has_photo_doc:
        return docs[:2]

    if is_store_phrase or (is_where_phrase and is_item_answer) or (is_item_answer and not any(k in user_lower for k in ["document", "bollett", "fattur", "f24", "730", "file"])):
        return None

    # 3. Elenco generico
    is_list_request = any(
        re.search(rf"\b{w}\b", user_lower)
        for w in ["elenco", "elencami", "lista", "tutti", "tutte", "quali", "cosa hai", "cosa c'è", "archivio"]
    )
    if is_list_request:
        return None

    # 4. Richiesta singola
    is_singular_request = any(
        re.search(rf"\b{w}\b", user_lower)
        for w in ["il", "lo", "la", "l'", "un", "uno", "una", "un'"]
    ) and not any(
        re.search(rf"\b{w}\b", user_lower)
        for w in ["i", "gli", "le", "tutti", "tutte", "entrambi", "entrambe", "elenco", "elencami", "lista", "quali"]
    )
    if is_singular_request and len(docs) > 0:
        top_title = (docs[0].get("title") or "").lower()
        top_words = [
            w for w in re.split(r"[^\w]+", top_title)
            if len(w) > 3 and w not in ITALIAN_STOPWORDS and not re.match(r"^(?:19|20)\d{2}$", w)
        ]
        user_asks_doc = any(k in user_lower for k in ["document", "file", "bollett", "fattur", "contratt", "certificat", "ricevut", "cedolin", "patente", "carta", "f24", "730", "estratto"])
        user_mentions_title = any(re.search(rf"\b{re.escape(w)}\b", user_lower) for w in top_words)
        if user_mentions_title or user_asks_doc:
            return [docs[0]]

    # 5. Proattività per documenti richiesti
    user_asks_doc = any(k in user_lower for k in [
        "document", "file", "bollett", "fattur", "contratt", "certificat", "ricevut", "cedolin",
        "patente", "carta", "f24", "730", "identit", "identificazion", "mostrami", "visualizza",
        "apri", "scarica", "dammi", "prendi", "vedi", "garanzia", "scontrino", "multa"
    ])
    if user_asks_doc and len(docs) > 0:
        matched_relevant = []
        for d in docs:
            d_tit = (d.get("title") or "").lower()
            d_iss = (d.get("issuer") or "").lower()
            d_type = (d.get("doc_type") or "").lower()
            d_words = [
                w for w in re.split(r"[^\w]+", f"{d_tit} {d_iss} {d_type}")
                if len(w) > 2 and w not in ITALIAN_STOPWORDS and not re.match(r"^(?:19|20)\d{2}$", w)
            ]
            if any(re.search(rf"\b{re.escape(w)}\b", user_lower) or re.search(rf"\b{re.escape(w)}\b", asst_lower) for w in d_words):
                matched_relevant.append(d)
        if matched_relevant:
            if is_singular_request:
                return [matched_relevant[0]]
            return matched_relevant[:4]

    return None


def extract_rename_title(text: str) -> Optional[str]:
    """Estrae il nuovo titolo da espressioni naturali dell'utente per rinominare documenti o foto."""
    if not text:
        return None
    clean = text.strip()
    clean = re.sub(r"^(?:sì|si|ok|perfetto|d'accordo|va bene)[,\s]+", "", clean, flags=re.IGNORECASE).strip()

    patterns = [
        r"^(?:puoi\s+)?(?:per\s+favore\s+)?(?:chiamalo|chiamala|chiamali|chiamale|chiamami)\s+(?:in\s+|come\s+)?[\"']?(.+?)[\"']?$",
        r"^(?:puoi\s+)?(?:per\s+favore\s+)?(?:rinominalo|rinominala|rinomina(?:\s+l'ultimo\s+(?:file|documento|foto|allegato)|\s+il\s+file|\s+la\s+foto|\s+l'ultima\s+foto)?)\s+(?:in\s+|come\s+)?[\"']?(.+?)[\"']?$",
        r"^(?:puoi\s+)?(?:per\s+favore\s+)?(?:salvalo\s+come|salvala\s+come|salvalo|salvala)\s+(?:in\s+|come\s+)?[\"']?(.+?)[\"']?$",
        r"^(?:dagli|dalle|dai)\s+(?:il\s+nome|come\s+nome)\s+(?:di\s+|in\s+)?[\"']?(.+?)[\"']?$",
        r"^(?:assegna(?:\s+il)?\s+nome)\s+[\"']?(.+?)[\"']?$",
        r"^(?:imposta\s+(?:il\s+)?nome(?:\s+in|\s+come)?)\s+[\"']?(.+?)[\"']?$",
    ]
    for p in patterns:
        m = re.search(p, clean, flags=re.IGNORECASE)
        if m:
            title = m.group(1).strip(" .?!\"'")
            title = re.sub(r"^(?:in|come)\s+", "", title, flags=re.IGNORECASE).strip(" '\"")
            if title and len(title) >= 2:
                return title
    return None


def extract_item_and_location(text: str, last_item_in_context: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    """Estrae con precisione il nome dell'oggetto e la posizione (per salvataggio, modifica, spostamento)."""
    t = text.strip()
    low = t.lower()

    def _clean_and_validate(it: Optional[str], lc: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        if not it or not lc:
            return None, None
        clean_it = it.strip(" .?!\"'[]:;,*`")
        clean_lc = lc.strip(" .?!\"'[]:;,*`")
        invalid_kws = ["dove lo ai messo", "in risposta a", "ti ricordi", "questo messaggio", "sto quotando", "messaggio precedente"]
        if any(k in clean_it.lower() or k in clean_lc.lower() for k in invalid_kws):
            return None, None
        if len(clean_it) < 2 or len(clean_it) > 100 or len(clean_lc) < 2 or len(clean_lc) > 150:
            return None, None
        return clean_it, clean_lc

    # Pronomi (es. "mettila in soggiorno", "spostalo in garage")
    m_pro = re.search(
        r"^(?:mettila|mettilo|mettili|mettile|spostala|spostalo|spostali|spostale|posizionalo|posizionala|sistemalo|sistemala)\s+(?:in|nel|nella|nello|nei|negli|nelle|sul|sulla|sullo|sui|sugli|sulle|a|all\'|allo|alla|dentro|sopra|sotto)\s+(.+)",
        low
    )
    if m_pro:
        loc = m_pro.group(1).strip(" .?!")
        return _clean_and_validate(last_item_in_context, loc)

    # 1. "modifica/cambia/aggiorna la posizione di X e mettila/mettilo in Y"
    m = re.search(
        r"\b(?:modifica|cambia|aggiorna)\b\s+(?:la\s+posizione\s+(?:di|del|della|dei|degli|delle|d\')\s*)?(.+?)\s+(?:e\s+)?(?:mettila|mettilo|mettili|mettile|spostala|spostalo|spostali|spostale|salvala|salvalo)?\s*(?:in|nel|nella|nello|nei|negli|nelle|sul|sulla|sullo|sui|sugli|sulle|a|all\'|allo|alla|dentro|sopra|sotto)\s+(.+)",
        low
    )
    if m:
        item = m.group(1).strip()
        loc = m.group(2).strip(" .?!")
        item = re.sub(r"^(?:la\s+posizione\s+(?:di|del|della|dei|degli|delle|d\')\s*)", "", item).strip()
        item = re.sub(r"^(?:il|lo|la|i|gli|le|l\'|un|uno|una|un\')\s*", "", item).strip()
        return _clean_and_validate(item, loc)

    # 2. "sposta/trasferisci/porta X in Y"
    m = re.search(
        r"\b(?:sposta|trasferisci|porta)\b\s+(?:il\s+|la\s+|le\s+|i\s+|gli\s+|l\')?(.+?)\s+\b(?:in|nel|nella|nello|nei|negli|nelle|sul|sulla|sullo|sui|sugli|sulle|a|all\'|allo|alla|dentro|sopra|sotto)\b\s+(.+)",
        low
    )
    if m:
        item = m.group(1).strip()
        loc = m.group(2).strip(" .?!")
        return _clean_and_validate(item, loc)

    # 3. "metti/posiziona/sistema X in Y"
    m = re.search(
        r"\b(?:metti|posiziona|sistema)\b\s+(?:il\s+|la\s+|le\s+|i\s+|gli\s+|l\')?(.+?)\s+\b(?:in|nel|nella|nello|nei|negli|nelle|sul|sulla|sullo|sui|sugli|sulle|a|all\'|allo|alla|dentro|sopra|sotto)\b\s+(.+)",
        low
    )
    if m:
        item = m.group(1).strip()
        loc = m.group(2).strip(" .?!")
        return _clean_and_validate(item, loc)

    # 4. "ho messo/riposto/salvato/lasciato/conservato/posizionato X in Y"
    m = re.search(
        r"\b(?:ho\s+)?(?:messo|riposto|salvato|lasciato|conservato|posizionato|sistemato)\b\s+(?:il\s+|la\s+|le\s+|i\s+|gli\s+|l\')?(.+?)\s+\b(?:nel|nella|nello|nei|negli|nelle|in|su|sul|sulla|sullo|sui|sugli|sulle|sotto|a|all\'|allo|alla|dentro|sopra)\b\s+(.+)",
        low
    )
    if m:
        item = m.group(1).strip()
        loc = m.group(2).strip(" .?!")
        return _clean_and_validate(item, loc)

    # 5. "ora X si trova in Y" o "X ora è in Y"
    m = re.search(
        r"\b(?:ora|adesso)\b\s+(?:il\s+|la\s+|le\s+|i\s+|gli\s+|l\')?(.+?)\s+(?:è|e\'|si trova|sta)\s+\b(?:in|nel|nella|nello|nei|negli|nelle|sul|sulla|sullo|sui|sugli|sulle|a|all\'|allo|alla|dentro|sopra|sotto)\b\s+(.+)",
        low
    )
    if m:
        item = m.group(1).strip()
        loc = m.group(2).strip(" .?!")
        return _clean_and_validate(item, loc)

    m = re.search(
        r"(?:il\s+|la\s+|le\s+|i\s+|gli\s+|l\')?(.+?)\s+\b(?:ora|adesso)\b\s+(?:è|e\'|si trova|sta)\s+\b(?:in|nel|nella|nello|nei|negli|nelle|sul|sulla|sullo|sui|sugli|sulle|a|all\'|allo|alla|dentro|sopra|sotto)\b\s+(.+)",
        low
    )
    if m:
        item = m.group(1).strip()
        loc = m.group(2).strip(" .?!")
        return _clean_and_validate(item, loc)

    return None, None


def extract_bulk_delete_target(text: str) -> tuple[bool, Optional[str]]:
    """
    Determina se la cancellazione multipla richiesta è un azzeramento totale del caveau
    oppure è mirata a un termine/categoria/gruppo specifico (es. '730 test', 'ricevute', 'bollette').
    Ritorna: (is_total_vault, target_keyword)
    """
    if not text:
        return True, None

    low = text.lower().strip()
    # 1. Rimuovi verbi di eliminazione e prefissi iniziali
    clean = re.sub(
        r"^(?:per\s+favore|puoi|ti\s+prego\s+di|vorrei|potresti)?\s*(?:eliminali\s+tutti|cancellali\s+tutti|rimuovili\s+tutti|eliminali|cancellali|rimuovili|eliminami|cancellami|rimuovimi|eliminarlo|cancellarlo|rimuoverlo|eliminarla|cancellarla|rimuoverla|elimina|cancella|rimuovi|svuota|butta)\s*(?:tutti\s+i|tutte\s+le|tutti\s+gli|tutti|tutte|tutto|l'intero|l'intera|ogni|qualsiasi)?\s*",
        "",
        low,
        flags=re.IGNORECASE
    ).strip(" ?.")

    # 2. Rimuovi suffissi descrittivi comuni
    clean = re.sub(
        r"\s*(?:dal\s+caveau|dall'archivio|dal\s+database|dalla\s+memoria|dal\s+sistema|presenti\s+nel\s+caveau|salvati\s+nel\s+caveau|nel\s+caveau|in\s+archivio|salvati|archiviati|memorizzati|presenti|che\s+hai|che\s+ci\s+sono|che\s+abbiamo|per\s+favore|grazie)$",
        "",
        clean,
        flags=re.IGNORECASE
    ).strip(" ?.")

    # 3. Rimuovi eventuali prefissi rimanenti di articoli / appartenenza
    clean = re.sub(r"^(?:i\s+miei|le\s+mie|i\s+tuoi|le\s+tue|i|gli|le|il|la|lo|l'|un|una|uno)\s+", "", clean, flags=re.IGNORECASE).strip(" ?.")

    # 4. Rimuovi nuovamente suffissi se rimasti
    clean = re.sub(
        r"\s*(?:dal\s+caveau|dall'archivio|dal\s+database|dalla\s+memoria|dal\s+sistema|presenti\s+nel\s+caveau|salvati\s+nel\s+caveau|nel\s+caveau|in\s+archivio|salvati|archiviati|memorizzati|presenti|che\s+hai|che\s+ci\s+sono|che\s+abbiamo|per\s+favore|grazie)$",
        "",
        clean,
        flags=re.IGNORECASE
    ).strip(" ?.")

    # 5. Prefisso generico "documenti di", "file di"
    clean_specific = re.sub(r"^(?:documenti|documento|file|allegati|oggetti|cose)\s*(?:di\s+|del\s+|della\s+|dei\s+|degli\s+|delle\s+|d\'|da\s+|per\s+)?", "", clean, flags=re.IGNORECASE).strip(" ?.")

    generic_terms = ["", "documenti", "documento", "file", "tutto", "tutti", "tutte", "caveau", "archivio", "dati", "elementi", "record", "allegati", "all", "bulk_documents", "cose", "oggetti"]
    if clean in generic_terms or clean_specific in generic_terms:
        return True, None

    return False, (clean_specific if clean_specific else clean)


def extract_link_photo_item(text: str) -> Optional[str]:
    """
    Estrae il nome dell'oggetto fisico a cui associare una foto/documento
    da espressioni come 'ti allego la foto per il piano', 'ecco la foto delle chiavi', 'associa la foto al passaporto'.
    """
    if not text:
        return None

    clean = text.strip()
    patterns = [
        r"(?:ti\s+allego|ecco|ti\s+lascio|ti\s+mando|ho\s+fatto|ho\s+mandato|ho\s+caricato)\s+(?:una|la|questa)?\s*(?:foto|immagine|allegato)\s+(?:per|del|della|delle|dei|degli|a|al|alla|alle|ai|agli|di)\s+[\"']?(.+?)[\"']?$",
        r"(?:collega|associa|lega|abbina)\s+(?:la|questa|l'ultima)?\s*(?:foto|immagine|documento|file|allegato)\s+(?:al|alla|alle|ai|agli|a|per|con)\s+[\"']?(.+?)[\"']?$",
        r"^(?:foto|immagine|allegato)\s+(?:per|del|della|delle|dei|degli|di)\s+[\"']?(.+?)[\"']?$",
        r"(?:questa|quest'ultima)\s+(?:foto|immagine)\s+(?:è|e'|serve)\s+(?:per|a)\s+[\"']?(.+?)[\"']?$"
    ]
    for p in patterns:
        m = re.search(p, clean, flags=re.IGNORECASE)
        if m:
            target = m.group(1).strip(" .?!\"'")
            target = re.sub(r"^(?:il|lo|la|i|gli|le|l'|un|uno|una|un')\s*", "", target, flags=re.IGNORECASE).strip()
            if target and len(target) >= 2:
                return target
    return None
