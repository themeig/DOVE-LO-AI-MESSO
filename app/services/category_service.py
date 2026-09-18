"""
Modulo Servizio Categorie e Sottocartelle del Caveau (Dove lo AI messo)
- Catalogo cartelle generali standard (Utenze & Bollette, Fisco & Tributi, ecc.)
- Deduplicazione e convergenza semantica per evitare cartelle frammentate o quasi identiche
- Ispezione delle sezioni attive nel Caveau prima di creare nuove sezioni
- Estrazione automatica e deduplicazione delle sottocartelle (es. Anno '2026', '2025' o sotto-temi)
- Consolidamento retroattivo del database
"""

from __future__ import annotations
import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Optional, List, Dict, Tuple, Any
from sqlalchemy.orm import Session
from sqlalchemy import text


# Catalogo macro-cartelle generali standard di Dove lo AI messo
DEFAULT_GENERAL_CATEGORIES: List[Dict[str, Any]] = [
    {
        "slug": "utenze_bollette",
        "label": "Utenze & Bollette",
        "icon": "fa-bolt",
        "keywords": [
            "bolletta", "bollette", "luce", "gas", "acqua", "energia", "enel", "servizio elettrico",
            "telecom", "fibra", "internet", "utenza", "utenze", "rifiuti", "tari", "canone rai",
            "telefonia", "vodafone", "tim", "windtre", "a2a", "iren", "hera", "sorgenia", "plenitude",
            "edison", "fastweb", "iliad", "smc", "kwh", "fornitura", "consumi", "mercato libero"
        ]
    },
    {
        "slug": "fisco_tributi",
        "label": "Fisco, Tributi & F24",
        "icon": "fa-landmark",
        "keywords": [
            "f24", "fisco", "tributi", "tasse", "imposta", "imposte", "agenzia delle entrate", "imu",
            "irpef", "iva", "dichiarazione dei redditi", "730", "unico", "ravvedimento", "inps", "inail",
            "cartella esattoriale", "agenzia entrate riscossione", "tributo", "tassa", "quietanza f24"
        ]
    },
    {
        "slug": "ricevute_spese",
        "label": "Fatture, Spese & Ricevute",
        "icon": "fa-receipt",
        "keywords": [
            "fattura", "fatture", "ricevuta", "ricevute", "scontrino", "scontrini", "parcella",
            "spesa", "spese", "pagamento", "pagamenti", "quietanza", "nota spese", "acquisto",
            "ordine", "bonifico", "contabilita", "rimborso"
        ]
    },
    {
        "slug": "contratti_polizze",
        "label": "Contratti, Polizze & Assicurazioni",
        "icon": "fa-file-signature",
        "keywords": [
            "contratto", "contratti", "polizza", "polizze", "assicurazione", "assicurazioni",
            "sinistro", "locazione", "affitto", "comodato", "accordo", "clausola", "rc auto",
            "mutuo", "finanziamento", "prestiti", "scrittura privata"
        ]
    },
    {
        "slug": "documenti_identita",
        "label": "Documenti Personali & Identità",
        "icon": "fa-id-card",
        "keywords": [
            "carta identita", "carta d'identita", "passaporto", "patente", "codice fiscale",
            "tessera sanitaria", "permesso di soggiorno", "certificato nascita", "stato di famiglia",
            "documento riconoscimento", "identita", "tessera"
        ]
    },
    {
        "slug": "sanita_spese_mediche",
        "label": "Sanità & Spese Mediche",
        "icon": "fa-heart-pulse",
        "keywords": [
            "medico", "sanita", "visita medica", "ricetta", "farmacia", "ticket", "esame",
            "referto", "analisi", "ospedale", "clinica", "dentista", "oculista", "farmaco",
            "prestazione sanitaria", "asl", "ssn", "visita specialistica"
        ]
    },
    {
        "slug": "formazione_certificati",
        "label": "Formazione & Certificati",
        "icon": "fa-graduation-cap",
        "keywords": [
            "scuola", "universita", "laurea", "master", "corso", "certificato", "diploma",
            "attestato", "esame universitario", "tassa universitaria", "iscrizione", "tolc",
            "cisia", "crediti cfu", "maturita", "studio", "certificati"
        ]
    },
    {
        "slug": "auto_veicoli",
        "label": "Automobili & Veicoli",
        "icon": "fa-car",
        "keywords": [
            "auto", "automobile", "veicolo", "veicoli", "macchina", "moto", "motocicletta",
            "bollo auto", "revisione", "tagliando", "meccanico", "libretto", "multa",
            "contravvenzione", "autovelox", "patente guida"
        ]
    },
    {
        "slug": "canzoni_musica",
        "label": "Canzoni & Testi Musicali",
        "icon": "fa-music",
        "keywords": [
            "canzone", "canzoni", "musica", "brano", "brani", "testo canzone", "accordi",
            "spartito", "karaoke", "poesia", "poesie", "strofa", "strofe", "ritornello",
            "album", "traccia", "audio", "cantautore", "pensieri", "riflessioni", "note personali",
            "testo brano", "testi canzoni", "brani musicali"
        ]
    },
    {
        "slug": "archivi_zip",
        "label": "Archivi Compressi & ZIP",
        "icon": "fa-file-zipper",
        "keywords": [
            "zip", "rar", "archivio", "archivio compresso", "7z", "tar", "backup", "archivio zip"
        ]
    },
    {
        "slug": "foto_immagini",
        "label": "Foto & Immagini",
        "icon": "fa-image",
        "keywords": [
            "foto", "fotografia", "fotografie", "immagine", "immagini", "ricordo", "ricordi",
            "screenshot", "album fotografico", "scatto", "cattura"
        ]
    }
]


