import json
import logging
import re
import httpx
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.config import get_settings
from app.models.database import Document, PhysicalItem, ChatMessage
from app.models.schemas import ChatResponse
from app.services.ai_service import get_ai_service, MockAIService

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
    }
]

SYSTEM_PROMPT = """Sei l'assistente AI per WhatsApp di 'Dove lo AI messo', un caveau intelligente per famiglie e professionisti italiani.
Hai accesso ad appositi STRUMENTI (tools) per interagire con il database SQLite del caveau.

REGOLE FERREE:
1. QUANDO L'UTENTE CHIEDE DI UN FILE O DOCUMENTO (es. "che file è?", "cos'ho appena caricato?", "trovami il certificato del tolc", "cerca la bolletta enel"):
   - DEVI SUBITO USARE `get_recent_vault_documents` oppure `search_vault`!
   - NON dire MAI che non hai trovato nulla o che è un oggetto fisico senza aver prima interrogato il database dei documenti!
   - Spiega con precisione e ricchezza di dettagli tutti i dati trovati (titolo, emittente, intestatario, voti/punteggi, importi e date).

2. QUANDO L'UTENTE CHIEDE DOVE SI TROVA UN OGGETTO (es. "dov'è il passaporto?", "dove ho messo le chiavi?"):
   - USA lo strumento `search_vault` per cercarlo tra gli oggetti fisici e i documenti.
   - Se lo trovi, indica la stanza e il mobile esatti. Se non lo trovi dopo la ricerca, invitalo gentilmente a memorizzarlo.

3. QUANDO L'UTENTE COMUNICA DOVE HA MESSO UN OGGETTO (es. "Ho messo il caricatore sul comodino"):
   - USA lo strumento `store_physical_item` per registrarlo subito nel caveau.

4. QUANDO L'UTENTE CHIEDE DELLE SCADENZE O COSA DEVE PAGARE:
   - USA lo strumento `get_upcoming_deadlines`.

5. STILE DI RISPOSTA:
   - Rispondi sempre in italiano naturale, cortese, chiaro e conciso nello stile di una vera chat WhatsApp (puoi usare emoji pertinenti come 📄, 📍, 💡, ✅).
"""

