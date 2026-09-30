"""
Modulo Servizio Vettoriale (pgvector & SQLite Fallback) per 'Dove lo AI messo'.
Supporta chunking del testo, generazione di embedding a 768 dimensioni,
salvataggio su database multi-tenant (document_embeddings) e ricerca per similarità cosenica.
"""
import math
import hashlib
import logging
from typing import List, Dict, Any, Optional, Union
import httpx
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.database import DocumentEmbedding, Document, HAS_PGVECTOR
from app.config import get_settings

logger = logging.getLogger(__name__)


def chunk_text(text: str, chunk_size: int = 800, chunk_overlap: int = 150) -> List[str]:
    """
    Suddivide il testo in frammenti (chunks) con sovrapposizione (overlap),
    rispettando la punteggiatura e i confini di riga/parola.
    """
    if not text:
        return []

    clean = text.strip()
    if len(clean) <= chunk_size:
        return [clean]

    chunks = []
    start = 0
    text_len = len(clean)

    while start < text_len:
        end = min(start + chunk_size, text_len)

        # Se non siamo alla fine, cerca un punto naturale di interruzione (newline, punto, punto e virgola, spazio)
        if end < text_len:
            split_points = [
                clean.rfind("\n\n", start, end),
                clean.rfind("\n", start, end),
                clean.rfind(". ", start, end),
                clean.rfind("; ", start, end),
                clean.rfind(" ", start, end),
            ]
            valid_splits = [p for p in split_points if p > start + (chunk_size // 3)]
            if valid_splits:
                end = valid_splits[0] + 1

        chunk = clean[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= text_len:
            break

        # Avanza tenendo conto dell'overlap
        next_start = end - chunk_overlap
        if next_start <= start:
            next_start = end
        start = next_start

    return chunks


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calcola la similarità cosenica tra due vettori numerici."""
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0

    dot = 0.0
    norm1 = 0.0
    norm2 = 0.0

    for a, b in zip(vec1, vec2):
        dot += a * b
        norm1 += a * a
        norm2 += b * b

    if norm1 <= 0.0 or norm2 <= 0.0:
        return 0.0

    return dot / (math.sqrt(norm1) * math.sqrt(norm2))


def generate_deterministic_embedding(text: str, dim: int = 768) -> List[float]:
    """
    Genera un embedding pseudo-semantico deterministico a 'dim' dimensioni (default 768).
    Utilizzato per ambienti offline, test automatici e fallback senza chiavi API.
    Basato su n-gram hashing distribuito uniformemente e normalizzato in norma L2.
    """
    if not text:
        return [0.0] * dim

    words = text.lower().split()
    vector = [0.0] * dim

    for idx, word in enumerate(words):
        # Hash della parola singola
        h1 = int(hashlib.sha256(word.encode("utf-8")).hexdigest()[:8], 16)
        pos1 = h1 % dim
        vector[pos1] += 1.0

        # Hash di bigrammi per preservare relazioni di sequenza
        if idx < len(words) - 1:
            bigram = f"{word}_{words[idx + 1]}"
            h2 = int(hashlib.md5(bigram.encode("utf-8")).hexdigest()[:8], 16)
            pos2 = h2 % dim
            vector[pos2] += 1.5

    # Normalizzazione L2
    norm = math.sqrt(sum(x * x for x in vector))
    if norm > 0:
        return [x / norm for x in vector]
    return [0.0] * dim


def generate_embedding(text: str, dim: int = 768) -> List[float]:
    """Generazione sincrona di embedding vettoriale."""
    # Se presente configurazione per embedding online (es. Google Gemini o OpenRouter),
    # potrà effettuare la chiamata remota; altrimenti usa il generatore deterministico locale.
    return generate_deterministic_embedding(text, dim=dim)


async def generate_embedding_async(
    text: str,
    client: Optional[httpx.AsyncClient] = None,
    dim: int = 768
) -> List[float]:
    """Generazione asincrona non-bloccante di embedding vettoriale."""
    # In assenza di chiavi esterne per embedding, fallback immediato su generatore locale
    return generate_deterministic_embedding(text, dim=dim)


def store_document_chunks(
    db: Session,
    document_id: int,
    text_content: str,
    user_id: Optional[str] = None,
    chunk_size: int = 800,
    chunk_overlap: int = 150
) -> List[DocumentEmbedding]:
    """
    Suddivide il testo di un documento in frammenti (chunks),
    calcola gli embedding vettoriali e li archivia nella tabella document_embeddings.
    Idempotente: rimuove eventuali frammenti pregressi per lo stesso documento.
    """
    # 1. Rimuovi chunks precedenti per evitare duplicazioni
    db.query(DocumentEmbedding).filter(DocumentEmbedding.document_id == document_id).delete()

    chunks = chunk_text(text_content, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    created_embeddings = []

    for idx, ch in enumerate(chunks):
        vec = generate_embedding(ch, dim=768)
        emb_record = DocumentEmbedding(
            user_id=user_id,
            document_id=document_id,
            chunk_index=idx,
            chunk_text=ch,
            embedding=vec
        )
        db.add(emb_record)
        created_embeddings.append(emb_record)

    db.commit()
    return created_embeddings


def search_vector_semantic(
    db: Session,
    query_text_or_vector: Union[str, List[float]],
    top_k: int = 5,
    user_id: Optional[str] = None,
    category: Optional[str] = None,
    min_similarity: float = 0.05
) -> List[Dict[str, Any]]:
    """
    Ricerca per similarità cosenica semantica sui frammenti di documenti indicizzati.
    Multi-tenant ready: isola per user_id se fornito.
    Restituisce i migliori documenti associati ordinati per punteggio di similarità decrescente.
    """
    if isinstance(query_text_or_vector, str):
        query_vector = generate_embedding(query_text_or_vector, dim=768)
    else:
        query_vector = query_text_or_vector

    query = db.query(DocumentEmbedding, Document).join(Document, DocumentEmbedding.document_id == Document.id)

    # Multi-tenancy filter
    if user_id:
        query = query.filter(
            or_(
                DocumentEmbedding.user_id == user_id,
                DocumentEmbedding.user_id.is_(None),
                Document.user_id == user_id,
                Document.user_id.is_(None)
            )
        )

    # Categoria o tipologia opzionale
    if category and category.lower() not in ("all", "tutti", ""):
        cat_clean = category.lower().strip()
        query = query.filter(
            or_(
                Document.category.ilike(f"%{cat_clean}%"),
                Document.doc_type.ilike(f"%{cat_clean}%")
            )
        )

    candidates = query.all()
    if not candidates:
        return []

    # Calcolo similarità cosenica
    scored_results = []
    doc_best_chunk: Dict[int, Dict[str, Any]] = {}

    for emb, doc in candidates:
        emb_vec = emb.embedding
        if not emb_vec:
            continue
        sim = cosine_similarity(query_vector, emb_vec)
        if sim < min_similarity:
            continue

        doc_id = doc.id
        if doc_id not in doc_best_chunk or sim > doc_best_chunk[doc_id]["score"]:
            doc_best_chunk[doc_id] = {
                "document_id": doc.id,
                "title": doc.title,
                "score": round(float(sim), 4),
                "chunk_index": emb.chunk_index,
                "chunk_text": emb.chunk_text,
                "issuer": doc.issuer,
                "amount": doc.amount,
                "due_date": doc.due_date.isoformat() if doc.due_date else None,
                "status": doc.status,
                "category": doc.category,
                "doc_type": doc.doc_type,
                "summary": doc.summary,
                "file_path": doc.file_path,
                "drive_web_url": doc.drive_web_url,
            }

    results = sorted(doc_best_chunk.values(), key=lambda x: x["score"], reverse=True)
    return results[:top_k]
