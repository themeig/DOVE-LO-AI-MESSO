import json
import logging
import re
from pathlib import Path
import httpx
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.config import get_settings
from app.models.database import Document, PhysicalItem, ChatMessage, ChatThread, get_app_setting
from app.models.schemas import ChatResponse
from app.services.ai_service import get_ai_service, MockAIService
from app.services.search_service import (
    search_vault_documents,
    search_vault_items,
    ITALIAN_STOPWORDS,
    GENERIC_ATTRIBUTE_TERMS,
    it_stem,
    token_matches,
)

logger = logging.getLogger(__name__)

TOOLS_DEFINITION = [
    {
        "type": "function",
        "function": {
            "name": "search_vault",
            "description": (
                "Cerca nel caveau qualsiasi informazione: sia file e documenti archiviati (es. certificati, tolc, bollette, contratti, f24) "
                "sia posizioni fisiche di oggetti memorizzati (es. chiavi, passaporto, caricatore, scarpe, occhiali, faldoni)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "La parola chiave o il nome dell'oggetto/documento da cercare (es. 'tolc', 'passaporto', 'bolletta', 'scrivania')"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_vault_documents",
            "description": "Recupera gli ultimi file e documenti caricati dall'utente (utile quando l'utente chiede 'che file è?', 'cos'ho caricato?', 'dimmi dell'ultimo documento').",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Numero di documenti recenti da recuperare (default 3)"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "store_physical_item",
            "description": "Memorizza o aggiorna la posizione fisica di un oggetto nel caveau (es. quando l'utente dice dove ha messo qualcosa).",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {"type": "string", "description": "Nome dell'oggetto (es. 'Passaporto', 'Chiavi di scorta')"},
                    "primary_location": {"type": "string", "description": "Stanza o ambiente principale (es. 'Studio', 'Cucina', 'Camera')"},
                    "detailed_location": {"type": "string", "description": "Dettaglio specifico del mobile o ripiano (es. 'Primo cassetto scrivania')"},
                    "category": {"type": "string", "description": "Categoria dell'oggetto (es. 'documenti', 'chiavi', 'veicoli', 'elettronica')"}
                },
                "required": ["item_name", "primary_location"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_upcoming_deadlines",
            "description": "Recupera l'elenco delle bollette, tributi o scadenze ancora da pagare registrate nel caveau.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_vault_record",
            "description": "Predispone il widget di conferma interattivo per eliminare un documento o un oggetto dal caveau. Cerca prima con `search_vault` per ricavare target_type, target_id e title.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_type": {
                        "type": "string",
                        "enum": ["document", "physical_item"],
                        "description": "Tipo di record: 'document' per file e ricevute, 'physical_item' per posizioni di oggetti"
                    },
                    "target_id": {
                        "type": "integer",
                        "description": "ID numerico del documento o dell'oggetto da eliminare"
                    },
                    "title": {
                        "type": "string",
                        "description": "Nome o titolo dell'elemento"
                    }
                },
                "required": ["target_type", "target_id", "title"]
            }
        }
    }
]