class AgenticChatService:
    def __init__(self):
        self.settings = get_settings()

    def execute_tool(self, name: str, args: Dict[str, Any], db: Session) -> Dict[str, Any]:
        """Esegue uno strumento registrato contro il database SQLite locale."""
        logger.info(f"Esecuzione tool {name} con argomenti: {args}")

        if name == "search_vault":
            query = (args.get("query") or "").strip()
            italian_stopwords = {
                "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "un'",
                "del", "dello", "della", "dei", "degli", "delle", "al", "allo", "alla", "ai", "agli", "alle",
                "dal", "dallo", "dalla", "dai", "dagli", "dalle", "nel", "nello", "nella", "nei", "negli", "nelle",
                "sul", "sullo", "sulla", "sui", "sugli", "sulle", "per", "con", "tra", "fra",
                "che", "chi", "cosa", "come", "dove", "quando", "trova", "trovami", "cerca", "dov'è", "file", "documento"
            }
            tokens = [t.lower() for t in re.split(r"[^\w]+", query) if len(t) > 2 and t.lower() not in italian_stopwords]
            if not tokens and query:
                tokens = [t.lower() for t in re.split(r"[^\w]+", query) if len(t) > 1]
            
            # 1. Ricerca tra i Documenti
            all_docs = db.query(Document).order_by(Document.created_at.desc()).all()
            doc_scored = []
            for d in all_docs:
                text_blob = f"{d.title} {d.issuer or ''} {d.doc_type} {d.summary} {d.file_path}".lower()
                score = 0
                if query.lower() in text_blob:
                    score += 50
                for t in tokens:
                    if t in text_blob:
                        score += 10
                if score > 0:
                    doc_scored.append((score, {
                        "document_id": d.id,
                        "title": d.title,
                        "issuer": d.issuer,
                        "doc_type": d.doc_type,
                        "amount": d.amount,
                        "due_date": d.due_date.isoformat() if d.due_date else None,
                        "status": d.status,
                        "summary": d.summary,
                        "filename": d.file_path.split("\\")[-1].split("/")[-1]
                    }))

            doc_scored.sort(key=lambda x: x[0], reverse=True)
            doc_results = [item[1] for item in doc_scored]

            # 2. Ricerca tra gli Oggetti Fisici
            all_items = db.query(PhysicalItem).order_by(PhysicalItem.updated_at.desc()).all()
            item_scored = []
            for it in all_items:
                text_blob = f"{it.item_name} {it.primary_location} {it.detailed_location or ''} {it.notes or ''}".lower()
                score = 0
                if query.lower() in text_blob:
                    score += 50
                for t in tokens:
                    if t in text_blob:
                        score += 10
                if score > 0:
                    item_scored.append((score, {
                        "item_id": it.id,
                        "item_name": it.item_name,
                        "primary_location": it.primary_location,
                        "detailed_location": it.detailed_location,
                        "category": it.category
                    }))

            item_scored.sort(key=lambda x: x[0], reverse=True)
            item_results = [item[1] for item in item_scored]

            return {
                "query": query,
                "found_documents": doc_results[:5],
                "found_physical_items": item_results[:5]
            }

        elif name == "get_recent_vault_documents":
            limit = args.get("limit", 3)
            recent_docs = db.query(Document).order_by(Document.created_at.desc()).limit(limit).all()
            return {
                "recent_documents": [
                    {
                        "document_id": d.id,
                        "title": d.title,
                        "issuer": d.issuer,
                        "doc_type": d.doc_type,
                        "amount": d.amount,
                        "due_date": d.due_date.isoformat() if d.due_date else None,
                        "status": d.status,
                        "summary": d.summary,
                        "filename": d.file_path.split("\\")[-1].split("/")[-1]
                    }
                    for d in recent_docs
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
                item = existing
            else:
                item = PhysicalItem(
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
                "message": f"Memorizzato con successo: '{item.item_name}' in {loc_str}"
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

    def build_system_prompt(self, db: Session) -> str:
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
        vault_summary.append("\nIMPORTANTE: Se l'utente ti chiede 'di cosa parla il file che ti ho mandato?', 'che file è?', o cerca un documento/oggetto, consulta SUBITO la lista qui sopra o usa gli strumenti per rispondere in modo dettagliato!")

        return SYSTEM_PROMPT + "\n" + "\n".join(vault_summary)

    def run_turn(self, user_text: str, db: Session) -> ChatResponse:
        """Esegue un turno conversazionale con tool-calling dell'agente."""
        # Se non c'è chiave API, fallback deterministico
        if not self.settings.OPENROUTER_API_KEY:
            ai = MockAIService()
            intent = ai.classify_and_extract_intent(user_text)
            reply = ai.generate_conversational_reply(user_text)
            return ChatResponse(reply=reply, action="REPLY")

        # Recupera la cronologia recente con memoria e contesto attivo iniettato
        system_content = self.build_system_prompt(db)
        recent_msgs = db.query(ChatMessage).order_by(ChatMessage.id.desc()).limit(8).all()
        history_messages: List[Dict[str, Any]] = [{"role": "system", "content": system_content}]
        for m in reversed(recent_msgs):
            if m.content != user_text:
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

        agent_model = self.settings.OPENROUTER_MODEL or "inclusionai/ling-3.0-flash-vl:free"

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

                        tool_output = self.execute_tool(func_name, func_args, db=db)
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
                        if final_text:
                            if tool_action == "store_physical_item" and "Memorizzato" not in final_text:
                                final_text = f"✅ Memorizzato! {final_text}"
                            return ChatResponse(reply=final_text, action=tool_action, data=tool_data)
                
                direct_reply = (msg1.get("content") or "").strip()
                lower_t = user_text.lower()
                
                # 0. Intercetta ed esegue tag di tool-call emessi come testo dal modello (es. <tool_call>...)
                tc_match = re.search(r"<tool_call>\s*(.*?)\s*</tool_call>", direct_reply, re.DOTALL | re.IGNORECASE)
                if tc_match:
                    raw_tc = tc_match.group(1).strip()
                    logger.info(f"Intercettata chiamata di tool nel testo del modello: {raw_tc}")
                    if "search_vault" in raw_tc or any(k in lower_t for k in ["cerca", "trova", "graduatori", "tolc", "passaporto"]):
                        q_term = re.sub(r"^(?:cerca|trovami|trova|dov'è|dov'e|dove)\s*", "", lower_t).strip(" ?.")
                        t_out = self.execute_tool("search_vault", {"query": q_term or user_text}, db)
                        docs = t_out.get("found_documents", [])
                        items = t_out.get("found_physical_items", [])
                        if docs:
                            d = docs[0]
                            return ChatResponse(
                                reply=f"📄 Ho trovato il documento '{d['title']}':\n💡 {d['summary']}",
                                action="search_vault",
                                data=t_out
                            )
                        if items:
                            it = items[0]
                            loc = it['primary_location'] + (f" ({it['detailed_location']})" if it['detailed_location'] else "")
                            return ChatResponse(
                                reply=f"📍 Il tuo {it['item_name']} si trova in: {loc}.",
                                action="search_vault",
                                data=t_out
                            )
                    
                    t_out = self.execute_tool("get_recent_vault_documents", {"limit": 3}, db)
                    docs = t_out.get("recent_documents", [])
                    if docs:
                        lines = [f"📄 **{d['title']}** ({d['doc_type']})\n💡 {d['summary']}" for d in docs[:2]]
                        return ChatResponse(
                            reply="Ho trovato nel tuo archivio documenti:\n\n" + "\n\n".join(lines),
                            action="search_vault",
                            data=t_out
                        )

                # 0.5 Se l'utente chiede del file appena mandato / caricato o cosa dice un file
                if any(k in lower_t for k in ["cosa parla", "cosa dice", "cosa c'è", "cosa ce", "cosa contiene", "appena mandato", "ho mandato", "appena caricato", "ho caricato", "ultimo file", "ultimo documento"]):
                    latest_doc = db.query(Document).order_by(Document.id.desc()).first()
                    if latest_doc:
                        return ChatResponse(
                            reply=f"📄 **{latest_doc.title}** ({latest_doc.issuer or 'Documento recente'})\n\n💡 {latest_doc.summary}",
                            action="search_vault",
                            data={"document_id": latest_doc.id, "title": latest_doc.title}
                        )

                # 1. Se l'utente fa una DOMANDA (cerca qualcosa, chiede dove si trova o info su un file)
                is_query = any(k in lower_t for k in ["dov'è", "dov'e", "dove", "trovami", "trova", "cerca", "qual è", "che file", "che documento", "cos'è", "spiegami", "graduatori"])
                if is_query:
                    query_clean = re.sub(r"^(?:dov'è|dov'e|dove ho messo|dove si trova|dove sono|dove|trovami|trova|cerca|che file è|che file e|che file|che documento è|che documento|cos'è il file|cos'è|spiegami il file|spiegami)\s*", "", lower_t).strip(" ?.")
                    if len(query_clean) >= 2:
                        found = self.execute_tool("search_vault", {"query": query_clean}, db)
                        docs = found.get("found_documents", [])
                        items = found.get("found_physical_items", [])
                        if docs:
                            d = docs[0]
                            return ChatResponse(
                                reply=f"📄 Ho trovato il documento '{d['title']}':\n💡 {d['summary']}",
                                action="search_vault",
                                data=found
                            )
                        if items:
                            it = items[0]
                            loc = it['primary_location'] + (f" ({it['detailed_location']})" if it['detailed_location'] else "")
                            return ChatResponse(
                                reply=f"📍 Il tuo {it['item_name']} si trova in: {loc}.",
                                action="search_vault",
                                data=found
                            )
                        return ChatResponse(
                            reply=f"Non ho trovato '{query_clean}' nel tuo caveau. Se vuoi salvarlo, dimmi pure dove l'hai riposto o carica il file!",
                            action="search_vault"
                        )
                    else:
                        recent = self.execute_tool("get_recent_vault_documents", {"limit": 3}, db)
                        docs = recent.get("recent_documents", [])
                        if docs:
                            lines = [f"📄 **{d['title']}** ({d['doc_type']})\n💡 {d['summary']}" for d in docs[:2]]
                            return ChatResponse(
                                reply="Ho trovato nel tuo archivio documenti:\n\n" + "\n\n".join(lines),
                                action="search_vault",
                                data=recent
                            )

                # 2. Se l'utente comunica che ha memorizzato o riposto qualcosa
                if any(k in lower_t for k in ["messo", "riposto", "salvato", "lasciato"]):
                    m = re.search(r"(?:messo|riposto|salvato|lasciato)\s+(?:il\s+|la\s+|le\s+|i\s+|l\')?(.+?)\s+(?:nel|nella|in|su|sul|sotto)\s+(.+)", lower_t)
                    item = m.group(1).strip() if m else "Oggetto"
                    loc = m.group(2).strip() if m else "posto specificato"
                    db_res = self.execute_tool("store_physical_item", {"item_name": item, "primary_location": loc}, db)
                    final_reply = direct_reply if ("Memorizzato" in direct_reply) else f"✅ Memorizzato! {direct_reply or f'Ho salvato la posizione di {item} in {loc}.'}"
                    return ChatResponse(reply=final_reply, action="store_physical_item", data=db_res)

                if direct_reply:
                    return ChatResponse(reply=direct_reply, action="REPLY")

        except Exception as e:
            logger.error(f"Errore Agentic loop: {e}")

        # Safety-net euristico deterministico se la rete è lenta o non chiama il tool
        lower_t = user_text.lower()
        is_query = any(k in lower_t for k in ["dov'è", "dov'e", "dove", "trovami", "trova", "cerca", "qual è", "che file", "che documento", "cos'è", "spiegami"])
        if is_query:
            query_clean = re.sub(r"^(?:dov'è|dov'e|dove ho messo|dove si trova|dove sono|dove|trovami|trova|cerca|che file è|che file e|che file|che documento è|che documento|cos'è il file|cos'è|spiegami il file|spiegami)\s*", "", lower_t).strip(" ?.")
            if len(query_clean) >= 2:
                found = self.execute_tool("search_vault", {"query": query_clean}, db)
                docs = found.get("found_documents", [])
                items = found.get("found_physical_items", [])
                if docs:
                    return ChatResponse(
                        reply=f"📄 Ho trovato il documento '{docs[0]['title']}':\n💡 {docs[0]['summary']}",
                        action="search_vault",
                        data=found
                    )
                if items:
                    loc = items[0]['primary_location'] + (f" ({items[0]['detailed_location']})" if items[0]['detailed_location'] else "")
                    return ChatResponse(
                        reply=f"📍 Il tuo {items[0]['item_name']} si trova in: {loc}.",
                        action="search_vault",
                        data=found
                    )
            recent = self.execute_tool("get_recent_vault_documents", {"limit": 3}, db)
            docs = recent.get("recent_documents", [])
            if docs:
                lines = [f"📄 **{d['title']}** ({d['doc_type']})\n💡 {d['summary']}" for d in docs[:2]]
                return ChatResponse(
                    reply="Ho trovato nel tuo archivio documenti:\n\n" + "\n\n".join(lines),
                    action="search_vault",
                    data=recent
                )

        if "messo" in lower_t or "riposto" in lower_t:
            m = re.search(r"(?:messo|riposto|salvato)\s+(?:il\s+|la\s+|le\s+|i\s+|l\')?(.+?)\s+(?:nel|nella|in|su|sul|sotto)\s+(.+)", lower_t)
            item = m.group(1).strip() if m else "Oggetto"
            loc = m.group(2).strip() if m else "posto specificato"
            res = self.execute_tool("store_physical_item", {"item_name": item, "primary_location": loc}, db)
            return ChatResponse(
                reply=f"✅ Memorizzato! Ho salvato la posizione di '{item}': {loc}.",
                action="store_physical_item",
                data=res
            )
            res = self.execute_tool("store_physical_item", {"item_name": item, "primary_location": loc}, db)
            return ChatResponse(
                reply=f"✅ Memorizzato! Ho salvato la posizione di '{item}': {loc}.",
                action="store_physical_item",
                data=res
            )

        if any(k in lower_t for k in ["dov'è", "dove ho", "dove si trova", "dove sono", "trovami", "cerca"]):
            query_clean = re.sub(r".*?(dov'è|dove ho messo|dove si trova|dove sono|trovami|cerca)\s+", "", lower_t).strip(" ?.")
            found = self.execute_tool("search_vault", {"query": query_clean}, db)
            docs = found.get("found_documents", [])
            items = found.get("found_physical_items", [])
            if docs:
                return ChatResponse(
                    reply=f"📄 Ho trovato il documento '{docs[0]['title']}': {docs[0]['summary']}",
                    action="search_vault",
                    data=found
                )
            if items:
                loc = items[0]['primary_location'] + (f" ({items[0]['detailed_location']})" if items[0]['detailed_location'] else "")
                return ChatResponse(
                    reply=f"📍 Il tuo {items[0]['item_name']} si trova in: {loc}.",
                    action="search_vault",
                    data=found
                )
            return ChatResponse(
                reply=f"Non ho trovato dove si trova '{query_clean}' nel tuo caveau. Se vuoi salvarlo, dimmi pure dove l'hai riposto!",
                action="search_vault"
            )

        return ChatResponse(
            reply="Ciao! Sono il tuo assistente per 'Dove lo AI messo'. Puoi chiedermi dove hai riposto un oggetto, cercare documenti e certificati, o verificare le tue scadenze.",
            action="GENERAL"
        )
