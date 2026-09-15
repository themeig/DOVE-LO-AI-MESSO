import re
import difflib
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple
from sqlalchemy.orm import Session

from app.models.database import Document, PhysicalItem

logger = logging.getLogger(__name__)

ITALIAN_STOPWORDS = {
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "un'", "l'", "d'",
    "del", "dello", "della", "dei", "degli", "delle", "al", "allo", "alla", "ai", "agli", "alle",
    "dal", "dallo", "dalla", "dai", "dagli", "dalle", "nel", "nello", "nella", "nei", "negli", "nelle",
    "sul", "sullo", "sulla", "sui", "sugli", "sulle", "per", "con", "tra", "fra", "in", "su", "da", "di", "a",
    "che", "chi", "cosa", "come", "dove", "quando", "trova", "trovami", "cerca", "dov'è", "dov'e",
    "dammi", "mostra", "mostrami", "visualizza", "fammi", "vedere", "voglio", "vorrei", "prendi", "apri",
    "ho", "hai", "ha", "abbiamo", "hanno", "e", "ed", "o", "od", "se", "si", "no", "non", "mio", "mia", "miei", "mie",
    "tuo", "tua", "tuoi", "tue", "suo", "sua", "suoi", "sue", "nostro", "nostra", "nostri", "nostre", "loro",
    "questo", "questa", "questi", "queste", "quello", "quella", "quelli", "quelle", "tutti", "tutte",
    "ora", "adesso", "allora", "invece", "poi", "bene", "anche", "pure", "esattamente"
}

GENERIC_ATTRIBUTE_TERMS = {
    "documento", "documenti", "file", "allegato", "allegati", "copia", "archivio",
    "modulo", "moduli", "modello", "modelli", "pdf",
    "scadenza", "scadenze", "rata", "rate", "importo", "costo", "quando"
}

CONCEPT_SYNONYMS: Dict[str, List[str]] = {
    "mg": ["mg4", "auto", "macchina", "veicolo"],
    "mg4": ["mg", "auto", "macchina", "veicolo"],
    "bolletta": ["bollette", "utenza", "utenze", "luce", "gas", "acqua", "energia", "fattura"],
    "bollette": ["bolletta", "utenza", "utenze", "luce", "gas", "acqua", "energia", "fattura"],
    "utenza": ["utenze", "bolletta", "bollette"],
    "utenze": ["utenza", "bolletta", "bollette"],
    "luce": ["energia", "elettrica", "corrente", "enel", "eni", "bolletta"],
    "gas": ["metano", "riscaldamento", "eni", "enel", "bolletta"],
    "acqua": ["idrico", "acquedotto", "bolletta", "mm"],
    "tassa": ["tasse", "f24", "tributo", "tributi", "irpef", "730", "fisco", "imposta", "imposte"],
    "tasse": ["tassa", "f24", "tributo", "tributi", "irpef", "730", "fisco", "imposta", "imposte"],
    "tributo": ["tributi", "tassa", "tasse", "f24", "imposta", "fisco"],
    "tributi": ["tributo", "tassa", "tasse", "f24", "imposta", "fisco"],
    "fisco": ["f24", "tributi", "irpef", "730", "tasse"],
    "f24": ["tasse", "tributi", "irpef", "fisco", "imposte", "acconto"],
    "730": ["dichiarazione", "precompilato", "redditi", "irpef"],
    "mutuo": ["mutui", "finanziamento", "prestito", "ipoteca"],
    "mutui": ["mutuo", "finanziamento", "prestito", "ipoteca"],
    "finanziamento": ["mutuo", "prestito", "rata", "rate", "banca"],
    "finanziamenti": ["mutuo", "prestito", "rata", "rate", "banca"],
    "auto": ["patente", "macchina", "veicolo", "bollo", "assicurazione", "polizza", "libretto", "mg", "mg4"],
    "macchina": ["auto", "veicolo", "patente", "bollo", "assicurazione", "polizza", "mg", "mg4"],
    "moto": ["patente", "veicolo", "bollo", "assicurazione", "polizza", "scooter"],
    "assicurazione": ["auto", "moto", "veicolo", "casa", "polizza", "scadenza"],
    "polizza": ["assicurazione", "auto", "moto", "scadenza"],
    "salute": ["visita", "cardiologo", "dottore", "medico", "ricetta", "referto", "ospedale"],
    "medico": ["visita", "dottore", "salute", "referto", "ospedale", "ricetta"],
    "referto": ["visita", "medico", "esame", "analisi", "ospedale", "salute"],
    "referti": ["referto", "visita", "medico", "esame", "analisi", "ospedale", "salute"],
    "chiavi": ["chiave", "porta", "scorta", "casa", "box", "garage", "cancello", "cassaforte"],
    "chiave": ["chiavi", "porta", "scorta", "casa", "box", "garage", "cancello", "cassaforte"],
    "passaporto": ["passaporti", "identità", "identificazione", "documenti"],
    "passaporti": ["passaporto", "identità", "identificazione", "documenti"],
    "patente": ["patenti", "guida", "auto", "veicolo", "identità", "identificazione"],
    "patenti": ["patente", "guida", "auto", "veicolo", "identità", "identificazione"],
    "identita": ["identità", "identificazione", "riconoscimento", "tessera", "patente", "passaporto", "carta", "anagrafici", "anagrafico", "anagrafica", "ricevuta", "personale", "codice"],
    "identità": ["identita", "identificazione", "riconoscimento", "tessera", "patente", "passaporto", "carta", "anagrafici", "anagrafico", "anagrafica", "ricevuta", "personale", "codice"],
    "identificazione": ["identità", "identita", "riconoscimento", "tessera", "patente", "passaporto", "carta", "anagrafici", "anagrafico", "anagrafica", "ricevuta", "personale"],
    "personale": ["identità", "identificazione", "anagrafici", "anagrafico", "anagrafica"],
    "personali": ["identità", "identificazione", "anagrafici", "anagrafico", "anagrafica"],
    "sanitaria": ["tessera", "salute", "medico", "sanitario", "asl", "codice", "fiscale"],
    "ricevuta": ["ricevute", "pagamento", "iscrizione", "immatricolazione", "quietanza", "scontrino", "fattura"],
    "ricevute": ["ricevuta", "pagamento", "iscrizione", "immatricolazione", "quietanza", "scontrino", "fattura"],
    "contratto": ["contratti", "accordo", "locazione", "affitto", "lavoro"],
    "contratti": ["contratto", "accordo", "locazione", "affitto", "lavoro"],
    "certificato": ["certificati", "attestato", "laurea", "residenza", "stato"],
    "certificati": ["certificato", "attestato", "laurea", "residenza", "stato"]
}


