import json
import logging
import re
from datetime import datetime, date, timedelta
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


TOOLS_DEFINITION = [
    {
        "type": "function",
        "function": {
            "name": "search_vault",
            "description": (
                "Cerca nel caveau qualsiasi informazione: sia file e documenti archiviati (es. certificati, tolc, bollette, contratti, f24) "
                "sia posizioni fisiche di oggetti memorizzati (es. chiavi, passaporto, caricatore, tenda, occhiali, faldoni). "
                "DEVI SEMPRE chiamare questo strumento quando l'utente chiede dove si trova qualcosa (es. 'dov'è la tenda?', 'dove ho messo il passaporto?')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "La parola chiave o il nome dell'oggetto/documento da cercare (es. 'tenda da campeggio', 'passaporto', 'bolletta', 'scrivania')"
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
            "description": (
                "Memorizza, aggiorna, sposta o modifica la posizione fisica di un oggetto o documento cartaceo/fisico nel caveau "
                "(es. 'Ho messo la patente nel cassetto', 'Modifica la posizione della tenda da campeggio e mettila in soggiorno', "
                "'Sposta le chiavi all'ingresso', 'Metti il passaporto nella scrivania', 'Ora la tenda è in soggiorno'). "
                "DEVI chiamarlo SEMPRE per aggiornare il database SQLite quando l'utente comunica dove si trova o dove sposta un oggetto."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {"type": "string", "description": "Nome dell'oggetto (es. 'Tenda da campeggio', 'Passaporto', 'Patente', 'Chiavi di scorta')"},
                    "primary_location": {"type": "string", "description": "Nuova stanza o ambiente principale (es. 'Soggiorno', 'Garage', 'Studio', 'Cucina', 'Camera')"},
                    "detailed_location": {"type": "string", "description": "Dettaglio specifico opzionale del mobile o ripiano (es. 'Primo cassetto scrivania', 'Mensola')"},
                    "category": {"type": "string", "description": "Categoria opzionale dell'oggetto"}
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
            "name": "get_current_date",
            "description": "Fornisce la data, l'ora, il giorno della settimana e l'anno corrente (es. 'che giorno è oggi?', 'quanti ne abbiamo?', 'che data è?'). Utilissimo per verificare le scadenze e sapere quanti giorni mancano.",
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
    },
    {
        "type": "function",
        "function": {
            "name": "list_vault_contents",
            "description": "Recupera l'elenco completo o filtrato di tutti i documenti o di tutti gli oggetti fisici memorizzati nel caveau per il canale attivo. Usalo SEMPRE quando l'utente chiede la lista, l'elenco, o cosa c'è salvato (es. 'fai la lista di tutti i documenti', 'fai la lista di tutti gli oggetti', 'cosa c'è nel caveau?', 'mostrami tutti i file', 'elenco documenti', 'elenco oggetti').",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_type": {
                        "type": "string",
                        "enum": ["all", "documents", "physical_items"],
                        "description": "Specifica cosa recuperare: 'documents' per documenti/file, 'physical_items' per soli oggetti fisici, 'all' per entrambi."
                    }
                },
                "required": ["target_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rename_vault_document",
            "description": (
                "Rinomina un documento o file/foto salvato nel caveau, assegnandogli un nuovo titolo personalizzato scelto dall'utente "
                "(es. 'chiamalo Base Volante Fanatec', 'rinomina l'ultimo file in Ricevuta Dentista', 'salvalo come Certificato Medico'). "
                "Usalo SEMPRE quando l'utente specifica o cambia il nome di un file o foto."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "new_title": {
                        "type": "string",
                        "description": "Il nuovo titolo/nome da assegnare al documento o foto (es. 'Base Volante Fanatec', 'Ricevuta Dentista')"
                    },
                    "document_id": {
                        "type": "integer",
                        "description": "ID numerico opzionale del documento da rinominare. Se non fornito, fa riferimento all'ultimo documento caricato nel canale."
                    }
                },
                "required": ["new_title"]
            }
        }
    }
]

SYSTEM_PROMPT = """Sei l'assistente AI per WhatsApp di 'Dove lo AI messo', un caveau intelligente per famiglie e professionisti italiani.
Il tuo compito primario e la tua missione è AIUTARE GLI UTENTI:
- Quando gli utenti cercano documenti (es. Modello 730, F24, bollette luce/gas, contratti di affitto o lavoro, ricevute sanitarie, certificati scolastici o universitari, estratti conto), il tuo dovere fondamentale è aiutarli a trovarli immediatamente nel caveau, spiegare con chiarezza tutti i dati salienti (importi, scadenze, mittenti) e metterli in condizione di visualizzarli e scaricarli facilmente sul proprio dispositivo.
- Quando cercano oggetti fisici (es. passaporto, chiavi di casa o dell'auto, occhiali, caricabatterie), aiutali ricordando con esattezza la stanza, il mobile o il cassetto in cui sono conservati.
- Quando chiedono scadenze o pagamenti in sospeso, aiutali a monitorare i tributi e le bollette da pagare per evitare ritardi.
- Quando comunicano dove hanno riposto un oggetto o ne spostano/modificano la posizione, memorizzane subito la posizione con precisione nel caveau.
- Quando indicano come chiamare o rinominare un file/foto appena caricato (es. 'chiamalo Base Volante'), rinominalo subito con precisione nel caveau.
Hai accesso ad appositi STRUMENTI (tools) per interagire con il database SQLite del caveau. Hai piena autonomia e intelligenza per comprendere e soddisfare le richieste dell'utente in linguaggio naturale.

REGOLE FERREE:
0. PRIMATO ASSOLUTO DEL DATABASE SULLA CHAT (DATI REALI > CONTESTO):
   - Hai a disposizione l'intera cronologia della conversazione e l'inventario in tempo reale del database: usali per avere la massima consapevolezza del contesto, ricordare preferenze, richieste pregresse, spiegazioni e dettagli scambiati.
   - Tuttavia, per quanto riguarda l'ESISTENZA e la POSIZIONE ATTUALE di un documento o di un oggetto nel caveau, la sola e unica fonte di verità sono i DATI REALI DEL DATABASE SQLite (presenti nella sezione [STATO ATTUALE DEL DATABASE SQLITE] o verificati in tempo reale tramite i tuoi strumenti `search_vault`, `list_vault_contents`, `get_upcoming_deadlines`, `store_physical_item`, `rename_vault_document`).
   - Se un oggetto o un documento era stato citato nella conversazione ma NON è presente nei dati del database SQLite (o lo strumento restituisce che non c'è), significa che è stato rimosso o non è archiviato nel caveau. In tal caso, rispondi chiaramente che non è presente nel caveau, senza dare per scontato che esista solo perché citato in passato.
   - Basa sempre le tue affermazioni fattuali sui dati certi del database!

1. QUANDO L'UTENTE CHIEDE DI UN FILE O DOCUMENTO (es. "dammi 730", "dammi il documento del mutuo", "mostrami la bolletta", "che file è?", "trovami il certificato del tolc", "cerca la bolletta enel"):
   - DEVI SEMPRE USARE lo strumento `search_vault`!
   - NON rispondere MAI a memoria senza chiamare `search_vault`, perché la chiamata di `search_vault` è INDISPENSABILE per consentire al sistema di mostrare il widget grafico del documento (con anteprima e pulsante "Vedi") all'utente!
   - DIVIETO ASSOLUTO DI CHIEDERE IL PERMESSO: Non chiedere MAI "Posso mostrarti il documento?", "Vuoi che te lo mostri?", "Desideri vederlo?", "Quale dei due desideri visualizzare?". L'utente te lo ha già chiesto! Mostra e riassumi subito le informazioni trovate, l'interfaccia allegherà automaticamente la scheda grafica con il tasto "Vedi" per aprirlo!
   - Se l'utente ti risponde "sì", "ok", "mostramelo" o simili, fa riferimento all'ultimo documento di cui stavate parlando: chiama subito `search_vault` per quel documento senza MAI chiedere "cosa devo cercare?"!
   - Spiega con precisione e ricchezza di dettagli tutti i dati trovati (titolo, emittente, intestatario, voti/punteggi, importi e date).

2. QUANDO L'UTENTE CHIEDE DOVE SI TROVA UN OGGETTO O UN DOCUMENTO (es. "dov'è il passaporto?", "dove è la tenda da campeggio?", "dove ho messo le chiavi?"):
   - DIVIETO ASSOLUTO DI RISPONDERE A MEMORIA O DALLA CHAT: DEVI SEMPRE USARE lo strumento `search_vault`!
   - Non fare MAI affidamento sui messaggi precedenti della chat: la sola e unica verità è ciò che restituisce `search_vault` dal database in tempo reale! Se l'oggetto è stato eliminato o spostato, la cronologia precedente è obsoleta. Se `search_vault` non trova l'oggetto, rispondi con chiarezza che non è presente nel caveau (o che è stato rimosso) senza inventare posizioni passate!

3. QUANDO L'UTENTE COMUNICA, MODIFICA, SPOSTA O AGGIORNA LA POSIZIONE DI UN OGGETTO (es. "Ho messo il caricatore sul comodino", "Modifica la posizione della tenda da campeggio e mettila in soggiorno", "Sposta le chiavi in cucina", "Metti la tenda in soggiorno", "Ora il passaporto si trova nello studio"):
   - DEVI SEMPRE USARE lo strumento `store_physical_item`!
   - DIVIETO ASSOLUTO di confermare a voce ("Ho aggiornato la posizione...") senza aver prima invocato `store_physical_item`! L'unico modo per aggiornare realmente la posizione nel caveau è chiamare `store_physical_item` passando il nome dell'oggetto e la nuova posizione principale.

4. QUANDO L'UTENTE CHIEDE DELLE SCADENZE O COSA DEVE PAGARE:
   - USA lo strumento `get_upcoming_deadlines`.

5. QUANDO L'UTENTE CHIEDE DI ELIMINARE O CANCELLARE UN DOCUMENTO O UN OGGETTO (es. "elimina la bolletta", "cancella il passaporto", "elimina i documenti delle bollette"):
   - Usa SEMPRE `search_vault` per cercare i documenti o gli oggetti pertinenti nel caveau.
   - Se trovi l'elemento da eliminare, chiama `delete_vault_record` con `target_type`, `target_id` e `title` per attivare il pulsante di conferma interattivo.
   - Nel tuo messaggio di testo chiedi sempre conferma con cortesia: "⚠️ Sei sicuro di voler eliminare [Titolo/Oggetto] dal caveau?".
   - Se ci sono più elementi corrispondenti (es. più bollette), puoi elencare cosa hai trovato e predisporre l'eliminazione per guidare l'utente.

6. STILE DI RISPOSTA E COMUNICAZIONE (FONDAMENTALE):
   - Rispondi sempre in italiano naturale, cortese, chiaro e conciso nello stile autentico di una chat WhatsApp (puoi usare emoji pertinenti come 📄, 📍, 💡, ✅).
   - NON INCLUDERE MAI identificativi tecnici di database (come "ID", "ID 83", "chiave primaria" o etichette meccaniche come "Sintesi:"). L'utente è una persona reale che legge su WhatsApp e desidera informazioni umane, pulite ed eleganti (es. "- 📄 **Bolletta Enel Energia** (64,20 € - scadenza 28/10/2026)").
   - Se l'utente ti chiede "elencami i documenti che hai", "quali documenti ci sono?", "cosa hai nel caveau?", elenca i documenti archiviati con un formato leggibile a punti elenco evidenziando il titolo in grassetto e le informazioni essenziali (importo, scadenza, emittente), senza mai mostrare ID numerici o campi tecnici interni!

7. DATA ODIERNA E CONTESTO TEMPORALE:
   - Conosci sempre con esattezza la data odierna iniettata nel contesto e puoi usare il tool `get_current_date` se necessario.
   - Quando l'utente ti chiede "che giorno è oggi?", "quanti ne abbiamo?", "cosa scade oggi?", "cosa scade questa settimana?" o "è scaduta la bolletta?", calcola con precisione la differenza rispetto alla data odierna.
   - Per le scadenze in ritardo (scadute nel passato), segnalalo con urgenza (es. "⚠️ SCADUTA DA X GIORNI"). Per quelle odierne, evidenzia "⏰ SCADE OGGI!". Per quelle imminenti, indica i giorni rimanenti (es. "In scadenza tra X giorni").

8. QUANDO L'UTENTE CHIEDE LA LISTA O L'ELENCO DI DOCUMENTI O OGGETTI (DISTINZIONE ESSENZIALE):
   - Distingui con la massima attenzione tra DOCUMENTI (file, bollette, certificati, F24) e OGGETTI FISICI (chiavi, occhiali, passaporto, caricabatterie):
     * Se chiede la lista di DOCUMENTI (es. "fai la lista di tutti i documenti", "quali documenti hai?", "mostrami i file"): chiama `list_vault_contents` con `target_type: "documents"`.
     * Se chiede la lista di OGGETTI (es. "fai la lista di tutti gli oggetti", "quali oggetti hai?", "dove sono le mie cose?"): chiama `list_vault_contents` con `target_type: "physical_items"`. NON parlare di documenti se ha chiesto gli oggetti!
     * Se chiede genericamente "cosa c'è nel caveau?" o "mostrami tutto": chiama `list_vault_contents` con `target_type: "all"`.
   - Se il tool restituisce 0 elementi:
     * Per documenti: rispondi cortesemente che al momento non ci sono documenti archiviati nel caveau e che è possibile caricarli con l'icona della graffetta 📎 o della fotocamera 📷.
     * Per oggetti fisici: rispondi cortesemente che al momento non ci sono oggetti fisici memorizzati nel caveau (es. "Al momento non ho oggetti registrati. Se vuoi, dimmi dove hai riposto qualcosa e lo memorizzerò! 📍").
   - Se il tool restituisce elementi, presentali in modo pulito ed elegante con punti elenco su WhatsApp.

9. QUANDO L'UTENTE COMUNICA UN NOME O CHIEDE DI RINOMINARE UN FILE/FOTO (es. "chiamalo Base Volante Fanatec", "chiamala Ricevuta Visita", "rinomina il file in X", "dalle il nome Y", "salvalo come Z"):
   - DEVI SEMPRE USARE lo strumento `rename_vault_document` passando `new_title` con il nome indicato dall'utente!
   - Non rispondere mai solo a parole ("D'accordo, l'ho chiamato...") senza aver invocato `rename_vault_document`!
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

    asst_lower = assistant_text.lower() if assistant_text else ""
    user_lower = user_text.lower() if user_text else ""

    # 1. Verifica quali documenti sono esplicitamente citati nel testo della risposta dell'assistente
    title_matches = []
    issuer_matches = []
    for d in docs:
        title = (d.get("title") or "").strip().lower()
        issuer = (d.get("issuer") or "").strip().lower()
        title_words = [w for w in re.split(r"[^\w]+", title) if len(w) > 3 and w not in ITALIAN_STOPWORDS]
        title_match = (title and title in asst_lower) or (title_words and sum(1 for w in title_words if w in asst_lower) >= max(1, len(title_words) * 0.6))
        # Supporta numeri/acronimi specifici nel titolo (es. "730", "f24")
        acronyms = [w for w in re.split(r"[^\w]+", title) if re.search(r"\d+", w) or len(w) in (2, 3)]
        if not title_match and acronyms:
            title_match = any(a in asst_lower for a in acronyms if len(a) >= 2)

        issuer_match = bool(issuer and len(issuer) > 3 and (issuer in asst_lower))
        if title_match:
            title_matches.append(d)
        elif issuer_match:
            issuer_matches.append(d)

    if title_matches:
        return title_matches
    if issuer_matches:
        return issuer_matches

    # 2. Se l'utente ha memorizzato una posizione fisica o ha chiesto dove si trova un oggetto,
    # oppure se l'assistente risponde indicando una posizione fisica (📍 o 'si trova in'), non allegare documenti!
    is_store_phrase = any(k in user_lower for k in ["messo", "riposto", "salvato", "lasciato", "conservato", "posizionato"])
    is_where_phrase = any(k in user_lower for k in ["dov'è", "dov'e", "dove è", "dove si trova", "dove sono", "dove sta"])
    is_item_answer = "📍" in asst_lower or "si trova in" in asst_lower or "si trovano in" in asst_lower or "è in " in asst_lower
    if is_store_phrase or (is_where_phrase and is_item_answer) or (is_item_answer and not any(k in user_lower for k in ["document", "bollett", "fattur", "f24", "730", "file"])):
        return None

    # 3. Se l'utente ha chiesto un elenco generico, non forzare l'allegato di un widget singolo arbitrario
    is_list_request = any(
        re.search(rf"\b{w}\b", user_lower)
        for w in ["elenco", "elencami", "lista", "tutti", "tutte", "quali", "cosa hai", "cosa c'è", "archivio"]
    )
    if is_list_request:
        return None

    # 4. Se l'utente ha chiesto un singolo elemento o documento specifico
    is_singular_request = any(
        re.search(rf"\b{w}\b", user_lower)
        for w in ["il", "lo", "la", "l'", "un", "uno", "una", "un'"]
    ) and not any(
        re.search(rf"\b{w}\b", user_lower)
        for w in ["i", "gli", "le", "tutti", "tutte", "elenco", "elencami", "lista", "quali"]
    )
    if is_singular_request and len(docs) > 0:
        top_title = (docs[0].get("title") or "").lower()
        top_words = [w for w in re.split(r"[^\w]+", top_title) if len(w) > 3 and w not in ITALIAN_STOPWORDS]
        user_asks_doc = any(k in user_lower for k in ["document", "file", "bollett", "fattur", "contratt", "certificat", "ricevut", "cedolin", "patente", "carta", "f24", "730", "estratto"])
        user_mentions_title = any(w in user_lower for w in top_words)
        if user_mentions_title or user_asks_doc:
            return [docs[0]]

    # 5. Se l'utente ha esplicitamente richiesto un documento
    user_asks_doc = any(k in user_lower for k in ["document", "file", "bollett", "fattur", "contratt", "certificat", "ricevut", "cedolin", "patente", "carta", "f24", "730", "mostrami", "visualizza", "apri", "scarica"])
    if user_asks_doc and len(docs) > 0:
        return [docs[0]]

    return None


class AgenticChatService:
    def __init__(self):
        self.settings = get_settings()

    def _extract_rename_title(self, text: str) -> Optional[str]:
        """Estrae il nuovo titolo da espressioni dell'utente per rinominare documenti o foto."""
        t = text.strip()
        clean = re.sub(r"[.!?,;]+$", "", t).strip()
        m = re.search(
            r"^(?:sì|si|ok|perfetto|d'accordo|va bene)?[,\s]*(?:puoi\s+)?(?:per\s+favore\s+)?(?:chiamalo|chiamala|chiamali|chiamale|rinominalo|rinominala|rinomina(?:\s+l'ultimo\s+(?:file|documento|foto|allegato))?|salvalo\s+come|salvala\s+come|dagli\s+il\s+nome|dalle\s+il\s+nome|dai\s+il\s+nome|assegna\s+il\s+nome)\s+(?:in\s+|come\s+)?[\"']?(.+?)[\"']?$",
            clean,
            re.IGNORECASE
        )
        if m:
            extracted = m.group(1).strip()
            extracted = re.sub(r"^(?:in|come)\s+", "", extracted, flags=re.IGNORECASE).strip(" '\"")
            if extracted:
                return extracted
        return None

    def _extract_item_and_location(self, text: str, last_item_in_context: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
        """Estrae con precisione il nome dell'oggetto e la posizione (per salvataggio, modifica, spostamento)."""
        t = text.strip()
        low = t.lower()

        # Pronomi (es. "mettila in soggiorno", "spostalo in garage")
        m_pro = re.search(
            r"^(?:mettila|mettilo|mettili|mettile|spostala|spostalo|spostali|spostale|posizionalo|posizionala|sistemalo|sistemala)\s+(?:in|nel|nella|nello|nei|negli|nelle|sul|sulla|sullo|sui|sugli|sulle|a|all\'|allo|alla|dentro|sopra|sotto)\s+(.+)",
            low
        )
        if m_pro:
            loc = m_pro.group(1).strip(" .?!")
            return last_item_in_context, loc

        # 1. "modifica/cambia/aggiorna la posizione di X e mettila/mettilo in Y"
        m = re.search(
            r"(?:modifica|cambia|aggiorna)\s+(?:la\s+posizione\s+(?:di|del|della|dei|degli|delle|d\')\s*)?(.+?)\s+(?:e\s+)?(?:mettila|mettilo|mettili|mettile|spostala|spostalo|spostali|spostale|salvala|salvalo)?\s*(?:in|nel|nella|nello|nei|negli|nelle|sul|sulla|sullo|sui|sugli|sulle|a|all\'|allo|alla|dentro|sopra|sotto)\s+(.+)",
            low
        )
        if m:
            item = m.group(1).strip()
            loc = m.group(2).strip(" .?!")
            item = re.sub(r"^(?:la\s+posizione\s+(?:di|del|della|dei|degli|delle|d\')\s*)", "", item).strip()
            item = re.sub(r"^(?:il|lo|la|i|gli|le|l\'|un|uno|una|un\')\s*", "", item).strip()
            return item, loc

        # 2. "sposta/trasferisci/porta X in Y"
        m = re.search(
            r"(?:sposta|trasferisci|porta)\s+(?:il\s+|la\s+|le\s+|i\s+|gli\s+|l\')?(.+?)\s+(?:in|nel|nella|nello|nei|negli|nelle|sul|sulla|sullo|sui|sugli|sulle|a|all\'|allo|alla|dentro|sopra|sotto)\s+(.+)",
            low
        )
        if m:
            item = m.group(1).strip()
            loc = m.group(2).strip(" .?!")
            return item, loc

        # 3. "metti/posiziona/sistema X in Y"
        m = re.search(
            r"(?:metti|posiziona|sistema)\s+(?:il\s+|la\s+|le\s+|i\s+|gli\s+|l\')?(.+?)\s+(?:in|nel|nella|nello|nei|negli|nelle|sul|sulla|sullo|sui|sugli|sulle|a|all\'|allo|alla|dentro|sopra|sotto)\s+(.+)",
            low
        )
        if m:
            item = m.group(1).strip()
            loc = m.group(2).strip(" .?!")
            return item, loc

        # 4. "ho messo/riposto/salvato/lasciato/conservato/posizionato X in Y"
        m = re.search(
            r"(?:messo|riposto|salvato|lasciato|conservato|posizionato|sistemato)\s+(?:il\s+|la\s+|le\s+|i\s+|gli\s+|l\')?(.+?)\s+(?:nel|nella|nello|nei|negli|nelle|in|su|sul|sulla|sullo|sui|sugli|sulle|sotto|a|all\'|allo|alla|dentro|sopra)\s+(.+)",
            low
        )
        if m:
            item = m.group(1).strip()
            loc = m.group(2).strip(" .?!")
            return item, loc

        # 5. "ora X si trova in Y" o "X ora è in Y"
        m = re.search(
            r"(?:ora|adesso)\s+(?:il\s+|la\s+|le\s+|i\s+|gli\s+|l\')?(.+?)\s+(?:è|e\'|si trova|sta)\s+(?:in|nel|nella|nello|nei|negli|nelle|sul|sulla|sullo|sui|sugli|sulle|a|all\'|allo|alla|dentro|sopra|sotto)\s+(.+)",
            low
        )
        if m:
            item = m.group(1).strip()
            loc = m.group(2).strip(" .?!")
            return item, loc

        m = re.search(
            r"(?:il\s+|la\s+|le\s+|i\s+|gli\s+|l\')?(.+?)\s+(?:ora|adesso)\s+(?:è|e\'|si trova|sta)\s+(?:in|nel|nella|nello|nei|negli|nelle|sul|sulla|sullo|sui|sugli|sulle|a|all\'|allo|alla|dentro|sopra|sotto)\s+(.+)",
            low
        )
        if m:
            item = m.group(1).strip()
            loc = m.group(2).strip(" .?!")
            return item, loc

        return None, None

    def _extract_rename_title(self, text: str) -> Optional[str]:
        """Estrae il nuovo titolo per un documento da una richiesta naturale dell'utente."""
        clean = text.strip()
        # Rimuovi prefissi di cortesia/assenso
        clean = re.sub(r"^(?:sì|si|ok|perfetto|d'accordo|va bene)[,\s]+", "", clean, flags=re.IGNORECASE).strip()

        patterns = [
            r"^(?:chiamalo|chiamala|chiamami)\s+(?:in\s+|come\s+)?[\"']?(.+?)[\"']?$",
            r"^(?:rinominalo|rinominala|rinomina(?:\s+il\s+file|\s+la\s+foto|\s+l'ultimo\s+file|\s+l'ultima\s+foto)?)\s+(?:in\s+|come\s+)?[\"']?(.+?)[\"']?$",
            r"^(?:salvalo|salvala)\s+(?:in\s+|come\s+)[\"']?(.+?)[\"']?$",
            r"^(?:dagli|dalle|dai)\s+(?:il\s+nome|come\s+nome)\s+(?:di\s+|in\s+)?[\"']?(.+?)[\"']?$",
            r"^(?:assegna(?:\s+il)?\s+nome)\s+[\"']?(.+?)[\"']?$",
            r"^(?:imposta\s+(?:il\s+)?nome(?:\s+in|\s+come)?)\s+[\"']?(.+?)[\"']?$",
        ]
        for p in patterns:
            m = re.search(p, clean, flags=re.IGNORECASE)
            if m:
                title = m.group(1).strip(" .?!\"'")
                if title and len(title) >= 2:
                    return title
        return None

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
            docs = (
                db.query(Document)
                .order_by(Document.created_at.desc())
                .limit(limit)
                .all()
            )
            return {
                "recent_documents": [
                    {
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
                        "filename": Path(d.file_path).name,
                        "file_url": f"/uploads/{Path(d.file_path).name}",
                        "download_url": f"/api/documents/{d.id}/download",
                        "file_type": d.file_type
                    }
                    for d in docs
                ]
            }

        elif name == "store_physical_item":
            raw_name = args.get("item_name", "Oggetto").strip()
            cleaned_name = re.sub(r"^(il|lo|la|i|gli|le|l'|un|uno|una|un')\s*", "", raw_name, flags=re.IGNORECASE).strip()
            item_name = (cleaned_name if cleaned_name else raw_name).capitalize()
            prim_loc = args.get("primary_location", "Non specificato").strip()
            det_loc = args.get("detailed_location")
            if det_loc is not None:
                det_loc = det_loc.strip() or None
            cat = args.get("category", "generico")

            # 1. Cerca per nome esatto (case-insensitive)
            existing = db.query(PhysicalItem).filter(PhysicalItem.item_name.ilike(item_name)).first()
            if not existing and thread_id:
                existing = db.query(PhysicalItem).filter(PhysicalItem.thread_id == thread_id, PhysicalItem.item_name.ilike(item_name)).first()

            # 2. Se non trovato, cerca con matching semantico/stemming (es. "Tenda" per "Tenda da campeggio")
            if not existing:
                candidates = search_vault_items(db, item_name, thread_id=thread_id)
                if candidates:
                    matched_id = candidates[0].get("item_id") or candidates[0].get("id")
                    if matched_id:
                        existing = db.query(PhysicalItem).filter(PhysicalItem.id == matched_id).first()

            if existing:
                existing.primary_location = prim_loc
                # Quando si aggiorna la stanza principale, il dettaglio va aggiornato se fornito o azzerato per non ereditare vecchi mobili
                existing.detailed_location = det_loc
                if thread_id:
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
                "item_name": item.item_name,
                "primary_location": item.primary_location,
                "detailed_location": item.detailed_location,
                "category": item.category,
                "location_str": loc_str
            }

        elif name == "delete_vault_record":
            target_type = args.get("target_type")
            target_id = args.get("target_id")
            title = args.get("title", "")

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

        elif name == "get_current_date":
            return get_current_date_info()

        elif name == "get_upcoming_deadlines":
            docs = db.query(Document).filter(Document.status == "da_pagare").order_by(Document.due_date.asc().nulls_last()).all()
            today = date.today()
            deadlines_list = []
            for d in docs:
                cat = categorize_deadline(d.due_date, today)
                deadlines_list.append({
                    "id": d.id,
                    "document_id": d.id,
                    "title": d.title,
                    "issuer": d.issuer,
                    "amount": d.amount,
                    "due_date": d.due_date.isoformat() if d.due_date else None,
                    "days_remaining": cat["days_remaining"],
                    "urgency": cat["urgency"],
                    "urgency_label": cat["urgency_label"],
                    "summary": d.summary,
                    "file_url": f"/uploads/{Path(d.file_path).name}",
                    "download_url": f"/api/documents/{d.id}/download",
                    "file_type": d.file_type
                })
            return {
                "today": today.isoformat(),
                "deadlines_count": len(deadlines_list),
                "deadlines": deadlines_list,
                "upcoming_documents": deadlines_list
            }

        elif name == "list_vault_contents":
            target_type = args.get("target_type", "all")
            doc_items = []
            item_items = []

            if target_type in ["all", "documents"]:
                query_docs = db.query(Document)
                if thread_id and thread_id != "general" and thread_id != "all":
                    query_docs = query_docs.filter(Document.thread_id == thread_id)
                docs = query_docs.order_by(Document.created_at.desc()).all()
                for d in docs:
                    fn = Path(d.file_path).name if d.file_path else ""
                    doc_items.append({
                        "id": d.id,
                        "document_id": d.id,
                        "title": d.title,
                        "issuer": d.issuer,
                        "amount": d.amount,
                        "due_date": d.due_date.isoformat() if d.due_date else None,
                        "summary": d.summary,
                        "doc_type": d.doc_type,
                        "status": d.status,
                        "file_url": f"/uploads/{fn}" if fn else None,
                        "download_url": f"/api/documents/{d.id}/download",
                        "file_type": d.file_type
                    })

            if target_type in ["all", "physical_items"]:
                query_items = db.query(PhysicalItem)
                if thread_id and thread_id != "general" and thread_id != "all":
                    query_items = query_items.filter(PhysicalItem.thread_id == thread_id)
                items = query_items.order_by(PhysicalItem.updated_at.desc()).all()
                for it in items:
                    loc = it.primary_location + (f" ({it.detailed_location})" if it.detailed_location else "")
                    item_items.append({
                        "item_id": it.id,
                        "item_name": it.item_name,
                        "primary_location": it.primary_location,
                        "detailed_location": it.detailed_location,
                        "location_str": loc,
                        "category": it.category
                    })

            return {
                "target_type": target_type,
                "documents_count": len(doc_items),
                "items_count": len(item_items),
                "documents": doc_items,
                "found_documents": doc_items,
                "physical_items": item_items,
                "found_physical_items": item_items
            }
        elif name == "rename_vault_document":
            new_title = (args.get("new_title") or "").strip()
            doc_id = args.get("document_id")
            if not new_title:
                return {"error": "Specificare un nuovo titolo valido per il documento."}

            doc = None
            if doc_id:
                doc = db.query(Document).filter(Document.id == doc_id).first()
            if not doc:
                # Se non è specificato l'ID, cerca l'ultimo documento caricato nel canale corrente
                q = db.query(Document)
                if thread_id and thread_id not in ["general", "all"]:
                    q = q.filter(Document.thread_id == thread_id)
                doc = q.order_by(Document.id.desc()).first()

            if not doc:
                return {"error": "Nessun documento trovato nel caveau da rinominare."}

            old_title = doc.title
            doc.title = new_title
            db.commit()
            db.refresh(doc)

            fn = Path(doc.file_path).name if doc.file_path else ""
            doc_info = {
                "id": doc.id,
                "document_id": doc.id,
                "title": doc.title,
                "issuer": doc.issuer,
                "amount": doc.amount,
                "due_date": doc.due_date.isoformat() if doc.due_date else None,
                "summary": doc.summary,
                "doc_type": doc.doc_type,
                "status": doc.status,
                "file_url": f"/uploads/{fn}" if fn else None,
                "download_url": f"/api/documents/{doc.id}/download",
                "file_type": doc.file_type
            }

            return {
                "success": True,
                "document_id": doc.id,
                "old_title": old_title,
                "new_title": doc.title,
                "document": doc_info,
                "documents": [doc_info]
            }

        return {"error": f"Strumento non riconosciuto: {name}"}

    def build_system_prompt(self, db: Session, thread_id: str = "general") -> str:
        """Costruisce il prompt di sistema iniettando la data odierna, la memoria attiva e il contesto del Caveau (RAG)."""
        date_info = get_current_date_info()
        q_docs = db.query(Document)
        q_items = db.query(PhysicalItem)
        if thread_id and thread_id != "general" and thread_id != "all":
            q_docs = q_docs.filter(Document.thread_id == thread_id)
            q_items = q_items.filter(PhysicalItem.thread_id == thread_id)

        total_docs_count = q_docs.count()
        total_items_count = q_items.count()

        docs = q_docs.order_by(Document.id.desc()).limit(50).all()
        items = q_items.order_by(PhysicalItem.id.desc()).limit(60).all()
        unpaid = db.query(Document).filter(Document.status == "da_pagare").all()

        today = date.today()
        yesterday = today - timedelta(days=1)
        tomorrow = today + timedelta(days=1)
        yesterday_str = f"{WEEKDAYS_IT[yesterday.weekday()]} {yesterday.day} {MONTHS_IT[yesterday.month - 1]} {yesterday.year}"
        tomorrow_str = f"{WEEKDAYS_IT[tomorrow.weekday()]} {tomorrow.day} {MONTHS_IT[tomorrow.month - 1]} {tomorrow.year}"

        ground_truth_banner = f"""[GROUND TRUTH - CALENDARIO E TEMPO REALE]:
- OGGI È: {date_info['formatted_italian']} (ore {date_info['current_time']})
- DATA ISO: {date_info['date']}
- ANNO REALE ATTUALE: {date_info['year']}
- IERI ERA: {yesterday_str}
- DOMANI SARÀ: {tomorrow_str}
DIVIETO ASSOLUTO: Non sei nel 2024! Siamo nell'anno {date_info['year']}. Conosci già la data e l'ora attuale. Quando ti viene chiesta la data, l'ora, ieri o domani, rispondi SEMPRE e SOLO usando queste informazioni esatte senza MAI inventare date del passato né citare il 2024!
"""

        vault_summary = [
            f"\n[DATA E ORA ATTUALE]: {date_info['formatted_italian']}, ore {date_info['current_time']} (Data ISO: {date_info['date']}, Anno: {date_info['year']})",
            f"\n[STATO ATTUALE DEL DATABASE SQLITE]:",
            f"- Documenti archiviati nel database per questo canale: {total_docs_count}",
            f"- Oggetti fisici memorizzati nel database per questo canale: {total_items_count}",
            f"- Scadenze/bollette da pagare in sospeso: {len(unpaid)}"
        ]
        if total_docs_count == 0:
            vault_summary.append("- NOTA IMPORTANTE: Al momento ci sono 0 documenti archiviati nel database. Non inventare documenti inesistenti.")
        if total_items_count == 0:
            vault_summary.append("- NOTA IMPORTANTE: Al momento ci sono 0 oggetti fisici memorizzati nel database. Non inventare oggetti inesistenti.")

        if items:
            vault_summary.append(f"\n[INVENTARIO OGGETTI FISICI MEMORIZZATI ({len(items)})]:")
            for it in items:
                loc = it.primary_location + (f" ({it.detailed_location})" if it.detailed_location else "")
                vault_summary.append(f"- 📍 {it.item_name}: {loc}")

        if docs:
            vault_summary.append(f"\n[INVENTARIO DOCUMENTI ARCHIVIATI ({len(docs)})]:")
            for d in docs:
                amt = f" ({d.amount:.2f} €)" if d.amount is not None else ""
                due = f" [scadenza {d.due_date.strftime('%d/%m/%Y')}]" if d.due_date else ""
                vault_summary.append(f"- 📄 {d.title}{amt}{due} (stato: {d.status})")

        if unpaid:
            vault_summary.append(f"\n[PAGAMENTI/SCADENZE IN SOSPESO ({len(unpaid)})]:")
            for u in unpaid[:10]:
                amt = f"{u.amount:.2f} €" if u.amount is not None else "importo non specificato"
                due = u.due_date.strftime('%d/%m/%Y') if u.due_date else "senza data"
                vault_summary.append(f"- ⏰ {u.title}: {amt} entro {due}")

        vault_summary.append("\n[REGOLA SULL'USO DEI DATI DEL DATABASE]:")
        vault_summary.append("- Per conoscere, elencare o cercare documenti o oggetti, DEVI interrogare il database tramite gli appositi strumenti (`search_vault`, `list_vault_contents`, `get_upcoming_deadlines`).")
        vault_summary.append("- I dati reali restituiti dai tuoi strumenti sul database SQLite prevalgono SEMPRE e CATEGORICAMENTE su qualsiasi testo o messaggio della chat precedente.")

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

        return ground_truth_banner + "\n" + SYSTEM_PROMPT + "\n" + "\n".join(vault_summary)

    def _handle_temporal_intent(self, user_text: str, lower_t: str) -> Optional[ChatResponse]:
        """Risponde istantaneamente e con certezza matematica alle domande sulla data e l'ora attuale, ieri o domani."""
        # Se la domanda riguarda scadenze o documenti specifici, lascia che proceda con i tool di ricerca
        if any(k in lower_t for k in ["scadenz", "da pagare", "bollett", "f24", "document", "cosa scade"]):
            return None

        # Normalizza accenti uniti (es. "giornoè" -> "giorno è", "dataè" -> "data è", "oraè" -> "ora è")
        normalized = re.sub(r"([a-z])(è|e'|é)", r"\1 \2", lower_t)
        clean = re.sub(r"[?!.,;]", " ", normalized)
        clean = re.sub(r"\s+", " ", clean).strip()

        # 1. Domani
        is_tomorrow = any(k in clean for k in ["domani", "prossimo giorno"]) and any(k in clean for k in ["che giorno", "che data", "quanti ne abbiamo", "sarà", "sara", "quando è", "quando e"])
        if is_tomorrow or clean in [
            "domani che giorno è", "domani che giorno e", "che giorno è domani", "che giorno e domani",
            "che giorno sara domani", "che giorno sarà domani", "domani che data è", "domani che data e",
            "domani quanti ne abbiamo"
        ]:
            tomorrow = date.today() + timedelta(days=1)
            weekday = WEEKDAYS_IT[tomorrow.weekday()]
            month = MONTHS_IT[tomorrow.month - 1]
            formatted = f"{weekday} {tomorrow.day} {month} {tomorrow.year}"
            return ChatResponse(
                reply=f"📅 Domani sarà **{formatted}**.",
                action="get_current_date",
                data={"date": tomorrow.isoformat(), "formatted_italian": formatted, "target": "tomorrow"}
            )

        # 2. Ieri
        is_yesterday = any(k in clean for k in ["ieri", "giorno prima"]) and any(k in clean for k in ["che giorno", "che data", "quanti ne avevamo", "era", "quando era"])
        if is_yesterday or clean in [
            "ieri che giorno era", "che giorno era ieri", "ieri che data era", "ieri quanti ne avevamo",
            "che data era ieri"
        ]:
            yesterday = date.today() - timedelta(days=1)
            weekday = WEEKDAYS_IT[yesterday.weekday()]
            month = MONTHS_IT[yesterday.month - 1]
            formatted = f"{weekday} {yesterday.day} {month} {yesterday.year}"
            return ChatResponse(
                reply=f"📅 Ieri era **{formatted}**.",
                action="get_current_date",
                data={"date": yesterday.isoformat(), "formatted_italian": formatted, "target": "yesterday"}
            )

        # 3. Oggi / Data attuale / Giorno attuale / Ora attuale
        is_today = (
            any(k in clean for k in [
                "che giorno è", "che giorno e", "che data è", "che data e",
                "data di oggi", "data odierna", "quanti ne abbiamo", "giorno odierno",
                "che ore sono", "ora attuale", "ora esatta", "orario attuale",
                "dimmi che giorno è", "dimmi che giorno e", "dimmi la data", "dimmi l'ora"
            ])
            or clean in [
                "che giorno è", "che giorno e", "che data è", "che data e", "data oggi",
                "quanti ne abbiamo oggi", "quanti ne abbiamo", "che ora è", "che ora e",
                "oggi che giorno è", "oggi che giorno e", "oggi"
            ]
        )
        if is_today:
            d_info = get_current_date_info()
            return ChatResponse(
                reply=f"📅 Oggi è **{d_info['formatted_italian']}** (ore {d_info['current_time']}).",
                action="get_current_date",
                data=d_info
            )

        return None

    def _handle_listing_intent(self, user_text: str, lower_t: str, db: Session, thread_id: str = "general") -> Optional[ChatResponse]:
        """Restituisce l'elenco reale, veritiero e aggiornato dei documenti presenti nel database, eliminando allucinazioni."""
        clean = re.sub(r"[?!.,;]", " ", lower_t)
        clean = re.sub(r"\s+", " ", clean).strip()

        is_listing = (
            any(k in clean for k in [
                "fai la lista", "fammi la lista", "fai una lista", "fai prima la lista",
                "elenca tutti", "elencami tutti", "elenca i documenti", "elencami i documenti",
                "elenco documenti", "elenco dei documenti", "lista documenti", "lista dei documenti",
                "quali documenti hai", "quali documenti ci sono", "cosa hai nel caveau",
                "cosa c'è nel caveau", "cosa ce nel caveau", "mostrami tutti i documenti",
                "mostra tutti i documenti", "vedere tutti i documenti", "cosa hai archiviato",
                "cosa c'è di archiviato", "tutti i documenti che hai"
            ])
            or clean in ["documenti", "i miei documenti", "tutti i documenti", "elenco", "lista"]
        )
        if not is_listing:
            return None

        query = db.query(Document)
        if thread_id and thread_id != "general" and thread_id != "all":
            query = query.filter(Document.thread_id == thread_id)
        docs = query.order_by(Document.id.desc()).all()

        if not docs:
            return ChatResponse(
                reply="Nel caveau non sono presenti documenti archiviati al momento.",
                action="list_documents",
                data={"count": 0, "documents": []}
            )

        lines = []
        doc_items = []
        for d in docs:
            amt = f" - {d.amount:.2f} €" if d.amount is not None else ""
            due = f" - Scadenza: {d.due_date.strftime('%d/%m/%Y')}" if d.due_date else ""
            iss = f" ({d.issuer}{amt}{due})" if (d.issuer or amt or due) else ""
            lines.append(f"- 📄 **{d.title}**{iss}")
            fn = Path(d.file_path).name if d.file_path else ""
            doc_items.append({
                "document_id": d.id,
                "title": d.title,
                "issuer": d.issuer,
                "amount": d.amount,
                "due_date": d.due_date.isoformat() if d.due_date else None,
                "summary": d.summary,
                "file_url": f"/uploads/{fn}" if fn else None,
                "download_url": f"/api/documents/{d.id}/download",
                "file_type": d.file_type
            })

        reply = f"Certo! Ecco l'elenco completo dei **{len(docs)} documenti** attualmente presenti nel caveau:\n\n" + "\n".join(lines)
        return ChatResponse(
            reply=reply,
            action="list_documents",
            data={"count": len(docs), "documents": doc_items},
            documents=doc_items[:5]
        )

    def _handle_deletion_intent(self, user_text: str, lower_t: str, db: Session, thread_id: str = "general") -> Optional[ChatResponse]:
        """Gestisce in modo sicuro le richieste di eliminazione (singola o multipla/totale) chiedendo conferma prima di qualsiasi azione."""
        is_deletion = any(k in lower_t for k in [
            "elimina", "cancella", "rimuovi", "eliminarlo", "cancellarlo", 
            "rimuoverlo", "butta", "cancellami", "eliminami", "eliminali", "cancellali", "rimuovili"
        ])
        if not is_deletion:
            return None

        clean_prompt = re.sub(r"[?!.,;]", " ", lower_t)
        clean_prompt = re.sub(r"\s+", " ", clean_prompt).strip()

        # 1. Rileva eliminazione multipla o totale
        is_bulk = (
            any(k in clean_prompt for k in [
                "elimina tutti", "elimina tutte", "cancella tutti", "cancella tutte",
                "rimuovi tutti", "rimuovi tutte", "svuota", "elimina tutto", "cancella tutto",
                "eliminali tutti", "cancellali tutti", "rimuovili tutti"
            ])
            or clean_prompt in ["eliminali", "cancellali", "rimuovili", "elimina tutto", "cancella tutto", "elimina tutti", "cancella tutti"]
        )

        if is_bulk:
            query = db.query(Document)
            if thread_id and thread_id != "general" and thread_id != "all":
                query = query.filter(Document.thread_id == thread_id)

            cat_name = "tutti i documenti"
            if "bollett" in clean_prompt:
                query = query.filter(or_(Document.doc_type == "bolletta", Document.title.ilike("%bollett%")))
                cat_name = "tutte le bollette"
            elif "f24" in clean_prompt or "tribut" in clean_prompt:
                query = query.filter(or_(Document.doc_type.ilike("%f24%"), Document.title.ilike("%f24%")))
                cat_name = "tutti i modelli F24"

            docs_to_delete = query.all()
            if not docs_to_delete:
                return ChatResponse(
                    reply=f"Non ho trovato documenti da eliminare nel caveau ({cat_name}).",
                    action="REPLY"
                )

            doc_ids = [d.id for d in docs_to_delete]
            doc_titles = [d.title for d in docs_to_delete]

            conf = {
                "type": "delete_confirmation",
                "target_type": "bulk_documents",
                "target_id": doc_ids[0],
                "target_ids": doc_ids,
                "title": f"TUTTI i {len(doc_ids)} documenti ({cat_name})" if len(doc_ids) > 1 else doc_titles[0],
                "details": f"Verranno eliminati definitivamente {len(doc_ids)} file dal caveau."
            }

            list_preview = "\n".join([f"- 📄 **{t}**" for t in doc_titles[:6]])
            if len(doc_titles) > 6:
                list_preview += f"\n- ... e altri {len(doc_titles) - 6} documenti"

            return ChatResponse(
                reply=f"⚠️ Stai per eliminare definitivamente **{len(doc_ids)} documenti** ({cat_name}):\n\n{list_preview}\n\nSei sicuro di voler procedere?",
                action="REQUEST_DELETE",
                data={"target_type": "bulk_documents", "document_ids": doc_ids},
                confirmation=conf,
                documents=[{
                    "document_id": d.id,
                    "title": d.title,
                    "issuer": d.issuer,
                    "amount": d.amount,
                    "due_date": d.due_date.isoformat() if d.due_date else None,
                    "summary": d.summary,
                    "file_url": f"/uploads/{Path(d.file_path).name}" if d.file_path else None,
                    "download_url": f"/api/documents/{d.id}/download",
                    "file_type": d.file_type
                } for d in docs_to_delete[:4]]
            )

        # 2. Eliminazione di un singolo documento o oggetto specifico
        target_query = re.sub(
            r"^(?:per favore|puoi|vorrei|potresti|ti prego di|elimina|cancella|rimuovi|cancellami|eliminami|butta)\s*(?:il|la|lo|le|i|l'|un|una|uno)?\s*",
            "", lower_t
        ).strip(" ?.")
        target_query = re.sub(
            r"^(?:documenti\s+delle|documenti\s+dei|documenti\s+di|documenti\s+del|documenti|documento\s+delle|documento\s+del|documento\s+di|documento|file\s+delle|file\s+di|file\s+del|file)\s*",
            "", target_query
        ).strip(" ?.")
        target_query = re.sub(r"\s*(?:per favore|per cortesia|grazie|per piacere)$", "", target_query).strip()
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
            return None

    def run_turn(self, user_text: str, db: Session, thread_id: str = "general") -> ChatResponse:
        """Esegue un turno conversazionale con tool-calling dell'agente."""
        lower_t = user_text.lower()

        # Intercetta le richieste di eliminazione sicura (singola o multipla)
        del_resp = self._handle_deletion_intent(user_text, lower_t, db, thread_id=thread_id)
        if del_resp:
            return del_resp

        # Intercetta immediatamente domande sulla data/ora odierna, ieri o domani con calcolo istantaneo esatto
        temp_resp = self._handle_temporal_intent(user_text, lower_t)
        if temp_resp:
            return temp_resp

        # Intercetta risposte affermative a una proposta precedente dell'assistente ("si", "sì", "ok", "mostramelo", "certo")
        is_affirmative = lower_t.strip(" !.?") in ["si", "sì", "ok", "va bene", "certo", "mostramelo", "mostrameli", "fammi vedere", "apri", "yes", "vai"]
        if is_affirmative:
            last_asst = (
                db.query(ChatMessage)
                .filter(ChatMessage.thread_id == thread_id, ChatMessage.sender == "assistant")
                .order_by(ChatMessage.id.desc())
                .first()
            )
            if last_asst and last_asst.content:
                s_res = self.execute_tool("search_vault", {"query": last_asst.content}, db=db, thread_id=thread_id)
                f_docs = s_res.get("found_documents", [])
                if f_docs:
                    matched = filter_relevant_documents(f_docs, last_asst.content, user_text) or [f_docs[0]]
                    d = matched[0]
                    return ChatResponse(
                        reply=f"📄 Eccolo! Ho recuperato il documento **{d['title']}** ({d.get('issuer', 'Documento')}):\n💡 {d.get('summary', '')}",
                        action="search_vault",
                        data=s_res,
                        documents=matched
                    )

        # Rileva ultimo oggetto citato nel thread per eventuale risoluzione pronomi (es. "mettila in...")
        last_item_name = None
        last_asst_msg = (
            db.query(ChatMessage)
            .filter(ChatMessage.thread_id == thread_id, ChatMessage.sender == "assistant")
            .order_by(ChatMessage.id.desc())
            .first()
        )
        if last_asst_msg and last_asst_msg.content:
            m_it = re.search(r"\*\*(.+?)\*\*", last_asst_msg.content)
            if m_it:
                last_item_name = m_it.group(1).strip()

        # Rileva intenzione di memorizzazione, modifica o spostamento posizione fisica
        is_store_or_update = (
            any(k in lower_t for k in [
                "messo", "riposto", "salvato", "lasciato", "conservato", "posizionato", "sistemato",
                "modifica la posizione", "cambia la posizione", "aggiorna la posizione",
                "sposta", "spostato", "spostata", "spostare",
                "mettilo", "mettila", "mettili", "mettile", "metti",
                "ora è in", "ora si trova in", "adesso è in", "adesso si trova in"
            ])
            and not any(k in lower_t for k in ["dov'è", "dov'e", "dove ho", "dove si trova", "dove sono", "dove sta", "dove è"])
        )

        is_where_request = (
            any(k in lower_t for k in [
                "dov'è", "dov'e", "dove è", "dove sono", "dove si trova", "dove si trovano",
                "dove ho messo", "dove ho riposto", "dove ho lasciato", "dove sta", "dove stanno",
                "dove trovo"
            ])
            and not is_store_or_update
        )

        is_listing_request = (
            any(k in lower_t for k in [
                "lista", "elenco", "elencami", "quali documenti", "quali oggetti",
                "mostrami tutti", "mostrami tutte", "mostra tutti", "mostra tutte",
                "cosa c'è nel caveau", "cosa ce nel caveau", "cosa ho nel caveau", "cosa hai nel caveau",
                "vedere tutti", "vedere tutte", "tutti i documenti", "tutti gli oggetti", "che oggetti", "che documenti"
            ])
            or lower_t.strip(" !.?") in ["documenti", "oggetti", "tutti i documenti", "tutti gli oggetti", "tutto", "i miei documenti", "i miei oggetti"]
        )
        is_deadline_request = (
            any(k in lower_t for k in [
                "scadenz", "da pagare", "bollette da pagare", "tributi da pagare",
                "cosa devo pagare", "quanto devo pagare", "prossime scadenze", "scadenze in sospeso"
            ])
            and not is_listing_request
            and not is_store_or_update
        )

        is_rename_request = (
            any(k in lower_t for k in [
                "chiamalo", "chiamala", "rinominalo", "rinominala", "rinomina",
                "salvalo come", "salvala come", "dagli il nome", "dalle il nome", "dai il nome", "dagli come nome", "dalle come nome"
            ])
            and not is_store_or_update
            and not is_where_request
        )

        stored_item_result = None
        if is_store_or_update:
            item_n, loc_n = self._extract_item_and_location(user_text, last_item_in_context=last_item_name)
            if item_n and loc_n:
                stored_item_result = self.execute_tool("store_physical_item", {"item_name": item_n, "primary_location": loc_n}, db=db, thread_id=thread_id)

        # Se non c'è chiave API, fallback deterministico per test offline
        if not self.settings.OPENROUTER_API_KEY:
            clean_test = lower_t.replace("?", "").strip()
            if is_rename_request:
                new_title = self._extract_rename_title(user_text)
                if new_title:
                    tool_out = self.execute_tool("rename_vault_document", {"new_title": new_title}, db=db, thread_id=thread_id)
                    if tool_out.get("success"):
                        return ChatResponse(
                            reply=f"✅ Ho rinominato il file in '**{tool_out['new_title']}**'!",
                            action="rename_vault_document",
                            data=tool_out,
                            documents=tool_out.get("documents")
                        )
                    else:
                        return ChatResponse(
                            reply=tool_out.get("error", "Non sono riuscito a rinominare il file."),
                            action="rename_vault_document",
                            data=tool_out
                        )

            if is_store_or_update and stored_item_result:
                return ChatResponse(
                    reply=f"✅ Memorizzato! Ho aggiornato la posizione di **{stored_item_result['item_name']}** in: {stored_item_result['location_str']}.",
                    action="store_physical_item",
                    data=stored_item_result
                )

            if is_where_request:
                q = re.sub(r"^(?:dov'è|dov'e|dove è|dove sono|dove si trova|dove ho messo|dove sta|dove)\s+(?:il|lo|la|i|gli|le|l')?\s*", "", lower_t).strip(" ?.")
                tool_out = self.execute_tool("search_vault", {"query": q}, db=db, thread_id=thread_id)
                items = tool_out.get("found_physical_items", [])
                docs = tool_out.get("found_documents", [])
                if items:
                    it = items[0]
                    loc_desc = it.get("location_str") or (it.get("primary_location", "") + (f" ({it['detailed_location']})" if it.get("detailed_location") else ""))
                    return ChatResponse(
                        reply=f"📍 **{it['item_name']}** si trova in: {loc_desc}.",
                        action="search_vault",
                        data=tool_out
                    )
                elif docs:
                    d = docs[0]
                    return ChatResponse(
                        reply=f"📄 Ho trovato il documento **{d['title']}** ({d.get('issuer', '')}).",
                        action="search_vault",
                        data=tool_out,
                        documents=[d]
                    )
                else:
                    return ChatResponse(
                        reply=f"Ho cercato nel caveau, ma non ho trovato '{q}'. Potrebbe essere stato eliminato o non ancora memorizzato.",
                        action="search_vault",
                        data=tool_out
                    )

            if is_listing_request or any(k in clean_test for k in ["lista", "elenco", "quali documenti", "quali oggetti"]):
                target = "physical_items" if any(k in clean_test for k in ["oggett", "cose"]) else ("documents" if any(k in clean_test for k in ["document", "file", "bollett"]) else "all")
                tool_out = self.execute_tool("list_vault_contents", {"target_type": target}, db=db, thread_id=thread_id)
                if target == "physical_items":
                    items = tool_out.get("physical_items", [])
                    if items:
                        lines = [f"- 📍 **{it['item_name']}**: {it['location_str']}" for it in items]
                        rep = "Ecco gli oggetti fisici memorizzati nel caveau:\n\n" + "\n".join(lines)
                    else:
                        rep = "Nel caveau non sono presenti oggetti fisici memorizzati al momento. Dimmi pure dove riponi i tuoi oggetti e li registrerò subito! 📍"
                    return ChatResponse(reply=rep, action="list_vault_contents", data=tool_out)
                elif target == "documents":
                    docs = tool_out.get("documents", [])
                    if docs:
                        lines = [f"- 📄 **{d['title']}** ({d['issuer']})" for d in docs]
                        rep = f"Ecco l'elenco dei {len(docs)} documenti presenti nel caveau:\n\n" + "\n".join(lines)
                    else:
                        rep = "Nel caveau non sono presenti documenti archiviati al momento."
                    return ChatResponse(reply=rep, action="list_vault_contents", data=tool_out, documents=docs[:5])
                else:
                    items = tool_out.get("physical_items", [])
                    docs = tool_out.get("documents", [])
                    parts = []
                    if docs:
                        lines = [f"- 📄 **{d['title']}** ({d.get('issuer', '')})" for d in docs]
                        parts.append("📄 **Documenti:**\n" + "\n".join(lines))
                    if items:
                        lines = [f"- 📍 **{it['item_name']}**: {it['location_str']}" for it in items]
                        parts.append("📍 **Oggetti fisici:**\n" + "\n".join(lines))
                    rep = "\n\n".join(parts) if parts else "Nel caveau non sono presenti documenti o oggetti memorizzati al momento."
                    return ChatResponse(reply=rep, action="list_vault_contents", data=tool_out, documents=docs[:5])

            if is_deadline_request:
                t_out = self.execute_tool("get_upcoming_deadlines", {}, db, thread_id=thread_id)
                docs = t_out.get("deadlines") or t_out.get("upcoming_documents", [])
                if docs:
                    lines = []
                    for d in docs[:5]:
                        urg = f" - ⚠️ {d['urgency_label']}" if d.get('urgency_label') else ""
                        lines.append(f"- 📄 **{d['title']}** — {d.get('amount','?')} € scad. {d.get('due_date','?')}{urg}")
                    return ChatResponse(reply="📅 Ecco le tue scadenze in sospeso:\n\n" + "\n".join(lines), action="get_upcoming_deadlines", data=t_out, documents=docs)
                return ChatResponse(reply="✅ Non ci sono scadenze o pagamenti in sospeso al momento.", action="get_upcoming_deadlines", data=t_out)

            ai = MockAIService()
            intent = ai.classify_and_extract_intent(user_text)
            reply = ai.generate_conversational_reply(user_text)
            return ChatResponse(reply=reply, action="REPLY")

        # Recupera la cronologia recente della chat (fino a 100 messaggi) per massima consapevolezza conversazionale e contesto continuo
        system_content = self.build_system_prompt(db, thread_id=thread_id)
        recent_msgs = (
            db.query(ChatMessage)
            .filter(ChatMessage.thread_id == thread_id)
            .order_by(ChatMessage.id.desc())
            .limit(100)
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


        if is_rename_request:
            tool_choice_cfg = {"type": "function", "function": {"name": "rename_vault_document"}}
        elif is_listing_request:
            tool_choice_cfg = {"type": "function", "function": {"name": "list_vault_contents"}}
        elif is_store_or_update:
            tool_choice_cfg = {"type": "function", "function": {"name": "store_physical_item"}}
        elif is_where_request:
            tool_choice_cfg = {"type": "function", "function": {"name": "search_vault"}}
        elif is_deadline_request:
            tool_choice_cfg = {"type": "function", "function": {"name": "get_upcoming_deadlines"}}
        else:
            tool_choice_cfg = "auto"

        try:
            r1 = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json={
                    "model": agent_model,
                    "messages": history_messages,
                    "tools": TOOLS_DEFINITION,
                    "tool_choice": tool_choice_cfg,
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

                        tool_payload = {
                            "dati_database_sqlite": tool_output,
                            "regola_verita_assoluta": (
                                "IMPORTANTE: Questi dati provengono DIRETTAMENTE dal database SQLite in tempo reale. "
                                "Basa la tua risposta UNICAMENTE ed ESCLUSIVAMENTE su questi dati. "
                                "Se una lista è vuota ([]), significa che nel database NON ci sono elementi (sono stati rimossi o mai salvati). "
                                "È VIETATO usare la cronologia della chat per inventare o supporre oggetti, posizioni o documenti assenti da questi dati."
                            )
                        }
                        history_messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id"),
                            "content": json.dumps(tool_payload, ensure_ascii=False)
                        })

                    # Se l'utente ha comunicato/spostato una posizione ma il modello ha chiamato solo search_vault o altro tool,
                    # eseguiamo anche store_physical_item per garantire la memorizzazione nel database
                    if is_store_or_update and not any(tc.get("function", {}).get("name") == "store_physical_item" for tc in tool_calls):
                        item_n, loc_n = self._extract_item_and_location(user_text, last_item_in_context=last_item_name)
                        if item_n and loc_n:
                            store_out = self.execute_tool("store_physical_item", {"item_name": item_n, "primary_location": loc_n}, db=db, thread_id=thread_id)
                            tool_action = "store_physical_item"
                            tool_data = store_out

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
                            docs_found = tool_data.get("found_documents") or tool_data.get("recent_documents") or tool_data.get("documents")

                        if not final_text:
                            if tool_action == "search_vault":
                                if docs_found:
                                    d = docs_found[0]
                                    final_text = f"📄 Ho trovato: **{d['title']}**\n💡 {d['summary']}"
                                else:
                                    final_text = "Ho cercato nel caveau ma non ho trovato corrispondenze nel database."
                            elif tool_action == "list_vault_contents":
                                if (tool_data or {}).get("target_type") == "physical_items":
                                    items = (tool_data or {}).get("physical_items", [])
                                    if items:
                                        lines = [f"- 📍 **{it['item_name']}**: {it['location_str']}" for it in items]
                                        final_text = f"📍 Ecco gli oggetti fisici memorizzati nel caveau:\n\n" + "\n".join(lines)
                                    else:
                                        final_text = "Nel caveau non sono presenti oggetti fisici memorizzati al momento. Dimmi pure dove riponi i tuoi oggetti e li registrerò subito! 📍"
                                elif (tool_data or {}).get("target_type") == "documents":
                                    docs = (tool_data or {}).get("documents", [])
                                    if docs:
                                        lines = [f"- 📄 **{d['title']}** ({d['issuer']})" for d in docs]
                                        final_text = f"📄 Ecco i documenti archiviati nel caveau:\n\n" + "\n".join(lines)
                                    else:
                                        final_text = "Nel caveau non sono presenti documenti archiviati al momento."
                                else:
                                    items = (tool_data or {}).get("physical_items", [])
                                    docs = (tool_data or {}).get("documents", [])
                                    parts = []
                                    if docs:
                                        lines = [f"- 📄 **{d['title']}** ({d.get('issuer', '')})" for d in docs]
                                        parts.append("📄 **Documenti:**\n" + "\n".join(lines))
                                    if items:
                                        lines = [f"- 📍 **{it['item_name']}**: {it['location_str']}" for it in items]
                                        parts.append("📍 **Oggetti fisici:**\n" + "\n".join(lines))
                                    final_text = "\n\n".join(parts) if parts else "Nel caveau non sono presenti documenti o oggetti memorizzati al momento."
                            elif tool_action == "get_upcoming_deadlines":
                                up = (tool_data or {}).get("deadlines") or (tool_data or {}).get("upcoming_documents", [])
                                if up:
                                    lines = []
                                    for d in up[:5]:
                                        urg = f" - ⚠️ {d['urgency_label']}" if d.get('urgency_label') else ""
                                        lines.append(f"- 📄 **{d['title']}**: {d.get('amount', '?')} € (scad. {d.get('due_date', '?')}{urg})")
                                    final_text = "📅 Ecco le tue scadenze in sospeso:\n\n" + "\n".join(lines)
                                else:
                                    final_text = "✅ Non ci sono scadenze o pagamenti in sospeso al momento."
                            elif tool_action == "get_current_date":
                                final_text = f"📅 Oggi è **{tool_data.get('formatted_italian')}** (ore {tool_data.get('current_time')})."
                            elif tool_action == "store_physical_item":
                                it_name = (tool_data or {}).get("item_name")
                                loc_str = (tool_data or {}).get("location_str")
                                final_text = f"✅ Memorizzato! Ho aggiornato la posizione di **{it_name}** in: {loc_str}."
                            elif tool_action == "rename_vault_document":
                                n_title = (tool_data or {}).get("new_title", "nuovo nome")
                                final_text = f"✅ Ho rinominato il file in '**{n_title}**'!"
                            else:
                                final_text = "Operazione completata con successo nel caveau."
                        else:
                            # Validazione e ancoraggio stretto della risposta del modello al database SQLite reale:
                            if tool_action == "list_vault_contents":
                                target = (tool_data or {}).get("target_type")
                                items = (tool_data or {}).get("physical_items", [])
                                docs = (tool_data or {}).get("documents", [])
                                if target == "physical_items" and len(items) == 0:
                                    final_text = "Nel caveau non sono presenti oggetti fisici memorizzati al momento. Dimmi pure dove riponi i tuoi oggetti e li registrerò subito! 📍"
                                elif target == "documents" and len(docs) == 0:
                                    final_text = "Nel caveau non sono presenti documenti archiviati al momento."
                                elif target == "all" and len(items) == 0 and len(docs) == 0:
                                    final_text = "Nel caveau non sono presenti documenti o oggetti memorizzati al momento."

                            elif tool_action == "search_vault":
                                found_i = (tool_data or {}).get("found_physical_items", [])
                                found_d = (tool_data or {}).get("found_documents", [])
                                if not found_i and not found_d:
                                    final_text = "Ho cercato nel caveau ma non ho trovato corrispondenze nel database. Potrebbe essere stato eliminato o non ancora memorizzato."
                                elif found_i and not found_d:
                                    it = found_i[0]
                                    if it.get("primary_location", "").lower() not in final_text.lower():
                                        final_text = f"📍 **{it['item_name']}** si trova in: {it['location_str']}."

                            elif tool_action == "get_upcoming_deadlines":
                                up = (tool_data or {}).get("deadlines") or (tool_data or {}).get("upcoming_documents", [])
                                if len(up) == 0:
                                    final_text = "✅ Non ci sono scadenze o pagamenti in sospeso al momento."

                            elif tool_action == "store_physical_item":
                                it_n = (tool_data or {}).get("item_name")
                                loc_s = (tool_data or {}).get("location_str")
                                if loc_s and (tool_data or {}).get("primary_location", "").lower() not in final_text.lower():
                                    final_text = f"✅ Memorizzato! Ho salvato la posizione di **{it_n}** in: {loc_s}."
                                elif "memorizzato" not in final_text.lower() and "salvat" not in final_text.lower() and "aggiornat" not in final_text.lower():
                                    final_text = f"✅ Memorizzato! {final_text}"

                            elif tool_action == "rename_vault_document":
                                n_title = (tool_data or {}).get("new_title")
                                if n_title and n_title.lower() not in final_text.lower():
                                    final_text = f"✅ Ho rinominato il file in '**{n_title}**'!\n{final_text}"

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

                    # Per tutti gli altri tool call testuali (search_vault, get_upcoming_deadlines, get_current_date, ecc.)
                    # esegui la ricerca più appropriata in base al contenuto
                    if "get_current_date" in raw_tc:
                        d_info = self.execute_tool("get_current_date", {}, db, thread_id=thread_id)
                        return ChatResponse(
                            reply=f"📅 Oggi è **{d_info['formatted_italian']}** (ore {d_info['current_time']}).",
                            action="get_current_date",
                            data=d_info
                        )

                    if "get_upcoming_deadlines" in raw_tc:
                        t_out = self.execute_tool("get_upcoming_deadlines", {}, db, thread_id=thread_id)
                        docs = t_out.get("deadlines") or t_out.get("upcoming_documents", [])
                        if docs:
                            lines = []
                            for d in docs[:5]:
                                urg = f" - ⚠️ {d['urgency_label']}" if d.get('urgency_label') else ""
                                lines.append(f"- 📄 **{d['title']}** — {d.get('amount','?')} € scad. {d.get('due_date','?')}{urg}")
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
                    if is_rename_request:
                        new_title = self._extract_rename_title(user_text)
                        if new_title:
                            r_out = self.execute_tool("rename_vault_document", {"new_title": new_title}, db=db, thread_id=thread_id)
                            if r_out.get("success"):
                                return ChatResponse(
                                    reply=f"✅ Ho rinominato il file in '**{r_out['new_title']}**'!",
                                    action="rename_vault_document",
                                    data=r_out,
                                    documents=r_out.get("documents")
                                )

                    if is_store_or_update:
                        if not stored_item_result:
                            item_n, loc_n = self._extract_item_and_location(user_text, last_item_in_context=last_item_name)
                            if item_n and loc_n:
                                stored_item_result = self.execute_tool("store_physical_item", {"item_name": item_n, "primary_location": loc_n}, db=db, thread_id=thread_id)
                        if stored_item_result:
                            if "memorizzato" not in direct_reply.lower() and "salvat" not in direct_reply.lower() and "aggiornat" not in direct_reply.lower():
                                direct_reply = f"✅ Posizione aggiornata! {direct_reply}"
                            return ChatResponse(
                                reply=direct_reply,
                                action="store_physical_item",
                                data=stored_item_result
                            )

                    # Se l'utente chiedeva dove si trova qualcosa (is_where_request),
                    # ancoriamo sempre la risposta al database reale SQLite (nessuna allucinazione da cronologia chat)
                    if is_where_request:
                        search_q = re.sub(r"^(?:dov'è|dov'e|dove è|dove sono|dove si trova|dove ho messo|dove sta|dove)\s+(?:il|lo|la|i|gli|le|l')?\s*", "", lower_t).strip(" ?.")
                        s_res = self.execute_tool("search_vault", {"query": search_q or user_text}, db=db, thread_id=thread_id)
                        found_items = s_res.get("found_physical_items", [])
                        found_docs = s_res.get("found_documents", [])
                        if found_items:
                            it = found_items[0]
                            loc_desc = it.get("location_str") or (it.get("primary_location", "") + (f" ({it['detailed_location']})" if it.get("detailed_location") else ""))
                            clean_rep = f"📍 **{it['item_name']}** si trova in: {loc_desc}."
                            return ChatResponse(reply=clean_rep, action="search_vault", data=s_res)
                        elif found_docs:
                            d = found_docs[0]
                            clean_rep = f"📄 Ho trovato il documento **{d['title']}** ({d.get('issuer', '')}).\n💡 {d.get('summary', '')}"
                            return ChatResponse(reply=clean_rep, action="search_vault", data=s_res, documents=[d])
                        else:
                            clean_rep = f"Ho cercato nel caveau, ma non ho trovato '{search_q}'. Potrebbe essere stato eliminato o non ancora registrato."
                            return ChatResponse(reply=clean_rep, action="search_vault", data=s_res)

                    if is_listing_request:
                        target = "physical_items" if any(k in lower_t for k in ["oggett", "cose"]) else ("documents" if any(k in lower_t for k in ["document", "file", "bollett", "fattur"]) else "all")
                        l_res = self.execute_tool("list_vault_contents", {"target_type": target}, db=db, thread_id=thread_id)
                        if target == "physical_items":
                            items = l_res.get("physical_items", [])
                            if items:
                                lines = [f"- 📍 **{it['item_name']}**: {it['location_str']}" for it in items]
                                rep = "📍 Ecco gli oggetti fisici memorizzati nel caveau:\n\n" + "\n".join(lines)
                            else:
                                rep = "Nel caveau non sono presenti oggetti fisici memorizzati al momento. Dimmi pure dove riponi i tuoi oggetti e li registrerò subito! 📍"
                            return ChatResponse(reply=rep, action="list_vault_contents", data=l_res)
                        elif target == "documents":
                            docs = l_res.get("documents", [])
                            if docs:
                                lines = [f"- 📄 **{d['title']}** ({d.get('issuer', '')})" for d in docs]
                                rep = f"📄 Ecco i {len(docs)} documenti presenti nel caveau:\n\n" + "\n".join(lines)
                            else:
                                rep = "Nel caveau non sono presenti documenti archiviati al momento."
                            return ChatResponse(reply=rep, action="list_vault_contents", data=l_res, documents=docs[:5])
                        else:
                            items = l_res.get("physical_items", [])
                            docs = l_res.get("documents", [])
                            parts = []
                            if docs:
                                lines = [f"- 📄 **{d['title']}** ({d.get('issuer', '')})" for d in docs]
                                parts.append("📄 **Documenti:**\n" + "\n".join(lines))
                            if items:
                                lines = [f"- 📍 **{it['item_name']}**: {it['location_str']}" for it in items]
                                parts.append("📍 **Oggetti fisici:**\n" + "\n".join(lines))
                            rep = "\n\n".join(parts) if parts else "Nel caveau non sono presenti documenti o oggetti memorizzati al momento."
                            return ChatResponse(reply=rep, action="list_vault_contents", data=l_res, documents=docs[:5])

                    if is_deadline_request:
                        d_res = self.execute_tool("get_upcoming_deadlines", {}, db=db, thread_id=thread_id)
                        docs = d_res.get("deadlines") or d_res.get("upcoming_documents", [])
                        if docs:
                            lines = []
                            for d in docs[:5]:
                                urg = f" - ⚠️ {d['urgency_label']}" if d.get('urgency_label') else ""
                                lines.append(f"- 📄 **{d['title']}** — {d.get('amount','?')} € scad. {d.get('due_date','?')}{urg}")
                            rep = "📅 Ecco le tue scadenze in sospeso:\n\n" + "\n".join(lines)
                        else:
                            rep = "✅ Non ci sono scadenze o pagamenti in sospeso al momento."
                        return ChatResponse(reply=rep, action="get_upcoming_deadlines", data=d_res, documents=docs)

                    # Se il modello ha risposto direttamente senza tool_calls (es. usando la cronologia chat),
                    # ma l'utente chiedeva un documento o la risposta ne cita uno, recuperiamo e alleghiamo il widget del file!
                    is_doc_intent = any(k in lower_t for k in [
                        "document", "file", "mutuo", "bollett", "fattur", "contratt", "certificat",
                        "f24", "730", "dichiarazion", "ricevut", "cedolin", "busta paga", "patente", "carta", "estratto",
                        "dammi", "mostra", "apri", "fammi vedere", "scarica", "vedi", "prendi"
                    ]) or any(k in direct_reply.lower() for k in [
                        "documento", "estratto conto", "bolletta", "fattura", "certificato", "allegato", "730", "f24"
                    ])

                    fallback_docs = None
                    s_res = None
                    is_list_query = any(k in lower_t for k in ["elenc", "lista", "tutti", "tutte", "quali", "cosa c'è", "cosa hai", "tutto il", "archivio"])
                    if is_doc_intent and not is_list_query:
                        s_res = self.execute_tool("search_vault", {"query": user_text}, db=db, thread_id=thread_id)
                        f_docs = s_res.get("found_documents", [])
                        if f_docs:
                            fallback_docs = filter_relevant_documents(f_docs, direct_reply, user_text)

                    return ChatResponse(
                        reply=direct_reply,
                        action="search_vault" if fallback_docs else "REPLY",
                        data=s_res if fallback_docs else None,
                        documents=fallback_docs
                    )

        except Exception as e:
            logger.error(f"Errore Agentic loop: {e}")
            return self._fallback_deterministic_response(user_text, lower_t, db, thread_id)

        # Se la chiamata non ha restituito 200 o non è riuscita
        return self._fallback_deterministic_response(user_text, lower_t, db, thread_id)

    def _fallback_deterministic_response(self, user_text: str, lower_t: str, db: Session, thread_id: str) -> ChatResponse:
        """Fallback locale robusto per memorizzazione, ricerca e scadenze in caso di rate-limit API o disconnessione."""
        # 0. Rinomina documento / foto
        if any(k in lower_t for k in ["chiamalo", "chiamala", "rinomina", "salvalo come", "salvala come", "dagli il nome", "dalle il nome", "dai il nome"]):
            new_title = self._extract_rename_title(user_text)
            if new_title:
                r_out = self.execute_tool("rename_vault_document", {"new_title": new_title}, db=db, thread_id=thread_id)
                if r_out.get("success"):
                    return ChatResponse(
                        reply=f"✅ Ho rinominato il file in '**{r_out['new_title']}**'!",
                        action="rename_vault_document",
                        data=r_out,
                        documents=r_out.get("documents")
                    )

        # 1. Memorizzazione o modifica posizione fisica
        item_n, loc_n = self._extract_item_and_location(user_text)
        if item_n and loc_n:
            db_res = self.execute_tool("store_physical_item", {"item_name": item_n, "primary_location": loc_n}, db, thread_id=thread_id)
            return ChatResponse(reply=f"✅ Memorizzato! Ho salvato la posizione di '{item_n}' in: {loc_n}.", action="store_physical_item", data=db_res)

        # 2. Data e ora odierna
        if any(k in lower_t for k in ["che giorno è", "che giorno e", "data di oggi", "quanti ne abbiamo", "che data è", "che data e", "data odierna", "che ore sono"]):
            d_info = get_current_date_info()
            return ChatResponse(
                reply=f"📅 Oggi è **{d_info['formatted_italian']}** (ore {d_info['current_time']}).",
                action="get_current_date",
                data=d_info
            )

        # 3. Scadenze in sospeso
        if any(k in lower_t for k in ["scadenz", "da pagare", "quanto devo pagare", "cosa scade"]):
            t_out = self.execute_tool("get_upcoming_deadlines", {}, db, thread_id=thread_id)
            docs = t_out.get("deadlines") or t_out.get("upcoming_documents", [])
            if docs:
                lines = []
                for d in docs[:5]:
                    urg = f" - ⚠️ {d['urgency_label']}" if d.get('urgency_label') else ""
                    lines.append(f"- 📄 **{d['title']}** — {d.get('amount','?')} € scad. {d.get('due_date','?')}{urg}")
                return ChatResponse(reply="📅 Ecco le tue scadenze in sospeso:\n\n" + "\n".join(lines), action="get_upcoming_deadlines", data=t_out, documents=docs)
            return ChatResponse(reply="✅ Non ci sono scadenze o pagamenti in sospeso al momento.", action="get_upcoming_deadlines", data=t_out)

        # 4. Liste o elenchi del caveau
        is_list = (
            any(k in lower_t for k in [
                "lista", "elenco", "elencami", "quali documenti", "quali oggetti",
                "mostrami tutti", "mostrami tutte", "mostra tutti", "mostra tutte",
                "cosa c'è nel caveau", "cosa ce nel caveau", "cosa ho nel caveau", "cosa hai nel caveau",
                "vedere tutti", "vedere tutte", "tutti i documenti", "tutti gli oggetti", "che oggetti", "che documenti"
            ])
            or lower_t.strip(" !.?") in ["documenti", "oggetti", "tutti i documenti", "tutti gli oggetti", "tutto", "i miei documenti", "i miei oggetti"]
        )
        if is_list:
            target = "physical_items" if any(k in lower_t for k in ["oggett", "cose"]) else ("documents" if any(k in lower_t for k in ["document", "file", "bollett", "fattur"]) else "all")
            l_res = self.execute_tool("list_vault_contents", {"target_type": target}, db=db, thread_id=thread_id)
            if target == "physical_items":
                items = l_res.get("physical_items", [])
                if items:
                    lines = [f"- 📍 **{it['item_name']}**: {it['location_str']}" for it in items]
                    rep = "📍 Ecco gli oggetti fisici memorizzati nel caveau:\n\n" + "\n".join(lines)
                else:
                    rep = "Nel caveau non sono presenti oggetti fisici memorizzati al momento. Dimmi pure dove riponi i tuoi oggetti e li registrerò subito! 📍"
                return ChatResponse(reply=rep, action="list_vault_contents", data=l_res)
            elif target == "documents":
                docs = l_res.get("documents", [])
                if docs:
                    lines = [f"- 📄 **{d['title']}** ({d.get('issuer', '')})" for d in docs]
                    rep = f"📄 Ecco i {len(docs)} documenti presenti nel caveau:\n\n" + "\n".join(lines)
                else:
                    rep = "Nel caveau non sono presenti documenti archiviati al momento."
                return ChatResponse(reply=rep, action="list_vault_contents", data=l_res, documents=docs[:5])
            else:
                items = l_res.get("physical_items", [])
                docs = l_res.get("documents", [])
                parts = []
                if docs:
                    lines = [f"- 📄 **{d['title']}** ({d.get('issuer', '')})" for d in docs]
                    parts.append("📄 **Documenti:**\n" + "\n".join(lines))
                if items:
                    lines = [f"- 📍 **{it['item_name']}**: {it['location_str']}" for it in items]
                    parts.append("📍 **Oggetti fisici:**\n" + "\n".join(lines))
                rep = "\n\n".join(parts) if parts else "Nel caveau non sono presenti documenti o oggetti memorizzati al momento."
                return ChatResponse(reply=rep, action="list_vault_contents", data=l_res, documents=docs[:5])

        # 4. Ricerca intelligente nel caveau (oggetti fisici e documenti)
        search_q = re.sub(
            r"^(?:dov'è|dov'e|dove ho messo|dove sono|dove|cerca|trovami|trova|dammi|mostrami|apri|visualizza|prendi)\s*(?:il|la|lo|le|i|l'|un|una|uno)?\s*",
            "", lower_t
        ).strip(" ?.")
        clean_q = search_q or user_text
        if len(clean_q) >= 2:
            s_res = self.execute_tool("search_vault", {"query": clean_q}, db=db, thread_id=thread_id)
            f_docs = s_res.get("found_documents", [])
            f_items = s_res.get("found_physical_items", [])
            if f_docs:
                d = f_docs[0]
                amt_str = f" ({d['amount']:.2f} €)" if d.get('amount') else ""
                due_str = f" - scadenza: {d['due_date']}" if d.get('due_date') else ""
                return ChatResponse(
                    reply=f"📄 Ho trovato il documento **{d['title']}**{amt_str}{due_str}:\n💡 {d.get('summary', '')}",
                    action="search_vault",
                    data=s_res,
                    documents=[d]
                )
            if f_items:
                it = f_items[0]
                loc = it['primary_location'] + (f" ({it['detailed_location']})" if it.get('detailed_location') else "")
                return ChatResponse(reply=f"📍 Il tuo {it['item_name']} si trova in: {loc}.", action="search_vault", data=s_res)

        return ChatResponse(
            reply=f"Non ho trovato nessun documento o oggetto corrispondente a '{user_text}' nel tuo caveau. Puoi chiedermi dove si trova un oggetto, cercare un documento o verificare le scadenze!",
            action="REPLY"
        )