def normalize_tokens(s: str) -> List[str]:
    """Normalizza una stringa in una lista di token senza accenti e caratteri speciali."""
    if not s:
        return []
    nfkd = unicodedata.normalize("NFKD", s)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c)).lower()
    tokens = re.findall(r"\b[a-z0-9]{2,}\b", ascii_str)
    # Rimuovi stopwords frequenti in italiano (preposizioni, articoli, congiunzioni)
    stopwords = {
        "di", "a", "da", "in", "con", "su", "per", "tra", "fra",
        "il", "lo", "la", "i", "gli", "le",
        "del", "della", "delle", "dello", "degli", "dei",
        "nel", "nella", "nelle", "nello", "negli", "nei",
        "al", "alla", "alle", "allo", "agli", "ai",
        "dal", "dalla", "dalle", "dallo", "dagli", "dai",
        "sul", "sulla", "sulle", "sullo", "sugli", "sui",
        "un", "uno", "una", "ed", "ad", "od",
        "e", "o", "che", "cui", "quale", "quali",
        "altri", "altre", "altro", "altra"
    }
    return [t for t in tokens if t not in stopwords]


def slugify(label: str) -> str:
    """Genera uno slug pulito a partire da un'etichetta testuale."""
    if not label:
        return "altro"
    nfkd = unicodedata.normalize("NFKD", label)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c)).lower()
    cleaned = re.sub(r"[^a-z0-9]+", "_", ascii_str).strip("_")
    return cleaned or "altro"


def stem_it(w: str) -> str:
    """Radice semplificata per corrispondenze singolare/plurale in italiano."""
    word = w.lower().strip()
    if len(word) >= 4 and word[-1] in ("e", "i", "o", "a"):
        return word[:-1]
    return word


def score_label_affinity(tokens: set[str], label: str, cat: Dict[str, Any]) -> float:
    """Calcola l'affinità testuale tra un'etichetta/token e una cartella."""
    cat_label = cat["label"]
    cat_tokens = set(normalize_tokens(cat_label))

    l_low = label.lower().strip()
    cl_low = cat_label.lower().strip()

    if l_low == cl_low:
        return 10.0
    if l_low and (l_low in cl_low or cl_low in l_low):
        return 6.0

    stems = {stem_it(t) for t in tokens}
    cat_stems = {stem_it(t) for t in cat_tokens}
    common = stems.intersection(cat_stems)
    if common:
        return len(common) * 3.5

    return 0.0


def get_active_vault_categories(db: Optional[Session] = None) -> List[Dict[str, Any]]:
    """
    Restituisce l'elenco consolidato delle cartelle disponibili:
    1. Le macro-cartelle standard di sistema (DEFAULT_GENERAL_CATEGORIES)
    2. Eventuali cartelle custom create dall'utente o dall'AI già presenti nel Caveau (da Document)
    """
    categories: Dict[str, Dict[str, Any]] = {}

    # 1. Carica le cartelle standard di sistema
    for cat in DEFAULT_GENERAL_CATEGORIES:
        categories[cat["slug"]] = {
            "slug": cat["slug"],
            "label": cat["label"],
            "icon": cat["icon"],
            "keywords": list(cat.get("keywords", [])),
            "is_default": True
        }

    # 2. Carica le categorie reali esistenti nel database
    if db is not None:
        try:
            from app.models.database import Document
            existing_rows = db.query(
                Document.category,
                Document.category_label,
                Document.category_icon
            ).filter(Document.category_label.isnot(None)).distinct().all()

            for cat_slug, cat_label, cat_icon in existing_rows:
                if not cat_label:
                    continue
                clean_lbl = cat_label.strip()
                tokens = set(normalize_tokens(clean_lbl))
                # Se è già affine o una variante di una macro-cartella standard di sistema,
                # non registrarla come categoria custom separata, così i documenti convergeranno
                # verso la macro-cartella standard canonica
                if any(score_label_affinity(tokens, clean_lbl, std_cat) >= 3.0 for std_cat in DEFAULT_GENERAL_CATEGORIES):
                    continue

                resolved_slug = cat_slug or slugify(clean_lbl)
                if resolved_slug not in categories:
                    categories[resolved_slug] = {
                        "slug": resolved_slug,
                        "label": clean_lbl,
                        "icon": cat_icon or "fa-folder-closed",
                        "keywords": normalize_tokens(clean_lbl),
                        "is_default": False
                    }
        except Exception:
            pass

    return list(categories.values())