def it_stem(w: str) -> str:
    """Stemmer morfologico per la lingua italiana (singolari/plurali e suffissi comuni)."""
    w = w.lower().strip()
    if len(w) <= 3:
        return w
    for suf in ("zione", "zioni", "menti", "mento", "ante", "anti", "ario", "aria", "arie", "ari"):
        if w.endswith(suf) and len(w) > len(suf) + 2:
            return w[:-len(suf)]
    if w.endswith(("a", "e", "i", "o")):
        return w[:-1]
    return w


def token_matches(q_tok: str, word: str) -> Tuple[bool, float]:
    """
    Verifica se un token della query corrisponde a una parola target tramite:
    1. Uguaglianza esatta (1.0)
    2. Stemming italiano singolare/plurale (0.95)
    3. Prefisso di radice comune (0.85)
    4. Fuzzy matching per refusi e somiglianza fonetica (0.75+)
    """
    q_tok = q_tok.lower().strip()
    word = word.lower().strip()
    if not q_tok or not word or len(q_tok) < 2 or len(word) < 2:
        return False, 0.0

    if q_tok == word:
        return True, 1.0

    # Prefisso alfanumerico per modelli/versioni (es. 'mg' <-> 'mg4', 'iphone' <-> 'iphone15')
    if (len(q_tok) >= 2 and len(word) >= 2) and (
        re.sub(r"\d+$", "", word) == q_tok or re.sub(r"\d+$", "", q_tok) == word
    ):
        return True, 0.90

    qs = it_stem(q_tok)
    ws = it_stem(word)
    if qs == ws and len(qs) >= 3:
        return True, 0.95

    # Corrispondenza di prefisso (es. 'bollett' in 'bolletta', minimo 4 caratteri)
    if len(qs) >= 4 and len(ws) >= 4:
        if ws.startswith(qs) or qs.startswith(ws):
            return True, 0.85

    # Fuzzy matching per piccoli errori di battitura (es. 'nele' -> 'enel', 'pasaporto' -> 'passaporto')
    if len(q_tok) >= 4 and len(word) >= 4:
        ratio = difflib.SequenceMatcher(None, q_tok, word).ratio()
        if ratio >= 0.75:
            return True, ratio

    return False, 0.0