SYSTEM_PROMPT = """Sei l'assistente AI per WhatsApp di 'Dove lo AI messo', un caveau intelligente per famiglie e professionisti italiani.
Hai accesso ad appositi STRUMENTI (tools) per interagire con il database SQLite del caveau. Hai piena autonomia e intelligenza per comprendere e soddisfare le richieste dell'utente in linguaggio naturale.

REGOLE FERREE:
1. QUANDO L'UTENTE CHIEDE DI UN FILE O DOCUMENTO (es. "dammi il documento del mutuo", "mostrami la bolletta", "che file è?", "trovami il certificato del tolc", "cerca la bolletta enel"):
   - DEVI SEMPRE USARE lo strumento `search_vault`!
   - NON rispondere MAI a memoria senza chiamare `search_vault`, perché la chiamata di `search_vault` è INDISPENSABILE per consentire al sistema di mostrare il widget grafico del documento (con anteprima e pulsante "Vedi") all'utente!
   - Spiega con precisione e ricchezza di dettagli tutti i dati trovati (titolo, emittente, intestatario, voti/punteggi, importi e date).

2. QUANDO L'UTENTE CHIEDE DOVE SI TROVA UN OGGETTO (es. "dov'è il passaporto?", "dove ho messo le chiavi?"):
   - USA lo strumento `search_vault` per cercarlo tra gli oggetti fisici e i documenti.
   - Se lo trovi, indica la stanza e il mobile esatti. Se non lo trovi dopo la ricerca, invitalo gentilmente a memorizzarlo.

3. QUANDO L'UTENTE COMUNICA DOVE HA MESSO UN OGGETTO (es. "Ho messo il caricatore sul comodino"):
   - USA lo strumento `store_physical_item` per registrarlo subito nel caveau.

4. QUANDO L'UTENTE CHIEDE DELLE SCADENZE O COSA DEVE PAGARE:
   - USA lo strumento `get_upcoming_deadlines`.

5. QUANDO L'UTENTE CHIEDE DI ELIMINARE O CANCELLARE UN DOCUMENTO O UN OGGETTO (es. "elimina la bolletta", "cancella il passaporto", "elimina i documenti delle bollette"):
   - Usa SEMPRE `search_vault` per cercare i documenti o gli oggetti pertinenti nel caveau.
   - Se trovi l'elemento da eliminare, chiama `delete_vault_record` con `target_type`, `target_id` e `title` per attivare il pulsante di conferma interattivo.
   - Nel tuo messaggio di testo chiedi sempre conferma con cortesia: "⚠️ Sei sicuro di voler eliminare [Titolo/Oggetto] dal caveau?".
   - Se ci sono più elementi corrispondenti (es. più bollette), puoi elencare cosa hai trovato e predisporre l'eliminazione per guidare l'utente.

6. STILE DI RISPOSTA:
   - Rispondi sempre in italiano naturale, cortese, chiaro e conciso nello stile di una vera chat WhatsApp (puoi usare emoji pertinenti come 📄, 📍, 💡, ✅).
"""