def extract_subfolder(
    due_date: Optional[Any] = None,
    text_content: Optional[str] = None,
    filename: Optional[str] = None,
    proposed_subfolder: Optional[str] = None,
    doc_type: Optional[str] = None
) -> Optional[str]:
    """
    Estrae o deduce la sottocartella appropriata (es. per Anno '2026', '2025' o sotto-tema 'Locazioni').
    
    Ordine di priorità:
    1. Sottocartella esplicitamente proposta (es. da parametri o da AI): se valida, usata direttamente.
    2. Data di scadenza (due_date): se presente anno YYYY, usa l'anno.
    3. Anno a 4 cifre identificato nel nome del file o nel testo del documento (es. 2024, 2025, 2026).
    4. Se documento contabile/fiscale/utenza privo di data, assegna l'anno corrente (UTC).
    """
    # 1. Sottocartella proposta
    if proposed_subfolder and proposed_subfolder.strip():
        sub = proposed_subfolder.strip().strip("/\\.")
        # Se è un anno a 4 cifre valido
        if re.match(r"^20\d{2}$", sub):
            return sub
        # Se è una stringa alfanumerica pulita
        if len(sub) >= 2:
            return sub.capitalize()

    # 2. Da due_date (date, datetime o stringa YYYY-MM-DD)
    if due_date is not None:
        if isinstance(due_date, (date, datetime)):
            return str(due_date.year)
        if isinstance(due_date, str):
            m_year = re.search(r"(?<!\d)(20[123]\d)(?!\d)", due_date)
            if m_year:
                return m_year.group(1)

    # 3. Ricerca anno a 4 cifre nel nome file o testo
    sources = []
    if filename:
        sources.append(filename)
    if text_content:
        sources.append(text_content[:1500])

    combined_text = " ".join(sources)
    # Cerchiamo anni recenti o prossimi (es. 2018 - 2035) delimitati da caratteri non numerici
    found_years = re.findall(r"(?<!\d)(20[123]\d)(?!\d)", combined_text)
    if found_years:
        return found_years[0]

    # 4. Fallback ad anno corrente per documenti tipicamente annuali
    dt = (doc_type or "").lower()
    if dt in ["bolletta", "utenza", "f24", "tributo", "fattura", "spese", "ricevuta", "modello_unico", "dichiarazione_redditi"]:
        return str(datetime.now(timezone.utc).year)

    return None