def search_vault_documents(db: Session, query: str, thread_id: str = "general") -> List[Dict[str, Any]]:
    """
    Esegue una ricerca intelligente, contestuale e tollerante ai refusi sui documenti del caveau.
    Supporta:
    - Flessione singolare/plurale (es. 'bollette' trova 'Bolletta ENEL')
    - Sinonimi contestuali (es. 'tasse' trova 'F24 IRPEF')
    - Tolleranza refusi (es. 'nele' trova 'Enel')
    - Scoring e discriminazione automatica dei risultati
    """
    raw_query = query.strip()
    clean_q = re.sub(r"[^\w]+", " ", raw_query.lower()).strip()
    broad_doc_queries = {"", "*", "tutti", "tutte", "tutti i documenti", "tutti i file", "documenti", "i documenti", "elenco", "lista", "elenco documenti", "lista documenti", "archivio"}
    if clean_q in broad_doc_queries:
        q_docs = db.query(Document)
        if thread_id and thread_id != "general" and thread_id != "all":
            q_docs = q_docs.filter(Document.thread_id == thread_id)
        docs = q_docs.order_by(Document.created_at.desc()).all()
        return [{
            "id": d.id,
            "document_id": d.id,
            "thread_id": d.thread_id,
            "title": d.title,
            "issuer": d.issuer,
            "doc_type": d.doc_type,
            "amount": d.amount,
            "due_date": d.due_date.isoformat() if d.due_date else None,
            "status": d.status,
            "summary": d.summary,
            "filename": Path(d.file_path).name if d.file_path else "",
            "file_url": f"/uploads/{Path(d.file_path).name}" if d.file_path else None,
            "download_url": f"/api/documents/{d.id}/download",
            "file_type": d.file_type
        } for d in docs]

    words = [w.lower() for w in re.split(r"[^\w]+", raw_query) if len(w) > 1]
    q_tokens = [w for w in words if w not in ITALIAN_STOPWORDS]
    if not q_tokens and words:
        q_tokens = words

    core_tokens = [w for w in q_tokens if w not in GENERIC_ATTRIBUTE_TERMS]
    if not core_tokens:
        core_tokens = q_tokens

    all_docs = db.query(Document).order_by(Document.created_at.desc()).all()
    doc_scored = []
    q_lower = raw_query.lower()

    for d in all_docs:
        t_l = (d.title or "").lower()
        i_l = (d.issuer or "").lower()
        dt_l = (d.doc_type or "").lower()
        s_l = (d.summary or "").lower()
        fn = Path(d.file_path).name if d.file_path else ""
        fn_l = fn.lower()

        t_words = [w for w in re.split(r"[^\w]+", t_l) if len(w) > 1]
        i_words = [w for w in re.split(r"[^\w]+", i_l) if len(w) > 1]
        dt_words = [w for w in re.split(r"[^\w]+", dt_l) if len(w) > 1]
        s_words = [w for w in re.split(r"[^\w]+", s_l) if len(w) > 1]
        f_words = [w for w in re.split(r"[^\w]+", fn_l) if len(w) > 1]

        key_words = t_words + i_words + dt_words + f_words

        matched_core_count = 0
        matched_key_count = 0
        for ct in core_tokens:
            syns = [ct] + CONCEPT_SYNONYMS.get(ct, []) + CONCEPT_SYNONYMS.get(it_stem(ct), [])
            if any(token_matches(tok, kw)[0] for tok in syns for kw in key_words):
                matched_core_count += 1
                matched_key_count += 1
            elif any(token_matches(ct, sw)[0] for sw in s_words):
                matched_core_count += 1

        # Phrase match sicuro: per stringhe brevi (2-3 caratteri come 'si') richiede word boundary
        has_phrase_match = False
        if len(q_lower) >= 4 and (q_lower in t_l or q_lower in s_l):
            has_phrase_match = True
        elif len(q_lower) >= 2 and (
            bool(re.search(rf"\b{re.escape(q_lower)}\b", t_l)) or
            bool(re.search(rf"\b{re.escape(q_lower)}\b", s_l))
        ):
            has_phrase_match = True

        if matched_core_count == 0 and not has_phrase_match:
            continue

        # Per query composte da 2+ parole chiave (es. 'collana rossa'):
        # Evita falsi positivi se nessuna parola corrisponde ai metadati chiave (titolo, emittente, tipo)
        # e solo un frammento isolato compare nella descrizione/sintesi del documento.
        if len(core_tokens) >= 2:
            if matched_key_count == 0 and not has_phrase_match and matched_core_count < len(core_tokens):
                continue
            if matched_core_count < max(2, int(len(core_tokens) * 0.5)) and not has_phrase_match:
                continue

        score = matched_core_count * 100
        if q_lower:
            if (len(q_lower) >= 4 and q_lower in t_l) or bool(re.search(rf"\b{re.escape(q_lower)}\b", t_l)):
                score += 150
            elif (len(q_lower) >= 4 and q_lower in s_l) or bool(re.search(rf"\b{re.escape(q_lower)}\b", s_l)):
                score += 50

        for ct in core_tokens:
            syns = [ct] + CONCEPT_SYNONYMS.get(ct, []) + CONCEPT_SYNONYMS.get(it_stem(ct), [])
            for tok in syns:
                is_direct = (tok == ct)
                mult = 2.0 if is_direct else 1.0
                for tw in t_words:
                    m, q = token_matches(tok, tw)
                    if m:
                        score += int(q * 80 * mult)
                for dw in dt_words:
                    m, q = token_matches(tok, dw)
                    if m:
                        score += int(q * 50 * mult)
                for iw in i_words:
                    m, q = token_matches(tok, iw)
                    if m:
                        score += int(q * 40 * mult)
                for fw in f_words:
                    m, q = token_matches(tok, fw)
                    if m:
                        score += int(q * 30 * mult)
                for sw in s_words:
                    m, q = token_matches(tok, sw)
                    if m:
                        score += int(q * 10 * mult)

        if score > 0:
            if d.thread_id == thread_id:
                score += 5
            doc_scored.append((score, matched_core_count, {
                "id": d.id,
                "document_id": d.id,
                "thread_id": d.thread_id,
                "title": d.title,
                "issuer": d.issuer,
                "doc_type": d.doc_type,
                "amount": d.amount,
                "due_date": d.due_date.isoformat() if d.due_date else None,
                "status": d.status,
                "summary": d.summary,
                "filename": fn,
                "file_url": f"/uploads/{fn}",
                "download_url": f"/api/documents/{d.id}/download",
                "file_type": d.file_type
            }))

    doc_scored.sort(key=lambda x: (x[1], x[0]), reverse=True)

    if not doc_scored:
        return []

    max_matched = doc_scored[0][1]
    if max_matched > 1:
        filtered_entries = [x for x in doc_scored if x[1] == max_matched]
    else:
        filtered_entries = doc_scored

    top_score = filtered_entries[0][0]
    cutoff = max(20, top_score * 0.5)
    filtered = [x[2] for x in filtered_entries if x[0] >= cutoff]

    if len(filtered) > 1 and top_score >= 150 and filtered_entries[1][0] < top_score * 0.6:
        filtered = [filtered[0]]

    return filtered[:6]