def strip_tool_tags(text: str) -> str:
    """Rimuove qualsiasi tag <tool_call>...</tool_call> o residui XML di chiamata tool."""
    if not text:
        return ""
    cleaned = re.sub(r"<tool_call>.*?</tool_call>", "", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<function=.*?</function>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<parameter=.*?</parameter>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"</?(?:tool_call|function|parameter|arg_key|arg_value)[^>]*>", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()




def filter_relevant_documents(docs: Optional[List[dict]], assistant_text: str, user_text: str) -> Optional[List[dict]]:
    """Filtra i widget dei documenti inviati alla UI in modo che corrispondano solo a quelli pertinenti o citati."""
    if not docs:
        return None
    if len(docs) == 1:
        return docs

    asst_lower = assistant_text.lower() if assistant_text else ""
    user_lower = user_text.lower() if user_text else ""

    # 1. Verifica quali documenti sono esplicitamente citati nel testo della risposta dell'assistente
    mentioned = []
    for d in docs:
        title = (d.get("title") or "").strip().lower()
        issuer = (d.get("issuer") or "").strip().lower()
        title_words = [w for w in re.split(r"[^\w]+", title) if len(w) > 3 and w not in ITALIAN_STOPWORDS]
        title_match = (title and title in asst_lower) or (title_words and sum(1 for w in title_words if w in asst_lower) >= max(1, len(title_words) * 0.6))
        issuer_match = bool(issuer and len(issuer) > 3 and (issuer in asst_lower))
        if title_match or issuer_match:
            mentioned.append(d)

    if 0 < len(mentioned) < len(docs):
        return mentioned

    # 2. Se l'utente ha chiesto un singolo elemento ("il documento", "la bolletta", ecc.), restituisci solo il top match
    is_singular_request = any(
        re.search(rf"\b{w}\b", user_lower)
        for w in ["il", "lo", "la", "l'", "un", "uno", "una", "un'"]
    ) and not any(
        re.search(rf"\b{w}\b", user_lower)
        for w in ["i", "gli", "le", "tutti", "tutte", "elenco", "lista", "quali"]
    )
    if is_singular_request and len(docs) > 0:
        return [docs[0]]

    return docs[:3]


class AgenticChatService:
    def __init__(self):
        self.settings = get_settings()

    def execute_tool(self, name: str, args: Dict[str, Any], db: Session, thread_id: str = "general") -> Dict[str, Any]:
        """Esegue uno strumento registrato contro il database SQLite locale."""
        logger.info(f"Esecuzione tool {name} con argomenti: {args} (thread: {thread_id})")

        if name == "search_vault":
            query = (args.get("query") or "").strip()
            doc_results = search_vault_documents(db, query, thread_id=thread_id)
            item_results = search_vault_items(db, query, thread_id=thread_id)
            return {
                "query": query,
                "found_documents": doc_results[:5],
                "found_physical_items": item_results[:5]
            }


        elif name == "get_recent_vault_documents":
            limit = args.get("limit", 3)
            # Prioritize current thread if any, otherwise all
            docs = (
                db.query(Document)
                .order_by(Document.created_at.desc())
                .limit(limit)
                .all()
            )
            return {
                "recent_documents": [
                    {
                        "document_id": d.id,
                        "thread_id": d.thread_id,
                        "title": d.title,
                        "issuer": d.issuer,
                        "doc_type": d.doc_type,
                        "amount": d.amount,
                        "due_date": d.due_date.isoformat() if d.due_date else None,
                        "status": d.status,
                        "summary": d.summary,
                        "filename": Path(d.file_path).name,
                        "file_url": f"/uploads/{Path(d.file_path).name}",
                        "file_type": d.file_type
                    }
                    for d in docs
                ]
            }

        elif name == "store_physical_item":
            raw_name = args.get("item_name", "Oggetto").strip()
            cleaned_name = re.sub(r"^(il|lo|la|i|gli|le|l'|un|uno|una|un')\s*", "", raw_name, flags=re.IGNORECASE).strip()
            item_name = (cleaned_name if cleaned_name else raw_name).capitalize()
            prim_loc = args.get("primary_location", "Non specificato")
            det_loc = args.get("detailed_location")
            cat = args.get("category", "generico")

            existing = db.query(PhysicalItem).filter(PhysicalItem.item_name.ilike(item_name)).first()
            if existing:
                existing.primary_location = prim_loc
                if det_loc:
                    existing.detailed_location = det_loc
                existing.thread_id = thread_id
                item = existing
            else:
                item = PhysicalItem(
                    thread_id=thread_id,
                    item_name=item_name,
                    primary_location=prim_loc,
                    detailed_location=det_loc,
                    category=cat
                )
                db.add(item)
            db.commit()
            db.refresh(item)

            loc_str = item.primary_location + (f" ({item.detailed_location})" if item.detailed_location else "")
            return {
                "success": True,
                "item_id": item.id,
                "thread_id": item.thread_id,
                "message": f"Memorizzato con successo: '{item.item_name}' in {loc_str}"
            }

        elif name == "delete_vault_record":
            target_type = args.get("target_type", "document")
            target_id = args.get("target_id")
            title = args.get("title", "Elemento")

            details = ""
            if target_type == "physical_item":
                rec = db.query(PhysicalItem).filter(PhysicalItem.id == target_id).first()
                if rec:
                    details = f"Posizione: {rec.primary_location}" + (f" ({rec.detailed_location})" if rec.detailed_location else "")
            else:
                rec = db.query(Document).filter(Document.id == target_id).first()
                if rec:
                    details = rec.summary or rec.issuer or ""

            conf = {
                "type": "delete_confirmation",
                "target_type": target_type,
                "target_id": target_id,
                "title": title,
                "details": details
            }
            return {
                "confirmation": conf,
                "status": "pending_confirmation",
                "target_type": target_type,
                "target_id": target_id,
                "title": title
            }

        elif name == "get_upcoming_deadlines":
            docs = db.query(Document).filter(Document.status == "da_pagare").order_by(Document.due_date.asc().nulls_last()).all()
            return {
                "deadlines_count": len(docs),
                "deadlines": [
                    {
                        "document_id": d.id,
                        "title": d.title,
                        "issuer": d.issuer,
                        "amount": d.amount,
                        "due_date": d.due_date.isoformat() if d.due_date else None,
                        "summary": d.summary
                    }
                    for d in docs
                ]
            }

        return {"error": f"Strumento non riconosciuto: {name}"}

    def build_system_prompt(self, db: Session, thread_id: str = "general") -> str:
        """Costruisce il prompt di sistema iniettando la memoria attiva e il contesto del Caveau (RAG)."""
        docs = db.query(Document).order_by(Document.id.desc()).limit(4).all()
        items = db.query(PhysicalItem).order_by(PhysicalItem.id.desc()).limit(6).all()
        unpaid = db.query(Document).filter(Document.status == "da_pagare").all()

        vault_summary = ["\n[STATO ATTUALE E MEMORIA DEL CAVEAU]:"]
        if docs:
            vault_summary.append("Ultimi Documenti/File archiviati:")
            for d in docs:
                amt = f" ({d.amount:.2f} €)" if d.amount else ""
                due = f" scadenza {d.due_date}" if d.due_date else ""
                vault_summary.append(f"- ID {d.id}: '{d.title}' (emittente: {d.issuer or 'N/D'}, tipo: {d.doc_type}){amt}{due}\n  Sintesi: {d.summary[:250]}")
        else:
            vault_summary.append("Nessun documento registrato finora.")

        if items:
            vault_summary.append("\nUltimi Oggetti fisici memorizzati:")
            for it in items:
                loc = it.primary_location + (f" -> {it.detailed_location}" if it.detailed_location else "")
                vault_summary.append(f"- '{it.item_name}': {loc}")
        else:
            vault_summary.append("Nessun oggetto fisico memorizzato finora.")

        vault_summary.append(f"\nScadenze/bollette da pagare in sospeso: {len(unpaid)}")

        thread = db.query(ChatThread).filter(ChatThread.id == thread_id).first() if db else None
        if thread:
            m_list = []
            if thread.members:
                try:
                    m_list = json.loads(thread.members)
                except Exception:
                    m_list = [thread.members]
            m_str = ", ".join(m_list) if m_list else "Io"
            thread_type_str = "Gruppo con altre persone" if thread.thread_type == "group" else "Area Tematica / Categoria"
            vault_summary.append(
                f"\n[CANALE CHAT ATTIVO]:\n"
                f"- Nome chat: {thread.name}\n"
                f"- Tipologia: {thread_type_str}\n"
                f"- Membri partecipanti: {m_str}\n"
                f"- Descrizione: {thread.description or 'Generale'}\n"
                f"Adatta le tue risposte e la memorizzazione sapendo che ti trovi in questo canale."
            )

        vault_summary.append("\nIMPORTANTE: Se l'utente ti chiede 'di cosa parla il file che ti ho mandato?', 'che file è?', o cerca un documento/oggetto, consulta SUBITO la lista qui sopra o usa gli strumenti per rispondere in modo dettagliato!")

        return SYSTEM_PROMPT + "\n" + "\n".join(vault_summary)

    def _handle_deletion_intent(self, user_text: str, lower_t: str, db: Session, thread_id: str = "general") -> Optional[ChatResponse]:
        """Gestisce in modo sicuro le richieste di eliminazione chiedendo conferma prima di qualsiasi azione."""
        is_deletion = any(k in lower_t for k in [
            "elimina", "cancella", "rimuovi", "eliminarlo", "cancellarlo", 
            "rimuoverlo", "butta", "cancellami", "eliminami"
        ])
        if not is_deletion:
            return None

        # Estrai il testo di ricerca rimuovendo le parole di comando e filler
        target_query = re.sub(
            r"^(?:per favore|puoi|vorrei|potresti|ti prego di|elimina|cancella|rimuovi|cancellami|eliminami|butta)\s*(?:il|la|lo|le|i|l'|un|una|uno)?\s*",
            "", lower_t
        ).strip(" ?.")
        target_query = re.sub(
            r"^(?:documenti\s+delle|documenti\s+dei|documenti\s+di|documenti\s+del|documenti|documento\s+delle|documento\s+del|documento\s+di|documento|file\s+delle|file\s+di|file\s+del|file)\s*",
            "", target_query
        ).strip(" ?.")
        target_query = re.sub(r"\s*(?:dal caveau|dall'archivio|dal database|dalla memoria|dal sistema)$", "", target_query).strip()

        if not target_query or len(target_query) < 2:
            target_query = user_text

        search_res = self.execute_tool("search_vault", {"query": target_query}, db, thread_id=thread_id)
        f_docs = search_res.get("found_documents", [])
        f_items = search_res.get("found_physical_items", [])

        prefers_doc = any(k in lower_t for k in ["document", "file", "bollett", "f24", "certificat", "ricevut", "fattur", "pdf"])
        prefers_item = any(k in lower_t for k in ["oggett", "posizion", "posto", "chiav", "passaport", "patente"])

        chosen_doc = None
        chosen_item = None

        if prefers_doc and f_docs:
            chosen_doc = f_docs[0]
        elif prefers_item and f_items:
            chosen_item = f_items[0]
        elif f_docs and not f_items:
            chosen_doc = f_docs[0]
        elif f_items and not f_docs:
            chosen_item = f_items[0]
        elif f_docs and f_items:
            chosen_doc = f_docs[0] if not prefers_item else None
            chosen_item = f_items[0] if prefers_item else None

        if chosen_doc:
            conf = {
                "type": "delete_confirmation",
                "target_type": "document",
                "target_id": chosen_doc["document_id"],
                "title": chosen_doc["title"],
                "details": chosen_doc.get("summary") or chosen_doc.get("issuer")
            }
            return ChatResponse(
                reply=f"⚠️ Ho trovato il documento **{chosen_doc['title']}** ({chosen_doc.get('issuer', 'Documento')}).\nSei sicuro di volerlo eliminare dal caveau?",
                action="REQUEST_DELETE",
                data={"target_type": "document", "target_id": chosen_doc["document_id"]},
                confirmation=conf,
                documents=[chosen_doc]
            )
        elif chosen_item:
            loc_str = chosen_item["primary_location"] + (f" ({chosen_item['detailed_location']})" if chosen_item.get("detailed_location") else "")
            conf = {
                "type": "delete_confirmation",
                "target_type": "physical_item",
                "target_id": chosen_item["item_id"],
                "title": chosen_item["item_name"],
                "details": f"Posizione: {loc_str}"
            }
            return ChatResponse(
                reply=f"⚠️ Ho trovato l'oggetto **{chosen_item['item_name']}** (registrato in: {loc_str}).\nSei sicuro di voler eliminare questa posizione dal caveau?",
                action="REQUEST_DELETE",
                data={"target_type": "physical_item", "target_id": chosen_item["item_id"]},
                confirmation=conf
            )
        else:
            # Se non troviamo una corrispondenza diretta, lasciamo piena libertà all'AI di dialogare
            return None

    def run_turn(self, user_text: str, db: Session, thread_id: str = "general") -> ChatResponse:
        """Esegue un turno conversazionale con tool-calling dell'agente."""
        lower_t = user_text.lower()

        # Intercetta le richieste di eliminazione sicura
        del_resp = self._handle_deletion_intent(user_text, lower_t, db, thread_id=thread_id)
        if del_resp:
            return del_resp

        # Se non c'è chiave API, fallback deterministico
        if not self.settings.OPENROUTER_API_KEY:
            ai = MockAIService()
            intent = ai.classify_and_extract_intent(user_text)
            reply = ai.generate_conversational_reply(user_text)
            return ChatResponse(reply=reply, action="REPLY")

        # Recupera la cronologia recente con memoria e contesto attivo iniettato
        system_content = self.build_system_prompt(db, thread_id=thread_id)
        recent_msgs = (
            db.query(ChatMessage)
            .filter(ChatMessage.thread_id == thread_id)
            .order_by(ChatMessage.id.desc())
            .limit(8)
            .all()
        )
        history_messages: List[Dict[str, Any]] = [{"role": "system", "content": system_content}]
        for m in reversed(recent_msgs):
            if m.content != user_text:
                # Evita di contaminare il contesto con vecchi messaggi contenenti tag tool grezzi
                if "<tool_call>" in m.content or "<function=" in m.content:
                    continue
                history_messages.append({
                    "role": "assistant" if m.sender == "assistant" else "user",
                    "content": m.content
                })
        history_messages.append({"role": "user", "content": user_text})

        headers = {
            "Authorization": f"Bearer {self.settings.OPENROUTER_API_KEY.strip()}",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Dove lo AI messo",
            "Content-Type": "application/json"
        }

        tool_action = "REPLY"
        tool_data = None

        agent_model = get_app_setting(db, "ai_model", default=self.settings.OPENROUTER_MODEL) or "google/gemini-2.5-flash-lite"

        try:
            r1 = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json={
                    "model": agent_model,
                    "messages": history_messages,
                    "tools": TOOLS_DEFINITION,
                    "tool_choice": "auto",
                    "max_tokens": 1500,
                    "temperature": 0.2
                },
                timeout=30.0
            )

            if r1.status_code == 200:
                data1 = r1.json()
                msg1 = data1.get("choices", [{}])[0].get("message", {})
                tool_calls = msg1.get("tool_calls")

                if tool_calls:
                    history_messages.append(msg1)
                    
                    for tc in tool_calls:
                        func_name = tc.get("function", {}).get("name")
                        try:
                            raw_args = tc.get("function", {}).get("arguments", "{}")
                            func_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        except Exception:
                            func_args = {}

                        tool_output = self.execute_tool(func_name, func_args, db=db, thread_id=thread_id)
                        tool_action = func_name
                        tool_data = tool_output

                        history_messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id"),
                            "content": json.dumps(tool_output, ensure_ascii=False)
                        })

                    r2 = httpx.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers=headers,
                        json={
                            "model": agent_model,
                            "messages": history_messages,
                            "max_tokens": 1500,
                            "temperature": 0.3
                        },
                        timeout=30.0
                    )
                    if r2.status_code == 200:
                        final_msg = r2.json().get("choices", [{}])[0].get("message", {})
                        final_text = (final_msg.get("content") or "").strip()
                        final_text = strip_tool_tags(final_text)

                        docs_found = None
                        if isinstance(tool_data, dict):
                            docs_found = tool_data.get("found_documents") or tool_data.get("recent_documents")

                        if not final_text:
                            if tool_action == "search_vault":
                                if docs_found:
                                    d = docs_found[0]
                                    final_text = f"📄 Ho trovato: **{d['title']}**\n💡 {d['summary']}"
                                else:
                                    final_text = "Ho cercato nel caveau ma non ho trovato documenti corrispondenti."
                            elif tool_action == "get_upcoming_deadlines":
                                up = (tool_data or {}).get("upcoming_documents", [])
                                if up:
                                    lines = [f"- 📄 **{d['title']}**: {d.get('amount', '?')} € (scad. {d.get('due_date', '?')})" for d in up[:5]]
                                    final_text = "📅 Ecco le tue scadenze in sospeso:\n\n" + "\n".join(lines)
                                else:
                                    final_text = "✅ Non ci sono scadenze o pagamenti in sospeso al momento."
                            elif tool_action == "store_physical_item":
                                final_text = "✅ Posizione salvata con successo nel caveau!"
                            else:
                                final_text = "Operazione completata con successo nel caveau."
                        else:
                            if tool_action == "store_physical_item" and "Memorizzato" not in final_text and "salvat" not in final_text.lower():
                                final_text = f"✅ Memorizzato! {final_text}"

                        filtered_docs = filter_relevant_documents(docs_found, final_text, user_text)
                        conf_box = None
                        if isinstance(tool_data, dict) and "confirmation" in tool_data:
                            conf_box = tool_data["confirmation"]
                            tool_action = "REQUEST_DELETE"

                        return ChatResponse(reply=final_text, action=tool_action, data=tool_data, documents=filtered_docs, confirmation=conf_box)
                
                direct_reply = (msg1.get("content") or "").strip()
                lower_t = user_text.lower()
                
                # 0. Intercetta ed esegue tag di tool-call emessi come testo dal modello (es. <tool_call>...)
                tc_match = re.search(r"<tool_call>\s*(.*?)\s*</tool_call>", direct_reply, re.DOTALL | re.IGNORECASE)
                if tc_match:
                    raw_tc = tc_match.group(1).strip()
                    logger.info(f"Intercettata chiamata di tool nel testo del modello: {raw_tc}")
                    
                    # Prova ad estrarre il nome del tool e la query dall'XML testuale
                    tool_name_m = re.search(r"(\w+)\s*\n|^(\w+)\s", raw_tc)
                    arg_val_m = re.search(r"<arg_value>(.*?)</arg_value>", raw_tc, re.DOTALL)
                    extracted_query = (arg_val_m.group(1).strip() if arg_val_m else "").lower() or re.sub(r"<[^>]+>", "", raw_tc).strip()

                    is_store_tc = "store_physical_item" in raw_tc or (any(k in lower_t for k in ["messo", "riposto", "salvato", "lasciato", "conservato"]) and not any(k in lower_t for k in ["dov'è", "dov'e", "dove"]))
                    if is_store_tc:
                        m = re.search(r"(?:messo|riposto|salvato|lasciato|conservato)\s+(?:il\s+|la\s+|le\s+|i\s+|l\')?(.+?)\s+(?:nel|nella|in|su|sul|sotto|a)\s+(.+)", lower_t)
                        item = m.group(1).strip() if m else "Oggetto"
                        loc = m.group(2).strip() if m else "posto specificato"
                        db_res = self.execute_tool("store_physical_item", {"item_name": item, "primary_location": loc}, db, thread_id=thread_id)
                        return ChatResponse(reply=f"✅ Memorizzato! Ho salvato la posizione di '{item}' in: {loc}.", action="store_physical_item", data=db_res)

                    # Per tutti gli altri tool call testuali (search_vault, get_upcoming_deadlines, ecc.)
                    # esegui la ricerca più appropriata in base al contenuto
                    if "get_upcoming_deadlines" in raw_tc:
                        t_out = self.execute_tool("get_upcoming_deadlines", {}, db, thread_id=thread_id)
                        docs = t_out.get("upcoming_documents", [])
                        if docs:
                            lines = [f"- 📄 **{d['title']}** — {d.get('amount','?')} € scad. {d.get('due_date','?')}" for d in docs[:5]]
                            return ChatResponse(reply="📅 Ecco le tue scadenze in sospeso:\n\n" + "\n".join(lines), action="get_upcoming_deadlines", data=t_out, documents=docs)

                    # search_vault o qualsiasi altro caso: cerca col termine estratto o con il testo utente
                    search_q = extracted_query or re.sub(r"^(?:cerca|trovami|trova|dov'è|dov'e|dove|quant'è|quanto)\s*", "", lower_t).strip(" ?.")
                    t_out = self.execute_tool("search_vault", {"query": search_q or user_text}, db, thread_id=thread_id)
                    docs = t_out.get("found_documents", [])
                    items_found = t_out.get("found_physical_items", [])
                    if docs:
                        d = docs[0]
                        filtered_d = filter_relevant_documents(docs, d['title'], user_text) or [d]
                        return ChatResponse(
                            reply=f"📄 Ho trovato il documento '{d['title']}':\n💡 {d['summary']}",
                            action="search_vault",
                            data=t_out,
                            documents=filtered_d
                        )
                    if items_found:
                        it = items_found[0]
                        loc = it['primary_location'] + (f" ({it['detailed_location']})" if it['detailed_location'] else "")
                        return ChatResponse(reply=f"📍 Il tuo {it['item_name']} si trova in: {loc}.", action="search_vault", data=t_out)

                    t_out2 = self.execute_tool("get_recent_vault_documents", {"limit": 3}, db, thread_id=thread_id)
                    docs2 = t_out2.get("recent_documents", [])
                    if docs2:
                        lines = [f"📄 **{d['title']}** ({d['doc_type']})\n💡 {d['summary']}" for d in docs2[:2]]
                        return ChatResponse(
                            reply="Ho trovato nel tuo archivio documenti:\n\n" + "\n\n".join(lines),
                            action="search_vault",
                            data=t_out2,
                            documents=docs2
                        )

                # Pulisci sempre il testo diretto prima di usarlo (rimuove eventuali tag residui)
                direct_reply = strip_tool_tags(direct_reply)

                if direct_reply:
                    # Se il modello ha risposto direttamente senza tool_calls (es. usando la cronologia chat),
                    # ma l'utente chiedeva un documento o la risposta ne cita uno, recuperiamo e alleghiamo il widget del file!
                    is_doc_intent = any(k in lower_t for k in [
                        "document", "file", "mutuo", "bollett", "fattur", "contratt", "certificat",
                        "f24", "ricevut", "cedolin", "busta paga", "patente", "carta", "estratto"
                    ]) or any(k in direct_reply.lower() for k in [
                        "documento:", "estratto conto", "bolletta", "fattura", "certificato", "allegato"
                    ])

                    fallback_docs = None
                    s_res = None
                    if is_doc_intent:
                        s_res = self.execute_tool("search_vault", {"query": user_text}, db=db, thread_id=thread_id)
                        f_docs = s_res.get("found_documents", [])
                        if f_docs:
                            fallback_docs = filter_relevant_documents(f_docs, direct_reply, user_text) or [f_docs[0]]

                    return ChatResponse(
                        reply=direct_reply,
                        action="search_vault" if fallback_docs else "REPLY",
                        data=s_res if fallback_docs else None,
                        documents=fallback_docs
                    )

        except Exception as e:
            logger.error(f"Errore Agentic loop: {e}")
            return ChatResponse(
                reply="Mi dispiace, si è verificato un errore di connessione con il motore AI. Riprova tra qualche istante!",
                action="REPLY"
            )

        return ChatResponse(
            reply="Non sono riuscito a elaborare la richiesta. Puoi chiedermi dove si trova un oggetto, cercare un documento o verificare le scadenze!",
            action="REPLY"
        )