def resolve_or_create_category_and_subfolder(
    proposed_label: Optional[str] = None,
    document_text: Optional[str] = None,
    doc_type: Optional[str] = None,
    due_date: Optional[Any] = None,
    db: Optional[Session] = None,
    proposed_slug: Optional[str] = None,
    proposed_icon: Optional[str] = None,
    proposed_subfolder: Optional[str] = None,
    filename: Optional[str] = None
) -> Tuple[str, str, str, Optional[str]]:
    """
    Risolve in modo intelligente e deterministico la categoria (cartella generale) e la sottocartella:
    1. Ispeziona le cartelle generali standard ed attive nel Caveau.
    2. Se il contenuto/etichetta è affine o pertinente a una cartella esistente,
       unifica verso quella cartella esistente evitando duplicati (es. 'Testi Canzoni' -> 'Canzoni, Musica & Testi Personali').
    3. Se e solo se NON c'è alcuna cartella pertinente, crea una nuova cartella con label ed icona adatte.
    4. Deduce o assegna la sottocartella (es. Anno '2026' o tema).
    
    Ritorna: (slug, label, icon, subfolder)
    """
    active_categories = get_active_vault_categories(db)

    # Raccogli contesto per il matching
    p_label = (proposed_label or "").strip()
    p_tokens = set(normalize_tokens(p_label))
    t_tokens = set(normalize_tokens(document_text or ""))
    fn_tokens = set(normalize_tokens(filename or ""))
    combined_tokens = p_tokens.union(fn_tokens)
    clean_type = (doc_type or "").lower().strip()

    best_match: Optional[Dict[str, Any]] = None
    best_score = 0.0

    # Valutazione di inerenza con ciascuna categoria attiva/standard
    for cat in active_categories:
        score = 0.0
        cat_slug = cat["slug"]
        cat_label = cat["label"]
        cat_tokens = set(normalize_tokens(cat_label))
        cat_keywords = set(normalize_tokens(" ".join(cat.get("keywords", []))))

        # 1. Corrispondenza esatta o per slug
        if proposed_slug and proposed_slug.lower() == cat_slug:
            score += 10.0
        if p_label.lower() == cat_label.lower():
            score += 10.0

        # 2. Inclusione o sotto-stringa nel titolo della cartella
        if p_label and (p_label.lower() in cat_label.lower() or cat_label.lower() in p_label.lower()):
            score += 6.0

        # 3. Sovrapposizione di parole chiave tra etichetta proposta e cartella
        common_label_tokens = p_tokens.intersection(cat_tokens)
        if common_label_tokens:
            score += len(common_label_tokens) * 3.5

        # 4. Parole chiave del catalogo presenti nell'etichetta proposta o nel nome del file
        common_keywords = combined_tokens.intersection(cat_keywords)
        if common_keywords:
            score += len(common_keywords) * 2.5

        # 5. Sovrapposizione con il testo reale del documento
        text_keywords = t_tokens.intersection(cat_keywords)
        if text_keywords:
            score += min(len(text_keywords) * 0.8, 4.0)

        # 6. Regole specifiche per doc_type
        if clean_type in ["bolletta", "utenza"] and cat_slug == "utenze_bollette":
            score += 5.0
        elif clean_type in ["f24", "tributo", "fiscale"] and cat_slug == "fisco_tributi":
            score += 5.0
        elif clean_type in ["fattura", "ricevuta", "scontrino", "spese"] and cat_slug == "ricevute_spese":
            score += 5.0
        elif clean_type in ["canzone", "musica", "poesia", "testo_personale"] and cat_slug == "canzoni_musica":
            score += 6.0
        elif clean_type in ["contratto", "polizza", "assicurazione"] and cat_slug == "contratti_polizze":
            score += 5.0
        elif clean_type in ["archivio_zip", "zip"] and cat_slug == "archivi_zip":
            score += 6.0
        elif clean_type in ["foto", "screenshot"] and cat_slug == "foto_immagini":
            score += 4.0

        if score > best_score:
            best_score = score
            best_match = cat

    # Soglia minima di inerenza per convergere verso una cartella esistente
    # Se il punteggio è sufficientemente alto (>= 3.0), unifica con la cartella esistente!
    if best_match and best_score >= 3.0:
        final_slug = best_match["slug"]
        final_label = best_match["label"]
        final_icon = best_match["icon"]
    else:
        # Se non c'è inerenza con nessuna cartella esistente, crea una nuova cartella pulita
        if p_label:
            final_label = p_label.strip()
            final_slug = proposed_slug or slugify(p_label)
            final_icon = proposed_icon or "fa-folder-open"
        else:
            final_slug = "altro"
            final_label = "Altri Documenti"
            final_icon = "fa-folder-closed"

    # Estrazione della sottocartella (Anno o sotto-tema)
    resolved_subfolder = extract_subfolder(
        due_date=due_date,
        text_content=document_text,
        filename=filename,
        proposed_subfolder=proposed_subfolder,
        doc_type=clean_type
    )

    return final_slug, final_label, final_icon, resolved_subfolder


def consolidate_vault_categories(db: Session) -> Dict[str, Any]:
    """
    Consolida retroattivamente le cartelle e assegna le sottocartelle
    a tutti i documenti esistenti nel Caveau, unificando le sezioni duplicate.
    """
    from app.models.database import Document
    docs = db.query(Document).all()
    updated_count = 0
    merged_sections = set()

    for d in docs:
        old_label = d.category_label or ""
        old_sub = d.subfolder

        slug, label, icon, sub = resolve_or_create_category_and_subfolder(
            proposed_label=d.category_label,
            document_text=d.summary,
            doc_type=d.doc_type,
            due_date=d.due_date,
            db=db,
            proposed_slug=d.category,
            proposed_icon=d.category_icon,
            proposed_subfolder=d.subfolder,
            filename=d.file_path
        )

        changed = False
        if d.category != slug or d.category_label != label or d.category_icon != icon:
            if old_label and old_label != label:
                merged_sections.add(f"{old_label} -> {label}")
            d.category = slug
            d.category_label = label
            d.category_icon = icon
            changed = True

        if sub and not d.subfolder:
            d.subfolder = sub
            changed = True

        if changed:
            updated_count += 1

    if updated_count > 0:
        db.commit()

    return {
        "updated_documents_count": updated_count,
        "merged_sections": list(merged_sections)
    }