def search_vault_items(db: Session, query: str, thread_id: str = "general") -> List[Dict[str, Any]]:
    """
    Esegue una ricerca intelligente, contestuale e tollerante sui record degli oggetti fisici nel caveau.
    """
    raw_query = query.strip()
    clean_q = re.sub(r"[^\w]+", " ", raw_query.lower()).strip()
    broad_item_queries = {"", "*", "tutti", "tutte", "tutti gli oggetti", "oggetti", "gli oggetti", "oggetto", "elenco", "lista", "elenco oggetti", "lista oggetti", "posizioni", "le mie cose", "mie cose", "cose"}
    if clean_q in broad_item_queries:
        q_items = db.query(PhysicalItem)
        if thread_id and thread_id != "general" and thread_id != "all":
            q_items = q_items.filter(PhysicalItem.thread_id == thread_id)
        items = q_items.order_by(PhysicalItem.updated_at.desc()).all()
        return [{
            "item_id": it.id,
            "thread_id": it.thread_id,
            "item_name": it.item_name,
            "primary_location": it.primary_location,
            "detailed_location": it.detailed_location,
            "category": it.category,
            "location_str": it.primary_location + (f" ({it.detailed_location})" if it.detailed_location else ""),
            "image_url": f"/api/files/{Path(it.image_path).name}" if it.image_path else None,
            "has_photo": bool(it.image_path),
            "document_id": it.document_id
        } for it in items]

    words = [w.lower() for w in re.split(r"[^\w]+", raw_query) if len(w) > 1]
    q_tokens = [w for w in words if w not in ITALIAN_STOPWORDS]
    if not q_tokens and words:
        q_tokens = words

    core_tokens = [w for w in q_tokens if w not in GENERIC_ATTRIBUTE_TERMS]
    if not core_tokens:
        core_tokens = q_tokens

    all_items = db.query(PhysicalItem).order_by(PhysicalItem.updated_at.desc()).all()
    item_scored = []
    q_lower = raw_query.lower()

    for it in all_items:
        n_l = (it.item_name or "").lower()
        l_l = (it.primary_location or "").lower()
        d_l = (it.detailed_location or "").lower()
        c_l = (it.category or "").lower()
        notes_l = (it.notes or "").lower()

        n_words = [w for w in re.split(r"[^\w]+", n_l) if len(w) > 1]
        l_words = [w for w in re.split(r"[^\w]+", l_l) if len(w) > 1]
        d_words = [w for w in re.split(r"[^\w]+", d_l) if len(w) > 1]
        c_words = [w for w in re.split(r"[^\w]+", c_l) if len(w) > 1]
        notes_words = [w for w in re.split(r"[^\w]+", notes_l) if len(w) > 1]

        doc_words = []
        if it.document_id:
            from app.models.database import Document
            doc_rec = db.query(Document).filter(Document.id == it.document_id).first()
            if doc_rec:
                doc_title = (doc_rec.title or "").lower()
                doc_words = [w for w in re.split(r"[^\w]+", doc_title) if len(w) > 1]

        key_words = n_words + l_words + d_words + c_words + notes_words + doc_words

        matched_core_count = 0
        for ct in core_tokens:
            syns = [ct] + CONCEPT_SYNONYMS.get(ct, []) + CONCEPT_SYNONYMS.get(it_stem(ct), [])
            if any(token_matches(tok, kw)[0] for tok in syns for kw in key_words):
                matched_core_count += 1

        if matched_core_count == 0 and not (q_lower in n_l or q_lower in l_l or q_lower in d_l):
            continue

        score = matched_core_count * 100
        if q_lower and q_lower in n_l:
            score += 150
        elif q_lower and (q_lower in l_l or q_lower in d_l):
            score += 50

        for ct in core_tokens:
            syns = [ct] + CONCEPT_SYNONYMS.get(ct, []) + CONCEPT_SYNONYMS.get(it_stem(ct), [])
            for tok in syns:
                is_direct = (tok == ct)
                mult = 2.0 if is_direct else 1.0
                for nw in n_words:
                    m, q = token_matches(tok, nw)
                    if m:
                        score += int(q * 80 * mult)
                for lw in l_words:
                    m, q = token_matches(tok, lw)
                    if m:
                        score += int(q * 40 * mult)
                for dw in d_words:
                    m, q = token_matches(tok, dw)
                    if m:
                        score += int(q * 30 * mult)
                for cw in c_words:
                    m, q = token_matches(tok, cw)
                    if m:
                        score += int(q * 30 * mult)
                for nw_note in notes_words:
                    m, q = token_matches(tok, nw_note)
                    if m:
                        score += int(q * 10 * mult)
                for dw_doc in doc_words:
                    m, q = token_matches(tok, dw_doc)
                    if m:
                        score += int(q * 20 * mult)

        if score > 0:
            if it.thread_id == thread_id:
                score += 5
            item_scored.append((score, matched_core_count, {
                "item_id": it.id,
                "thread_id": it.thread_id,
                "item_name": it.item_name,
                "primary_location": it.primary_location,
                "detailed_location": it.detailed_location,
                "category": it.category,
                "location_str": it.primary_location + (f" ({it.detailed_location})" if it.detailed_location else ""),
                "image_url": f"/api/files/{Path(it.image_path).name}" if it.image_path else None,
                "has_photo": bool(it.image_path),
                "document_id": it.document_id
            }))

    item_scored.sort(key=lambda x: (x[1], x[0]), reverse=True)

    if not item_scored:
        return []

    max_matched = item_scored[0][1]
    if max_matched > 1:
        filtered_entries = [x for x in item_scored if x[1] == max_matched]
    else:
        filtered_entries = item_scored

    top_score = filtered_entries[0][0]
    cutoff = max(20, top_score * 0.5)
    filtered = [x[2] for x in filtered_entries if x[0] >= cutoff]

    if len(filtered) > 1 and top_score >= 150 and filtered_entries[1][0] < top_score * 0.6:
        filtered = [filtered[0]]

    return filtered[:6]
