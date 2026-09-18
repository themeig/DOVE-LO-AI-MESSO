import json
import logging
import re
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
import httpx
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.config import get_settings
from app.models.database import (
    Document,
    PhysicalItem,
    ChatMessage,
    ChatThread,
    get_app_setting,
    UIEvent,
    WatchedFolder,
    GoogleDriveCredential,
)
from app.models.schemas import ChatResponse
from app.services.ai_service import get_ai_service, MockAIService
from app.services.drive_service import resolve_drive_folder_path
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
                    "category": {"type": "string", "description": "Categoria opzionale dell'oggetto"},
                    "document_id": {"type": "integer", "description": "ID numerico opzionale di un documento o foto salvato nel caveau da collegare a questo oggetto"},
                    "document_title": {"type": "string", "description": "Titolo opzionale del documento o foto da associare"}
                },
                "required": ["item_name", "primary_location"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "link_document_to_item",
            "description": (
                "Collega un documento, foto o allegato presente nel caveau a un oggetto fisico memorizzato "
                "(es. 'ti allego una foto per il piano', 'ecco la foto per il passaporto', 'associa questa foto alle chiavi di scorta', 'collega la foto al piano'). "
                "Consente di mostrare direttamente l'immagine della posizione quando l'utente chiede dove si trova l'oggetto."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {"type": "string", "description": "Nome dell'oggetto fisico a cui associare la foto/documento (es. 'Piano', 'Chiavi di scorta', 'Passaporto')"},
                    "item_id": {"type": "integer", "description": "ID dell'oggetto fisico se già noto"},
                    "document_id": {"type": "integer", "description": "ID numerico del documento/foto da associare (se omesso, fa riferimento all'ultimo documento caricato)"},
                    "document_title": {"type": "string", "description": "Titolo o parola chiave del documento/foto da associare"}
                },
                "required": ["item_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_upcoming_deadlines",
            "description": (
                "Recupera lo scadenzario delle bollette, tributi o pagamenti in sospeso da pagare registrati nel caveau. "
                "Se l'utente chiede la scadenza di un documento specifico (es. patente, carta d'identità, passaporto, garanzia, contratto), "
                "puoi indicare il parametro 'query' (es. 'patente') oppure usare direttamente search_vault."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Filtro opzionale per cercare la scadenza di un documento, persona o categoria specifica (es. 'patente', 'garanzia', 'mario rossi', 'luce')"
                    }
                }
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
            "description": "Predispone il widget di conferma interattivo per eliminare uno o più documenti o oggetti dal caveau (anche eliminazione multipla o totale, come 'elimina tutti i documenti', 'cancella tutte le bollette', 'elimina tutti', 'elimina il file X'). Richiede sempre la conferma dell'utente prima di cancellare.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_type": {
                        "type": "string",
                        "enum": ["document", "physical_item", "bulk_documents"],
                        "description": "Tipo di record: 'document' per singolo file, 'physical_item' per singola posizione, 'bulk_documents' per cancellare più o tutti i documenti."
                    },
                    "target_id": {
                        "type": "integer",
                        "description": "ID numerico dell'elemento (se singolo)"
                    },
                    "target_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Lista opzionale di ID dei documenti da eliminare in blocco"
                    },
                    "title": {
                        "type": "string",
                        "description": "Titolo dell'elemento o descrizione del gruppo (es. 'Tutti i documenti', 'Tutte le bollette', 'Bolletta Enel')"
                    },
                    "category": {
                        "type": "string",
                        "description": "Filtro categoria opzionale per eliminazione multipla (es. 'bolletta', 'f24', 'all')"
                    }
                },
                "required": ["target_type", "title"]
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
    },
    {
        "type": "function",
        "function": {
            "name": "show_document_card",
            "description": (
                "Mostra all'utente una o più schede grafiche interattive (widget) di documenti o file con anteprima e pulsanti reali per visualizzarlo ('Vedi') e scaricarlo ('Scarica'). "
                "DEVI SEMPRE chiamare questo strumento quando l'utente cerca documenti, chiede di visualizzare, vedere, aprire, consultare o scaricare file "
                "(es. 'dammi i documenti di identità', 'ok voglio scaricarla', 'voglio fare il download', 'scaricali entrambi', 'entrambi', 'si di entrambi', 'apri il documento'). "
                "Supporta l'invio simultaneo di più documenti contemporaneamente tramite 'document_ids' o 'document_titles'. "
                "DIVIETO ASSOLUTO di scrivere che l'utente deve farlo singolarmente: questo strumento genera le card grafiche con il pulsante per scaricare ciascun file!"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "document_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Lista di ID numerici dei documenti da mostrare (es. per 'entrambi', 'tutti' o più documenti)"
                    },
                    "document_id": {
                        "type": "integer",
                        "description": "ID numerico del singolo documento da mostrare"
                    },
                    "document_titles": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Lista di titoli o nomi dei documenti da mostrare (es. ['Tessera Sanitaria Italiana', 'Ricevuta Pre-Immatricolazione Università di Pavia'])"
                    },
                    "document_title": {
                        "type": "string",
                        "description": "Titolo, nome o parola chiave del documento se l'ID non è noto (es. 'Tessera Sanitaria', 'F24')"
                    },
                    "query": {
                        "type": "string",
                        "description": "Termine di ricerca alternativo per individuare il documento nel caveau"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scan_local_folder",
            "description": (
                "Esegue la scansione e l'indicizzazione dei documenti (PDF, immagini, fatture, ricevute) da una cartella sul computer dell'utente o da tutte le cartelle monitorate. "
                "DEVI chiamarlo quando l'utente chiede di scansionare cartelle, indicizzare file dal PC o cercare nuovi documenti locali (es. 'scansiona le mie cartelle', 'indicizza la cartella C:\\Fatture', 'ho messo nuovi file nel PC, aggiorna')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "folder_path": {
                        "type": "string",
                        "description": "Percorso opzionale della cartella sul PC da scansionare (se omesso o 'all', scansiona tutte le cartelle monitorate)"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_watched_folders",
            "description": "Elenca tutte le cartelle del computer attualmente monitorate e indicizzate da Dove lo AI messo (es. 'quali cartelle del mio computer stai vedendo?', 'elenco cartelle collegate').",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_local_file_in_explorer",
            "description": "Apre direttamente un file o una cartella in Esplora File di Windows (File Explorer) evidenziando il file sul computer dell'utente (es. 'apri la cartella del contratto su Windows', 'apri il file in esplora risorse', 'mostrami dov'è salvato sul computer').",
            "parameters": {
                "type": "object",
                "properties": {
                    "document_title": {
                        "type": "string",
                        "description": "Titolo o nome del documento da aprire in Esplora File"
                    },
                    "document_id": {
                        "type": "integer",
                        "description": "ID numerico del documento se già noto"
                    },
                    "path": {
                        "type": "string",
                        "description": "Percorso esatto su disco se noto"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_zip_archive",
            "description": (
                "Crea e comprime uno o più documenti del caveau in un nuovo file archivio .ZIP scaricabile. "
                "DEVI chiamarlo quando l'utente chiede di creare un archivio zip, comprimere documenti, pacchetti di fatture o esportare un gruppo di file compressi "
                "(es. 'creami uno zip con tutte le bollette', 'fai uno zip dei documenti del 2026', 'comprimi le ricevute in un file zip', 'crea un archivio zip dei contratti')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Termine di ricerca o filtro per selezionare i documenti da includere nello zip (es. 'bolletta', 'fisco', 'enel', '2026', 'tutti')"
                    },
                    "category": {
                        "type": "string",
                        "description": "Categoria specifica di documenti (es. 'bolletta', 'f24', 'contratto', 'all')"
                    },
                    "archive_name": {
                        "type": "string",
                        "description": "Nome del file zip da generare (es. 'Archivio_Bollette_2026.zip')"
                    },
                    "document_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Lista opzionale di ID numerici dei documenti da includere nello zip"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "unzip_vault_archive",
            "description": (
                "Estrae e scompatta un file archivio .ZIP presente nel caveau, indicizzando automaticamente tutti i documenti, immagini, fogli Excel e file Word al suo interno. "
                "DEVI chiamarlo quando l'utente chiede di estrarre, scompattare o fare l'unzip di un file compresso "
                "(es. 'scompatta il file zip che ho caricato', 'estrai l'archivio fatture.zip', 'fai l'unzip dello zip', 'estrai tutti i file dallo zip')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "integer",
                        "description": "ID numerico del documento ZIP da scompattare se noto"
                    },
                    "document_title": {
                        "type": "string",
                        "description": "Nome o titolo dell'archivio ZIP da cercare ed estrarre (es. 'archivio.zip', 'fatture')"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_google_drive_status",
            "description": (
                "Recupera lo stato attuale della connessione Google Drive Cloud Sync, la modalità di archiviazione "
                "('dual' = locale + cloud, o 'cloud_only' = solo Google Drive), l'account Google associato, "
                "e l'elenco dei documenti e file sincronizzati su Google Drive con la relativa cartella (es. 'DoveLoAIMesso / 2026 / Bollette & Utenze / ...' "
                "o 'DoveLoAIMesso / Documenti & Foto / ...') e il link diretto di apertura [Drive ↗]. "
                "Usalo SEMPRE quando l'utente chiede cosa c'è su Google Drive, come hai organizzato le cartelle su Drive, "
                "o chiede di cercare documenti salvati su Google Drive."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Termine opzionale di ricerca per filtrare file o cartelle su Google Drive"
                    }
                }
            }
        }
    }
]

SYSTEM_PROMPT = """================================================================================
IDENTITÀ, AMBIENTE OPERATIVO E INTERFACCIA UTENTE (DOVE SEI E COME FUNZIONI):
================================================================================
1. DOVE TI TROVI:
   - Sei l'assistente AI nativo integrato nell'applicazione desktop "Dove lo AI messo", un caveau intelligente per famiglie e professionisti.
   - Sei in dialogo diretto con l'utente all'interno di un'interfaccia fedele a WhatsApp Web (con bolle di chat e dashboard).
   - I documenti memorizzati nel database SQLite sono file reali (PDF e immagini) salvati sul server locale (`/uploads/...`) pronti per essere aperti o scaricati.

2. COME FUNZIONANO LE SCHEDE DOCUMENTO E I DOWNLOAD:
   - Quando chiami lo strumento `show_document_card` o restituisci documenti nel campo `documents`, la chat di WhatsApp genera automaticamente sotto la tua bolla di testo delle VERE SCHEDE GRAFICHE INTERATTIVE (widget arrotondati).
   - Ciascuna scheda mostra: icona del file (PDF rosso o immagine blu), titolo, mittente, importo, data di scadenza e DUE PULSANTI REALI:
     * [👁️ Vedi]: apre l'anteprima istantanea a schermo intero del documento.
     * [⬇️ Scarica]: scarica direttamente il file originale sul dispositivo (computer o smartphone) dell'utente.

3. COSA DEVI FARE (OBBLIGHI E REGOLE TASSATIVE - NLU PROATTIVA & RIDUZIONE DEI PASSAGGI):
   - QUANDO L'UTENTE CHIEDE DOCUMENTI, VUOLE VEDERLI O SCARICARLI (es. "dammi i documenti di identità", "mostrami la tessera", "voglio fare il download", "scarica", "scaricali", "entrambi"):
     DEVI SEMPRE E SUBITO INVOCARE `show_document_card` O ALLEGARE TUTTE LE SCHEDE!
   - PROATTIVITÀ MULTI-SCHEDA (DIVIETO DI CONFERME INUTILI): Se una ricerca (`search_vault`) o richiesta restituisce un numero limitato di risultati altamente pertinenti (es. 2-3 documenti come Tessera Sanitaria e Ricevuta per l'identificazione), DEVI INVOCARE `show_document_card` PER TUTTI I RISULTATI IN AUTOMATICO.
   - DIVIETO ASSOLUTO DI CHIEDERE IL PERMESSO O FARE DOMANDE SUPERFLUE: MAI chiedere "Quale vuoi?", "Quale preferisci?", "Desideri che ti mostri la scheda di uno in particolare?", "Quale desideri scaricare?". Questo aggiunge passaggi inutili e contrari all'esperienza d'uso. MOSTRA SUBITO LE SCHEDE DI TUTTI I DOCUMENTI PERTINENTI!
   - GESTIONE COLLETTIVA DI "SCARICALI", "ENTRAMBI", "TUTTI E DUE", "TUTTI", "SI DI ENTRAMBI": Se l'utente dice "scaricali", "scaricale", "scaricalo", "entrambi", "tutti e due", "tutti", "mostrali tutti", "download" subito dopo che hai elencato dei documenti, capisci immediatamente che si riferisce a TUTTI quelli appena menzionati e mostra le schede per tutti contemporaneamente!
   - DIVIETO ASSOLUTO DI DIRE "dovrai farlo singolarmente": l'interfaccia supporta l'invio contemporaneo di 2, 3 o più schede contemporaneamente con il rispettivo pulsante di download su ciascuna!
   - DIVIETO ASSOLUTO DI RISPONDERE SOLO A PAROLE: l'utente NON può cliccare sulle tue frasi per scaricare un file. Ha bisogno della CARD GRAFICA con il pulsante [Scarica]!

REGOLE OPERATIVE:
0. PRIMATO ASSOLUTO DEL DATABASE SULLA CHAT (DATI REALI > CONTESTO):
   - Hai a disposizione l'intera cronologia della conversazione e l'inventario in tempo reale del database: usali per comprendere il contesto, ricordare preferenze e richieste pregresse.
   - Per quanto riguarda l'ESISTENZA e la POSIZIONE ATTUALE di un documento o di un oggetto, la sola fonte di verità sono i DATI REALI DEL DATABASE SQLite. Se un elemento non è nel database, dichiara chiaramente che non è presente nel caveau.

1. QUANDO L'UTENTE CHIEDE DI UN FILE O DOCUMENTO (es. "dammi 730", "dammi i documenti di identità", "mostrami la bolletta", "cerca il certificato"):
   - DEVI SEMPRE USARE `search_vault` o `show_document_card`!
   - Mostra e riassumi subito le informazioni trovate e allega SEMPRE le relative schede documento!
   - Se ci sono più documenti pertinenti (es. Tessera Sanitaria e Ricevuta Pavia per l'identificazione), mostrali e fornisci le schede per entrambi!

2. QUANDO L'UTENTE CHIEDE DOVE SI TROVA UN OGGETTO (es. "dov'è il passaporto?", "dove ho messo le chiavi?"):
   - DEVI SEMPRE USARE lo strumento `search_vault`!
   - Basa la risposta solo su ciò che restituisce `search_vault` dal database in tempo reale.
   - Se l'oggetto ha una foto collegata nel caveau, l'anteprima verrà mostrata automaticamente nella chat.

3. QUANDO L'UTENTE COMUNICA, MODIFICA, SPOSTA O AGGIORNA LA POSIZIONE DI UN OGGETTO:
   - DEVI SEMPRE USARE lo strumento `store_physical_item`!

4. QUANDO L'UTENTE CHIEDE DELLE SCADENZE O COSA DEVE PAGARE:
   - USA lo strumento `get_upcoming_deadlines`.

5. QUANDO L'UTENTE CHIEDE DI ELIMINARE O CANCELLARE:
   - Per eliminare un singolo elemento: cerca con `search_vault` e chiama `delete_vault_record(target_type='document' o 'physical_item', target_id=..., title=...)`.
   - Per eliminare tutti i documenti o una specifica categoria/gruppo per nome (es. 'elimina tutti i 730 test', 'elimina tutte le ricevute', 'cancella tutte le bollette', 'elimina tutti i documenti'): chiama `delete_vault_record(target_type='bulk_documents', title=..., category=...)`.
   - Questo genera l'apposita card di conferma interattiva con i pulsanti per confermare o annullare l'eliminazione in sicurezza!

6. STILE DI RISPOSTA:
   - Italiano naturale, cortese, chiaro e conciso in stile WhatsApp (emoji 📄, 📍, 💡, ✅, 📸).
   - MAI identificativi tecnici di database (come "ID 83", "chiave primaria").

7. DATA ODIERNA E CONTESTO TEMPORALE:
   - Conosci sempre la data odierna iniettata nel contesto e calcola con precisione giorni rimanenti o ritardi.

8. DISTINZIONE ESSENZIALE LISTA DOCUMENTI VS OGGETTI FISICI:
   - Se chiede lista documenti: `list_vault_contents(target_type="documents")`.
   - Se chiede lista oggetti fisici: `list_vault_contents(target_type="physical_items")`.

9. QUANDO L'UTENTE CHIEDE DI RINOMINARE UN FILE/FOTO:
   - Chiama `rename_vault_document(new_title=...)`.

10. QUANDO L'UTENTE CHIEDE DI SCARICARE O VEDERE UN DOCUMENTO:
    - Di norma, DIVIETO DI SCRIVERE FINTI LINK MARKDOWN e CHIAMA SEMPRE `show_document_card`! L'interfaccia WhatsApp mostrerà all'utente la scheda interattiva con i pulsanti [👁️ Vedi] e [⬇️ Scarica].
    - GESTIONE RESILIENTE SEGNALAZIONI UI: Se la telemetria UI del client segnala un errore di visualizzazione o se l'utente riferisce esplicitamente di non vedere il pulsante/scheda, riconosci l'inconveniente tecnico e fornisci come riserva il percorso/link di download diretto reale di sistema (es. `/api/documents/{id}/download`).

11. QUANDO L'UTENTE CARICA O ASSOCIA UNA FOTO/ALLEGATO A UN OGGETTO FISICO (es. 'ti allego la foto per il piano', 'ecco la foto delle chiavi', 'associa questa foto al passaporto'):
    - DEVI USARE `link_document_to_item(item_name=...)` per collegare istantaneamente il documento/foto alla posizione dell'oggetto fisico nel caveau!
    - Conferma sempre all'utente che la foto è stata collegata e che verrà mostrata quando chiederà dove si trova l'oggetto.

12. SCANSIONE E MONITORAGGIO CARTELLE DEL COMPUTER:
    - Se l'utente chiede di scansionare cartelle, monitorare directory o indicizzare nuovi file dal PC: USA `scan_local_folder(folder_path=...)` o `list_watched_folders()`.
    - Riassumi quanti nuovi documenti sono stati trovati e aggiunti al caveau.

13. APERTURA DI FILE IN ESPLORA RISORSE DI WINDOWS:
    - Se l'utente chiede di aprire la cartella originale o il file su Windows (es. 'apri il contratto su Windows', 'mostrami la cartella in esplora risorse'): USA `open_local_file_in_explorer(document_title=...)`.

14. CREAZIONE ARCHIVI ZIP COMPRESSI (create_zip_archive):
    - Se l'utente chiede di creare un file zip, comprimere documenti, raggruppare bollette, fatture, ricevute o documenti in un unico archivio (es. 'creami uno zip con tutte le bollette', 'fai uno zip dei documenti 2026', 'puoi zippare i file?', 'comprimi le fatture'): DEVI SEMPRE USARE LO STRUMENTO `create_zip_archive(query=..., category=..., archive_name=...)`!
    - NON DIRE MAI che non hai la funzionalità di creare zip: possiedi lo strumento nativo `create_zip_archive` integrato!

15. ESTRAZIONE E DECOMPRESSIONE ARCHIVI (unzip_vault_archive):
    - Se l'utente chiede di estrarre, scompattare o fare l'unzip di un file .zip presente nel caveau (es. 'scompatta il file zip che ho caricato', 'estrai l'archivio fatture.zip', 'fai l'unzip dello zip', 'estrai tutti i file'): DEVI SEMPRE USARE LO STRUMENTO `unzip_vault_archive(document_title=..., document_id=...)`!
    - Tutti i file estratti (PDF, immagini, documenti Word, fogli Excel) verranno analizzati con l'AI e catalogati automaticamente nel caveau.

16. INTEGRAZIONE GOOGLE DRIVE CLOUD SYNC & ARCHIVIAZIONE CLOUD:
    - L'applicazione "Dove lo AI messo" include la sincronizzazione con Google Drive Cloud Sync (tramite API ufficiale Google con scope sicuro `drive.file`).
    - L'utente può collegare Google Drive dal menu "Strumenti -> ☁️ Google Drive Cloud Sync" o aprire direttamente qualsiasi documento cliccando sul pulsante [Drive ↗] visibile nella scheda del documento.
    - MODALITÀ DI ARCHIVIAZIONE DISPONIBILI:
      * "dual" (Copia locale cifrata nel caveau + Google Drive): conserva sia il file cifrato locale nel caveau, sia la copia organizzata su Google Drive.
      * "cloud_only" (Solo Google Drive): il file fisico originale risiede unicamente su Google Drive (zero file locali su disco); nel caveau locale rimangono i metadati, l'estrazione AI e il link diretto `drive_web_url`.
    - STRUTTURA AD ALBERO DELLE CARTELLE SU GOOGLE DRIVE:
      Tutti i file sincronizzati su Drive sono archiviati in modo strutturato dentro la cartella principale `DoveLoAIMesso`:
      * Con data di scadenza (es. bollette, F24, tributi, rate): `DoveLoAIMesso / <Anno> / <Categoria> / <NomeFile>` (es. `DoveLoAIMesso/2026/Bollette & Utenze/2026-10-28_Enel_64.20eur.pdf`).
      * Senza data di scadenza (es. ricevute generiche, credenziali, contratti, certificati, foto): `DoveLoAIMesso / <Categoria> / <NomeFile>` (es. `DoveLoAIMesso/Documenti & Foto/client_secret_...json`).
      * Categorie cartella standard:
        - `Bollette & Utenze` (bollette luce, gas, acqua, utenze)
        - `Fisco & Tasse` (F24, tributi, modello unico, tasse)
        - `Fatture & Spese` (fatture, ricevute d'acquisto, scontrini)
        - `Contratti & Polizze` (contratti d'affitto, lavoro, polizze, assicurazioni)
        - `Documenti & Foto` (credenziali, documenti personali, foto)
    - QUANDO L'UTENTE CHIEDE DI GOOGLE DRIVE (es. 'cosa c'è su Drive?', 'come hai organizzato le cartelle su Drive?', 'cerca su Drive', 'è salvato su Drive?'):
      * DEVI SEMPRE USARE LO STRUMENTO `get_google_drive_status` o `search_vault`!
      * Conosci lo stato di sincronizzazione, la modalità attiva (solo Drive o duale) e l'account Google associato.
      * Spiega con precisione all'utente come sono organizzate le cartelle su Google Drive, quali file sono stati salvati e in quali cartelle, e che può aprirli su Drive cliccando su [Drive ↗].
      * MAI DIRE "Non posso accedere a Google Drive" o "Non ho la capacità di connettermi a Google Drive": l'integrazione Google Drive Cloud Sync è parte fondamentale dell'app e ne conosci lo stato reale in tempo reale!
"""

def strip_tool_tags(text: str) -> str:
    """Rimuove qualsiasi tag <tool_call>...</tool_call>, blocchi di thinking <thought>...</thought> o residui XML di chiamata tool."""
    if not text:
        return ""
    cleaned = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<tool_call>.*?</tool_call>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<function=.*?</function>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<parameter=.*?</parameter>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"</?(?:thought|think|tool_call|function|parameter|arg_key|arg_value)[^>]*>", "", cleaned, flags=re.IGNORECASE)
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
        title_match = (title and title in asst_lower) or (title_words and sum(1 for w in title_words if w in asst_lower) >= max(1, len(title_words) * 0.5))
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
    # oppure se l'assistente risponde indicando una posizione fisica (📍 o 'si trova in'):
    # se c'è una foto collegata all'oggetto (📸 o 'foto' o physical_item_id), allegala! Altrimenti non allegare documenti non correlati.
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
        for w in ["i", "gli", "le", "tutti", "tutte", "entrambi", "entrambe", "elenco", "elencami", "lista", "quali"]
    )
    if is_singular_request and len(docs) > 0:
        top_title = (docs[0].get("title") or "").lower()
        top_words = [w for w in re.split(r"[^\w]+", top_title) if len(w) > 3 and w not in ITALIAN_STOPWORDS]
        user_asks_doc = any(k in user_lower for k in ["document", "file", "bollett", "fattur", "contratt", "certificat", "ricevut", "cedolin", "patente", "carta", "f24", "730", "estratto"])
        user_mentions_title = any(w in user_lower for w in top_words)
        if user_mentions_title or user_asks_doc:
            return [docs[0]]

    # 5. Se l'utente ha esplicitamente richiesto documenti o una ricerca documenti (proattività per 1-4 documenti)
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
            d_words = [w for w in re.split(r"[^\w]+", f"{d_tit} {d_iss} {d_type}") if len(w) > 2 and w not in ITALIAN_STOPWORDS]
            if any(w in user_lower or w in asst_lower for w in d_words):
                matched_relevant.append(d)
        if matched_relevant:
            if is_singular_request:
                return [matched_relevant[0]]
            return matched_relevant[:4]

    return None


class AgenticChatService:
    def __init__(self):
        self.settings = get_settings()

    def get_recent_ui_events(self, db: Session, thread_id: str = "general", minutes: int = 10) -> List[UIEvent]:
        """Recupera gli ultimi eventi di telemetria UI per il thread specificato."""
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
            events = (
                db.query(UIEvent)
                .filter(UIEvent.thread_id == thread_id)
                .filter(UIEvent.created_at >= cutoff)
                .order_by(UIEvent.id.desc())
                .limit(5)
                .all()
            )
            return events
        except Exception as e:
            logger.warning(f"Errore recupero eventi UI recenti: {e}")
            return []

    def _build_ui_telemetry_prompt_note(self, db: Session, thread_id: str = "general") -> Optional[str]:
        """Genera un blocco di istruzioni contestuali basate sullo stato di salute e telemetria del client."""
        events = self.get_recent_ui_events(db, thread_id=thread_id, minutes=10)
        if not events:
            return None

        lines = []
        for ev in events:
            doc_id = ev.target_id
            doc_title = ev.title or "Documento"
            dl_path = f"/api/documents/{doc_id}/download" if doc_id else "/api/dashboard"
            lines.append(
                f"- Evento: {ev.event_type} per '{doc_title}' (ID: {doc_id or 'N/D'}). "
                f"Dettaglio: {ev.error_details or 'Errore rendering client'}. "
                f"Link di download diretto reale: {dl_path}"
            )

        note = (
            "================================================================================\n"
            "STATO TELEMETRIA UI CLIENT IN TEMPO REALE (FEEDBACK DAL FRONTEND):\n"
            "================================================================================\n"
            "L'interfaccia client ha registrato i seguenti eventi o errori tecnici recenti:\n"
            + "\n".join(lines) + "\n\n"
            "ISTRUZIONE RESILIENTE:\n"
            "- Se l'utente ti dice che non vede il pulsante, non vede la scheda o non riesce ad aprire/scaricare il file:\n"
            "  1. Riconosci cortesemente che si è verificato un inconveniente temporaneo di visualizzazione nella chat.\n"
            "  2. Fornisci SUBITO il link diretto di download alternativo (es. `/api/documents/{id}/download` o pulsante nella Dashboard).\n"
            "  3. Non limitarti a ripetere frasi generiche o a riprovare alla cieca senza fornire il link diretto di salvataggio!"
        )
        return note

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

        def _clean_and_validate(it: Optional[str], lc: Optional[str]) -> tuple[Optional[str], Optional[str]]:
            if not it or not lc:
                return None, None
            clean_it = it.strip(" .?!\"'[]:;,*`")
            clean_lc = lc.strip(" .?!\"'[]:;,*`")
            # Ignora falsi positivi da messaggi di sistema, citazioni o domande meta
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

    def _extract_bulk_delete_target(self, text: str) -> tuple[bool, Optional[str]]:
        """
        Determina se la cancellazione multipla richiesta è un azzeramento totale del caveau
        oppure è mirata a un termine/categoria/gruppo specifico (es. '730 test', 'ricevute', 'bollette').
        Ritorna: (is_total_vault, target_keyword)
        """
        if not text:
            return True, None
        
        low = text.lower().strip()
        # 1. Rimuovi verbi di eliminazione e prefissi iniziali (forme lunghe prima per evitare match parziali)
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

        # 5. Se è rimasto un prefisso generico come "documenti di" o "file di" o solo "documenti", puliscilo se c'è altro testo
        clean_specific = re.sub(r"^(?:documenti|documento|file|allegati|oggetti|cose)\s*(?:di\s+|del\s+|della\s+|dei\s+|degli\s+|delle\s+|d\'|da\s+|per\s+)?", "", clean, flags=re.IGNORECASE).strip(" ?.")

        generic_terms = ["", "documenti", "documento", "file", "tutto", "tutti", "tutte", "caveau", "archivio", "dati", "elementi", "record", "allegati", "all", "bulk_documents", "cose", "oggetti"]
        if clean in generic_terms or clean_specific in generic_terms:
            return True, None

        return False, (clean_specific if clean_specific else clean)

    def _extract_link_photo_item(self, text: str) -> Optional[str]:
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
                        "filename": Path(d.file_path).name if d.file_path else "",
                        "file_url": f"/uploads/{Path(d.file_path).name}" if d.file_path else None,
                        "download_url": f"/api/documents/{d.id}/download",
                        "file_type": d.file_type,
                        "drive_file_id": d.drive_file_id,
                        "drive_web_url": d.drive_web_url,
                        "is_on_drive": bool(d.drive_file_id or d.drive_web_url)
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

            img_p = args.get("image_path")
            doc_id = args.get("document_id")
            doc_title = (args.get("document_title") or "").strip()

            linked_doc = None
            if doc_id:
                linked_doc = db.query(Document).filter(Document.id == doc_id).first()
            if not linked_doc and doc_title:
                s_docs = search_vault_documents(db, doc_title, thread_id=thread_id)
                if s_docs:
                    linked_doc = db.query(Document).filter(Document.id == s_docs[0]["id"]).first()

            if existing:
                existing.primary_location = prim_loc
                existing.detailed_location = det_loc
                if img_p:
                    existing.image_path = img_p
                if linked_doc:
                    existing.document_id = linked_doc.id
                    existing.image_path = linked_doc.file_path
                    linked_doc.physical_item_id = existing.id
                if thread_id:
                    existing.thread_id = thread_id
                item = existing
            else:
                item = PhysicalItem(
                    thread_id=thread_id,
                    item_name=item_name,
                    primary_location=prim_loc,
                    detailed_location=det_loc,
                    category=cat,
                    image_path=linked_doc.file_path if linked_doc else img_p,
                    document_id=linked_doc.id if linked_doc else None
                )
                db.add(item)
                db.flush()
                if linked_doc:
                    linked_doc.physical_item_id = item.id

            db.commit()
            db.refresh(item)

            loc_str = item.primary_location + (f" ({item.detailed_location})" if item.detailed_location else "")
            fn = Path(item.image_path).name if item.image_path else None
            return {
                "success": True,
                "item_id": item.id,
                "thread_id": item.thread_id,
                "item_name": item.item_name,
                "primary_location": item.primary_location,
                "detailed_location": item.detailed_location,
                "category": item.category,
                "location_str": loc_str,
                "document_id": item.document_id,
                "image_url": f"/api/files/{fn}" if fn else None,
                "has_photo": bool(item.image_path or item.document_id)
            }

        elif name == "link_document_to_item":
            item_name = (args.get("item_name") or "").strip()
            item_id = args.get("item_id")
            doc_id = args.get("document_id")
            doc_title = (args.get("document_title") or "").strip()
            img_path = args.get("image_path")

            # 1. Trova documento
            doc = None
            if doc_id:
                doc = db.query(Document).filter(Document.id == doc_id).first()
            if not doc and doc_title:
                s_docs = search_vault_documents(db, doc_title, thread_id=thread_id)
                if s_docs:
                    doc = db.query(Document).filter(Document.id == s_docs[0]["id"]).first()
            if not doc:
                q = db.query(Document)
                if thread_id and thread_id not in ["general", "all"]:
                    q = q.filter(Document.thread_id == thread_id)
                doc = q.order_by(Document.id.desc()).first()

            # 2. Trova o crea oggetto fisico
            item = None
            if item_id:
                item = db.query(PhysicalItem).filter(PhysicalItem.id == item_id).first()
            elif item_name:
                clean_name = re.sub(r"^(il|lo|la|i|gli|le|l'|un|uno|una|un')\s*", "", item_name, flags=re.IGNORECASE).strip()
                cap_name = (clean_name if clean_name else item_name).capitalize()
                item = db.query(PhysicalItem).filter(PhysicalItem.item_name.ilike(cap_name)).first()
                if not item and thread_id:
                    item = db.query(PhysicalItem).filter(PhysicalItem.thread_id == thread_id, PhysicalItem.item_name.ilike(cap_name)).first()
                if not item:
                    s_items = search_vault_items(db, cap_name, thread_id=thread_id)
                    if s_items:
                        item = db.query(PhysicalItem).filter(PhysicalItem.id == s_items[0]["item_id"]).first()

            if not item and item_name:
                clean_name = re.sub(r"^(il|lo|la|i|gli|le|l'|un|uno|una|un')\s*", "", item_name, flags=re.IGNORECASE).strip()
                cap_name = (clean_name if clean_name else item_name).capitalize()
                item = PhysicalItem(
                    thread_id=thread_id,
                    item_name=cap_name,
                    primary_location="Posizione da foto",
                    category="generico"
                )
                db.add(item)
                db.flush()

            if not item:
                return {"error": "Specificare un oggetto fisico valido a cui associare la foto/documento."}

            if doc:
                item.document_id = doc.id
                item.image_path = doc.file_path
                doc.physical_item_id = item.id
            elif img_path:
                item.image_path = img_path

            db.commit()
            db.refresh(item)

            fn = Path(item.image_path).name if item.image_path else (Path(doc.file_path).name if doc and doc.file_path else None)
            doc_info = {
                "id": doc.id if doc else None,
                "document_id": doc.id if doc else None,
                "title": doc.title if doc else f"Foto {item.item_name}",
                "issuer": doc.issuer if doc else None,
                "amount": doc.amount if doc else None,
                "due_date": doc.due_date.isoformat() if doc and doc.due_date else None,
                "summary": doc.summary if doc else f"Foto della posizione di {item.item_name}",
                "file_url": f"/uploads/{fn}" if fn else None,
                "download_url": f"/api/documents/{doc.id}/download" if doc else None,
                "file_type": doc.file_type if doc else "image"
            } if (doc or fn) else None

            loc_str = item.primary_location + (f" ({item.detailed_location})" if item.detailed_location else "")
            return {
                "success": True,
                "item_id": item.id,
                "item_name": item.item_name,
                "location_str": loc_str,
                "document_id": doc.id if doc else None,
                "document_title": doc.title if doc else None,
                "image_url": f"/api/files/{fn}" if fn else None,
                "has_photo": bool(item.image_path or item.document_id),
                "document": doc_info,
                "documents": [doc_info] if doc_info else []
            }

        elif name == "delete_vault_record":
            target_type = args.get("target_type")
            target_id = args.get("target_id")
            title = args.get("title", "")
            target_ids = args.get("target_ids") or []
            category = args.get("category")

            is_bulk = (
                target_type == "bulk_documents"
                or (target_type not in ["document", "physical_item"] and any(k in (title or "").lower() for k in ["tutt", "tutte"]))
                or bool(target_ids and len(target_ids) > 1)
            )

            if is_bulk:
                target_type = "bulk_documents"
                query = db.query(Document)
                if thread_id and thread_id != "general" and thread_id != "all":
                    query = query.filter(Document.thread_id == thread_id)

                clean_ref = f"{title or ''} {category or ''}".strip()
                is_total, target_kw = self._extract_bulk_delete_target(clean_ref)

                if target_ids:
                    query = query.filter(Document.id.in_(target_ids))
                    cat_name = f"{len(target_ids)} documenti selezionati"
                elif not is_total and target_kw:
                    s_matches = search_vault_documents(db, target_kw, thread_id=thread_id)
                    matched_ids = [m["id"] for m in s_matches]
                    stem_kw = it_stem(target_kw)
                    like_matches = query.filter(or_(
                        Document.title.ilike(f"%{target_kw}%"),
                        Document.doc_type.ilike(f"%{target_kw}%"),
                        Document.issuer.ilike(f"%{target_kw}%"),
                        Document.summary.ilike(f"%{target_kw}%"),
                        Document.title.ilike(f"%{stem_kw}%"),
                        Document.doc_type.ilike(f"%{stem_kw}%"),
                        Document.summary.ilike(f"%{stem_kw}%")
                    )).all()
                    for lm in like_matches:
                        if lm.id not in matched_ids:
                            matched_ids.append(lm.id)

                    if matched_ids:
                        query = query.filter(Document.id.in_(matched_ids))
                        cat_name = f"documenti corrispondenti a '{target_kw}'"
                    else:
                        return {
                            "error": f"Nessun documento trovato nel caveau corrispondente a '{target_kw}'.",
                            "status": "not_found"
                        }
                else:
                    cat_name = "tutti i documenti"

                docs_to_delete = query.all()
                if not docs_to_delete:
                    return {
                        "error": f"Nessun documento trovato da eliminare nel caveau ({cat_name}).",
                        "status": "not_found"
                    }

                doc_ids = [d.id for d in docs_to_delete]
                doc_titles = [d.title for d in docs_to_delete]
                conf_title = title if (title and "tutt" in title.lower() and is_total) else (f"I {len(doc_ids)} {cat_name}" if len(doc_ids) > 1 else doc_titles[0])
                conf = {
                    "type": "delete_confirmation",
                    "target_type": "bulk_documents",
                    "target_id": doc_ids[0],
                    "target_ids": doc_ids,
                    "title": conf_title,
                    "details": f"Verranno eliminati definitivamente {len(doc_ids)} file dal caveau."
                }
                return {
                    "confirmation": conf,
                    "status": "pending_confirmation",
                    "target_type": "bulk_documents",
                    "target_id": doc_ids[0],
                    "target_ids": doc_ids,
                    "title": conf_title,
                    "documents": [{
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
                }

            details = ""
            if target_type == "physical_item":
                rec = db.query(PhysicalItem).filter(PhysicalItem.id == target_id).first() if target_id else None
                if not rec and title:
                    clean_t = re.sub(r"^(?:elimina|cancella|rimuovi|butta)\s*(?:il|la|lo|le|i|l'|un|una|uno)?\s*", "", title, flags=re.IGNORECASE).strip(" ?.")
                    clean_t = re.sub(r"\s*(?:per favore|per cortesia|grazie)$", "", clean_t, flags=re.IGNORECASE).strip()
                    s_items = search_vault_items(db, clean_t or title, thread_id=thread_id)
                    if s_items:
                        rec = db.query(PhysicalItem).filter(PhysicalItem.id == (s_items[0].get("item_id") or s_items[0].get("id"))).first()
                if rec:
                    target_id = rec.id
                    title = rec.item_name
                    details = f"Posizione: {rec.primary_location}" + (f" ({rec.detailed_location})" if rec.detailed_location else "")
            else:
                target_type = "document"
                rec = db.query(Document).filter(Document.id == target_id).first() if target_id else None
                if not rec and title:
                    clean_t = re.sub(r"^(?:elimina|cancella|rimuovi|butta)\s*(?:il|la|lo|le|i|l'|un|una|uno)?\s*", "", title, flags=re.IGNORECASE).strip(" ?.")
                    clean_t = re.sub(r"\s*(?:per favore|per cortesia|grazie)$", "", clean_t, flags=re.IGNORECASE).strip()
                    s_res = search_vault_documents(db, clean_t or title, thread_id=thread_id)
                    if s_res:
                        rec = db.query(Document).filter(Document.id == s_res[0]["id"]).first()
                if rec:
                    target_id = rec.id
                    title = rec.title
                    details = rec.summary or rec.issuer or ""

            conf = {
                "type": "delete_confirmation",
                "target_type": target_type or "document",
                "target_id": target_id or 0,
                "title": title or "elemento",
                "details": details
            }
            return {
                "confirmation": conf,
                "status": "pending_confirmation",
                "target_type": target_type or "document",
                "target_id": target_id or 0,
                "title": title or "elemento"
            }

        elif name == "get_current_date":
            return get_current_date_info()

        elif name == "get_upcoming_deadlines":
            query_arg = (args.get("query") or "").strip().lower()
            if query_arg:
                # Se è specificata una query (es. "patente", "garanzia"), cerca tra tutti i documenti con scadenza a prescindere dallo stato
                matched_docs = search_vault_documents(db, query_arg, thread_id=thread_id)
                matched_ids = [m["id"] for m in matched_docs]
                docs = (
                    db.query(Document)
                    .filter(Document.id.in_(matched_ids), Document.due_date.isnot(None))
                    .order_by(Document.due_date.asc().nulls_last())
                    .all()
                )
                if not docs:
                    docs = (
                        db.query(Document)
                        .filter(Document.due_date.isnot(None))
                        .order_by(Document.due_date.asc().nulls_last())
                        .all()
                    )
                    docs = [d for d in docs if query_arg in (d.title or "").lower() or query_arg in (d.summary or "").lower()]
            else:
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
                        "file_type": d.file_type,
                        "drive_file_id": d.drive_file_id,
                        "drive_web_url": d.drive_web_url,
                        "is_on_drive": bool(d.drive_file_id or d.drive_web_url)
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
                "file_type": doc.file_type,
                "drive_file_id": doc.drive_file_id,
                "drive_web_url": doc.drive_web_url,
                "is_on_drive": bool(doc.drive_file_id or doc.drive_web_url)
            }

            return {
                "success": True,
                "document_id": doc.id,
                "old_title": old_title,
                "new_title": doc.title,
                "document": doc_info,
                "documents": [doc_info]
            }
        elif name == "show_document_card":
            doc_id = args.get("document_id")
            doc_ids = args.get("document_ids") or []
            doc_title = (args.get("document_title") or args.get("query") or "").strip()
            doc_titles = args.get("document_titles") or []

            docs = []
            # 1. Raccogli per document_ids
            if doc_ids:
                for did in doc_ids:
                    try:
                        d = db.query(Document).filter(Document.id == int(did)).first()
                        if d and d not in docs:
                            docs.append(d)
                    except Exception:
                        pass

            # 2. Raccogli per document_titles
            if doc_titles:
                for dt in doc_titles:
                    matches = search_vault_documents(db, str(dt).strip(), thread_id=thread_id)
                    if matches:
                        top_id = matches[0]["id"]
                        d = db.query(Document).filter(Document.id == top_id).first()
                        if d and d not in docs:
                            docs.append(d)

            # 3. Singolo ID
            if not docs and doc_id:
                try:
                    d = db.query(Document).filter(Document.id == int(doc_id)).first()
                    if d:
                        docs.append(d)
                except Exception:
                    pass

            # 4. Singolo titolo o query di ricerca
            if not docs and doc_title:
                matches = search_vault_documents(db, doc_title, thread_id=thread_id)
                if matches:
                    for m in matches[:4]:
                        d = db.query(Document).filter(Document.id == m["id"]).first()
                        if d and d not in docs:
                            docs.append(d)

            # 5. Se nessun parametro, prendi l'ultimo documento
            if not docs and not doc_id and not doc_ids and not doc_title and not doc_titles:
                q = db.query(Document)
                if thread_id and thread_id not in ["general", "all"]:
                    q = q.filter(Document.thread_id == thread_id)
                last_d = q.order_by(Document.id.desc()).first()
                if last_d:
                    docs.append(last_d)

            if not docs:
                return {"error": "Nessun documento trovato nel caveau da visualizzare.", "found": False}

            docs_info = []
            for d in docs:
                fn = Path(d.file_path).name if d.file_path else ""
                docs_info.append({
                    "id": d.id,
                    "document_id": d.id,
                    "thread_id": d.thread_id,
                    "title": d.title,
                    "issuer": d.issuer,
                    "amount": d.amount,
                    "due_date": d.due_date.isoformat() if d.due_date else None,
                    "summary": d.summary,
                    "doc_type": d.doc_type,
                    "status": d.status,
                    "file_url": f"/uploads/{fn}" if fn else None,
                    "download_url": f"/api/documents/{d.id}/download",
                    "file_type": d.file_type,
                    "drive_file_id": d.drive_file_id,
                    "drive_web_url": d.drive_web_url,
                    "is_on_drive": bool(d.drive_file_id or d.drive_web_url)
                })

            return {
                "success": True,
                "document": docs_info[0],
                "documents": docs_info,
                "found_documents": docs_info
            }

        elif name == "scan_local_folder":
            from app.services.folder_service import scan_local_folder as do_scan_folder
            f_path = (args.get("folder_path") or "").strip()
            results = []
            if f_path and f_path.lower() != "all":
                res = do_scan_folder(f_path, db, thread_id=thread_id)
                results.append(res)
            else:
                watched = db.query(WatchedFolder).filter(WatchedFolder.is_active == True).all()
                if not watched:
                    return {
                        "error": "Nessuna cartella del PC è attualmente configurata per il monitoraggio. Puoi aggiungerne una dalla Dashboard o indicare un percorso specifico (es. C:\\Documenti).",
                        "folders_count": 0
                    }
                for wf in watched:
                    res = do_scan_folder(wf.path, db, thread_id=wf.thread_id or thread_id, watched_folder_id=wf.id)
                    results.append(res)

            total_new = sum(r.new_indexed_count for r in results)
            total_scanned = sum(r.scanned_files_count for r in results)
            total_skipped = sum(r.skipped_count for r in results)
            total_errors = sum(r.error_count for r in results)

            return {
                "success": True,
                "total_scanned": total_scanned,
                "total_new_indexed": total_new,
                "total_skipped": total_skipped,
                "total_errors": total_errors,
                "folders_processed": [
                    {
                        "path": r.folder_path,
                        "scanned": r.scanned_files_count,
                        "new": r.new_indexed_count,
                        "skipped": r.skipped_count,
                        "details": r.details[:5]
                    }
                    for r in results
                ]
            }

        elif name == "list_watched_folders":
            folders = db.query(WatchedFolder).all()
            return {
                "watched_folders_count": len(folders),
                "folders": [
                    {
                        "id": f.id,
                        "name": f.name,
                        "path": f.path,
                        "thread_id": f.thread_id,
                        "file_count": f.file_count,
                        "last_scanned_at": f.last_scanned_at.isoformat() if f.last_scanned_at else "Mai",
                        "is_active": f.is_active
                    }
                    for f in folders
                ]
            }

        elif name == "open_local_file_in_explorer":
            from app.services.folder_service import open_path_in_explorer
            doc_id = args.get("document_id")
            doc_title = (args.get("document_title") or "").strip()
            path_arg = (args.get("path") or "").strip()

            target_path = None
            matched_doc = None
            if doc_id:
                matched_doc = db.query(Document).filter(Document.id == doc_id).first()
            elif doc_title:
                matches = search_vault_documents(db, doc_title, thread_id=thread_id)
                if matches:
                    matched_doc = db.query(Document).filter(Document.id == matches[0]["id"]).first()

            if matched_doc:
                target_path = matched_doc.original_path or matched_doc.file_path
            elif path_arg:
                target_path = path_arg

            if not target_path or not Path(target_path).exists():
                return {
                    "success": False,
                    "error": f"File o cartella non trovata sul computer: {target_path or doc_title or doc_id}"
                }

            opened = open_path_in_explorer(target_path)
            return {
                "success": opened,
                "path": target_path,
                "title": matched_doc.title if matched_doc else Path(target_path).name,
                "message": f"Aperto '{Path(target_path).name}' in Esplora File." if opened else "Impossibile aprire Esplora File."
            }

        elif name == "create_zip_archive":
            from app.services.archive_service import create_zip_from_documents
            doc_ids = args.get("document_ids")
            query = args.get("query")
            category = args.get("category")
            archive_name = args.get("archive_name")

            zip_doc = create_zip_from_documents(
                db=db,
                document_ids=doc_ids,
                query=query,
                category=category,
                archive_title=archive_name,
                thread_id=thread_id
            )
            if not zip_doc:
                return {
                    "success": False,
                    "message": "Nessun documento trovato corrispondente ai criteri per creare l'archivio ZIP."
                }
            fn = Path(zip_doc.file_path).name if zip_doc.file_path else "archivio.zip"
            return {
                "success": True,
                "message": f"Archivio ZIP '{zip_doc.title}' creato con successo.",
                "zip_document_id": zip_doc.id,
                "title": zip_doc.title,
                "file_url": f"/uploads/{fn}",
                "download_url": f"/api/documents/{zip_doc.id}/download",
                "summary": zip_doc.summary,
                "document": {
                    "id": zip_doc.id,
                    "document_id": zip_doc.id,
                    "title": zip_doc.title,
                    "issuer": zip_doc.issuer,
                    "doc_type": zip_doc.doc_type,
                    "amount": None,
                    "due_date": None,
                    "status": "archiviato",
                    "summary": zip_doc.summary,
                    "file_url": f"/uploads/{fn}",
                    "download_url": f"/api/documents/{zip_doc.id}/download",
                    "file_type": "zip"
                }
            }

        elif name == "unzip_vault_archive":
            from app.services.archive_service import unzip_document_to_vault
            doc_id = args.get("document_id")
            doc_title = args.get("document_title")

            extracted = unzip_document_to_vault(
                db=db,
                document_id=doc_id,
                document_title=doc_title,
                thread_id=thread_id
            )
            if not extracted:
                return {
                    "success": False,
                    "message": "Impossibile estrarre l'archivio ZIP o nessun file valido trovato all'interno."
                }
            return {
                "success": True,
                "message": f"Estratti con successo {len(extracted)} documenti dall'archivio ZIP.",
                "extracted_count": len(extracted),
                "extracted_documents": [
                    {
                        "id": d.id,
                        "document_id": d.id,
                        "title": d.title,
                        "issuer": d.issuer,
                        "doc_type": d.doc_type,
                        "amount": d.amount,
                        "due_date": d.due_date.isoformat() if d.due_date else None,
                        "status": d.status,
                        "summary": d.summary,
                        "file_url": f"/uploads/{Path(d.file_path).name}" if d.file_path else None,
                        "download_url": f"/api/documents/{d.id}/download",
                        "file_type": d.file_type
                    }
                    for d in extracted
                ]
            }

        elif name == "get_google_drive_status":
            cred = db.query(GoogleDriveCredential).first() if db else None
            if not cred:
                return {
                    "connected": False,
                    "message": "Google Drive non è attualmente collegato. L'utente può collegarlo in ogni momento dal menu Strumenti -> ☁️ Google Drive Cloud Sync.",
                    "root_folder": "DoveLoAIMesso",
                    "folder_structure_rules": {
                        "with_due_date": "DoveLoAIMesso / <Anno> / <Categoria> / <NomeFile>",
                        "without_due_date": "DoveLoAIMesso / <Categoria> / <NomeFile>"
                    },
                    "standard_categories": [
                        "Bollette & Utenze",
                        "Fisco & Tasse",
                        "Fatture & Spese",
                        "Contratti & Polizze",
                        "Documenti & Foto"
                    ],
                    "categories": [
                        "Bollette & Utenze",
                        "Fisco & Tasse",
                        "Fatture & Spese",
                        "Contratti & Polizze",
                        "Documenti & Foto"
                    ],
                    "total_files_on_drive": 0,
                    "matching_files": [],
                    "folders_overview": {},
                    "documents": []
                }

            query = (args.get("query") or "").strip().lower()
            q_drive = db.query(Document).filter(
                or_(Document.drive_file_id.isnot(None), Document.drive_web_url.isnot(None))
            )
            if thread_id and thread_id not in ["general", "all"]:
                q_drive = q_drive.filter(Document.thread_id == thread_id)

            drive_docs = q_drive.order_by(Document.id.desc()).all()

            files_list = []
            folders_overview = {}
            for d in drive_docs:
                folder_parts = resolve_drive_folder_path(d.doc_type, d.due_date)
                folder_str = " / ".join(folder_parts)
                fn = Path(d.file_path).name if d.file_path else ""
                doc_title = (d.title or "").strip() or fn or f"Documento #{d.id}"
                folders_overview.setdefault(folder_str, []).append(doc_title)

                if query and (
                    query not in doc_title.lower()
                    and query not in folder_str.lower()
                    and query not in (d.summary or "").lower()
                    and query not in (d.doc_type or "").lower()
                ):
                    continue

                files_list.append({
                    "id": d.id,
                    "document_id": d.id,
                    "thread_id": d.thread_id,
                    "title": doc_title,
                    "issuer": d.issuer,
                    "doc_type": d.doc_type,
                    "amount": d.amount,
                    "due_date": d.due_date.isoformat() if d.due_date else None,
                    "status": d.status,
                    "summary": d.summary,
                    "folder_path": folder_str,
                    "folder_parts": folder_parts,
                    "drive_file_id": d.drive_file_id,
                    "drive_web_url": d.drive_web_url,
                    "is_on_drive": True,
                    "file_url": f"/uploads/{fn}" if fn else None,
                    "download_url": f"/api/documents/{d.id}/download",
                    "file_type": d.file_type
                })

            mode_desc = "Solo Google Drive (i file fisici risiedono su Google Drive, metadati nel caveau)" if cred.storage_mode == "cloud_only" else "Copia locale cifrata nel caveau + Google Drive (doppia copia)"

            return {
                "connected": True,
                "user_email": cred.user_email,
                "storage_mode": cred.storage_mode,
                "storage_mode_description": mode_desc,
                "root_folder": "DoveLoAIMesso",
                "folder_structure_rules": {
                    "with_due_date": "DoveLoAIMesso / <Anno> / <Categoria> / <NomeFile>",
                    "without_due_date": "DoveLoAIMesso / <Categoria> / <NomeFile>"
                },
                "standard_categories": [
                    "Bollette & Utenze",
                    "Fisco & Tasse",
                    "Fatture & Spese",
                    "Contratti & Polizze",
                    "Documenti & Foto"
                ],
                "categories": [
                    "Bollette & Utenze",
                    "Fisco & Tasse",
                    "Fatture & Spese",
                    "Contratti & Polizze",
                    "Documenti & Foto"
                ],
                "total_files_on_drive": len(drive_docs),
                "matching_files_count": len(files_list),
                "matching_files": files_list,
                "folders_overview": folders_overview,
                "documents": files_list
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

        watched_folders = db.query(WatchedFolder).all() if db else []
        if watched_folders:
            vault_summary.append(f"\n[CARTELLE PC MONITORATE ({len(watched_folders)})]:")
            for wf in watched_folders:
                vault_summary.append(f"- 📁 {wf.name}: {wf.path} ({wf.file_count} file indicizzati, ultima scansione: {wf.last_scanned_at.strftime('%d/%m/%Y %H:%M') if wf.last_scanned_at else 'Mai'})")

        # Stato Sincronizzazione Google Drive Cloud Sync
        drive_cred = db.query(GoogleDriveCredential).first() if db else None
        q_drive = db.query(Document).filter(
            or_(Document.drive_file_id.isnot(None), Document.drive_web_url.isnot(None))
        )
        if thread_id and thread_id not in ["general", "all"]:
            q_drive = q_drive.filter(Document.thread_id == thread_id)
        drive_docs = q_drive.order_by(Document.id.desc()).all() if db else []

        if drive_cred:
            mode_desc = "Solo Google Drive (i file fisici risiedono su Google Drive, metadati nel caveau)" if drive_cred.storage_mode == "cloud_only" else "Copia locale cifrata nel caveau + Google Drive (doppia copia)"
            vault_summary.append(f"\n[STATO SINCRONIZZAZIONE GOOGLE DRIVE CLOUD SYNC]:")
            vault_summary.append(f"- Connessione: ATTIVA E COLLEGATA")
            vault_summary.append(f"- Account Google associato: {drive_cred.user_email or 'Account collegato'}")
            vault_summary.append(f"- Modalità archiviazione: {drive_cred.storage_mode} ({mode_desc})")
            vault_summary.append(f"- File totali archiviati su Google Drive per questo canale: {len(drive_docs)}")
            vault_summary.append(f"- Regola cartelle Drive: 'DoveLoAIMesso / <Anno> / <Categoria> / <File>' (o 'DoveLoAIMesso / <Categoria> / <File>' senza scadenza)")
            if drive_docs:
                vault_summary.append("  File attualmente presenti su Google Drive:")
                for dd in drive_docs[:15]:
                    f_path = " / ".join(resolve_drive_folder_path(dd.doc_type, dd.due_date))
                    dd_title = (dd.title or "").strip() or (Path(dd.file_path).name if dd.file_path else "") or f"Documento #{dd.id}"
                    vault_summary.append(f"  * 📁 {f_path} -> 📄 {dd_title} [Drive Web URL: {dd.drive_web_url or dd.drive_file_id}]")
        else:
            vault_summary.append(f"\n[STATO SINCRONIZZAZIONE GOOGLE DRIVE CLOUD SYNC]:")
            vault_summary.append(f"- Connessione: NON COLLEGATO (l'utente può collegare il proprio account dal menu Strumenti -> Google Drive Cloud Sync)")

        vault_summary.append("\n[REGOLA SULL'USO DEI DATI DEL DATABASE]:")
        vault_summary.append("- Per conoscere, elencare o cercare documenti o oggetti, DEVI interrogare il database tramite gli appositi strumenti (`search_vault`, `list_vault_contents`, `get_upcoming_deadlines`, `scan_local_folder`, `list_watched_folders`).")
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
        is_deletion = any(k in lower_t for k in [
            "elimina", "cancella", "rimuovi", "butta", "eliminami", "cancellami", "svuota", "eliminali", "cancellali", "rimuovili"
        ])
        if is_deletion:
            return None

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
        is_deletion = any(re.search(rf"\b{re.escape(k)}\b", lower_t) for k in [
            "elimina", "cancella", "rimuovi", "eliminarlo", "cancellarlo", 
            "rimuoverlo", "butta", "cancellami", "eliminami", "eliminali", "cancellali", "rimuovili"
        ])
        if not is_deletion:
            return None

        # Escludi frasi negative, domande meta o riferimenti a quotazioni
        if any(re.search(rf"\b{re.escape(k)}\b", lower_t) for k in [
            "non eliminare", "non cancellare", "senza eliminare", "senza cancellare",
            "sto quotando", "quotando un messaggio", "ti ricordi", "questo messaggio", "a questo messaggio"
        ]):
            return None

        clean_prompt = re.sub(r"[?!.,;]", " ", lower_t)
        clean_prompt = re.sub(r"\s+", " ", clean_prompt).strip()

        # 1. Rileva eliminazione multipla o totale
        is_bulk = (
            any(k in clean_prompt for k in [
                "elimina tutti", "elimina tutte", "cancella tutti", "cancella tutte",
                "rimuovi tutti", "rimuovi tutte", "svuota", "elimina tutto", "cancella tutto",
                "eliminali tutti", "cancellali tutti", "rimuovili tutti", "elimina ogni"
            ])
            or clean_prompt in ["eliminali", "cancellali", "rimuovili", "elimina tutto", "cancella tutto", "elimina tutti", "cancella tutti"]
        )

        if is_bulk:
            query = db.query(Document)
            if thread_id and thread_id != "general" and thread_id != "all":
                query = query.filter(Document.thread_id == thread_id)

            is_total, target_kw = self._extract_bulk_delete_target(clean_prompt)
            if not is_total and target_kw:
                s_matches = search_vault_documents(db, target_kw, thread_id=thread_id)
                matched_ids = [m["id"] for m in s_matches]
                stem_kw = it_stem(target_kw)
                like_matches = query.filter(or_(
                    Document.title.ilike(f"%{target_kw}%"),
                    Document.doc_type.ilike(f"%{target_kw}%"),
                    Document.issuer.ilike(f"%{target_kw}%"),
                    Document.summary.ilike(f"%{target_kw}%"),
                    Document.title.ilike(f"%{stem_kw}%"),
                    Document.doc_type.ilike(f"%{stem_kw}%"),
                    Document.summary.ilike(f"%{stem_kw}%")
                )).all()
                for lm in like_matches:
                    if lm.id not in matched_ids:
                        matched_ids.append(lm.id)

                if not matched_ids:
                    return ChatResponse(
                        reply=f"Non ho trovato documenti corrispondenti a '{target_kw}' nel caveau da eliminare.",
                        action="REPLY"
                    )
                query = query.filter(Document.id.in_(matched_ids))
                cat_name = f"documenti corrispondenti a '{target_kw}'"
            else:
                cat_name = "tutti i documenti"

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
                "title": f"TUTTI i {len(doc_ids)} documenti ({cat_name})" if (is_total and len(doc_ids) > 1) else (f"I {len(doc_ids)} {cat_name}" if len(doc_ids) > 1 else doc_titles[0]),
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

    def _handle_drive_intent(self, user_text: str, lower_t: str, db: Session, thread_id: str = "general") -> Optional[ChatResponse]:
        """Intercetta e risponde in modo deterministico nei test offline alle domande generali sull'integrazione Google Drive."""
        is_specific_doc_search = any(k in lower_t for k in [
            "polizza", "bollett", "fattur", "f24", "730", "patente", "passaporto", "carta",
            "ricevut", "scontrino", "contratt", "certificat", "mutuo", "multa", "verbale"
        ])
        if is_specific_doc_search:
            return None

        has_drive_mention = any(k in lower_t for k in ["google drive", "su drive", "in drive", "mio drive", "tuo drive", "nostro drive"]) or (
            "drive" in lower_t and any(k in lower_t for k in ["cartell", "salvat", "organizzat", "cosa", "dove", "file", "stato", "sincronizz", "come hai", "come funziona", "spiegami"])
        )
        if not has_drive_mention:
            return None

        status_data = self.execute_tool("get_google_drive_status", {}, db=db, thread_id=thread_id)
        if not status_data.get("connected"):
            return ChatResponse(
                reply=(
                    "☁️ **Google Drive non è attualmente collegato.**\n\n"
                    "L'integrazione con Google Drive Cloud Sync è pronta e funzionante: puoi collegare il tuo account Google in qualsiasi momento "
                    "aprendo il menu **Strumenti $\to$ ☁️ Google Drive Cloud Sync** e cliccando su **'Collega Google Drive'**."
                ),
                action="get_google_drive_status",
                data=status_data
            )

        email = status_data.get("user_email") or "Account collegato"
        mode = status_data.get("storage_mode", "dual")
        mode_label = "**Solo Google Drive** (i file fisici risiedono unicamente sul cloud Google Drive, nessun file memorizzato sul disco locale)" if mode == "cloud_only" else "**Copia locale cifrata nel caveau + Google Drive** (doppio salvataggio sicuro)"
        total_files = status_data.get("total_files_on_drive", 0)
        folders_overview = status_data.get("folders_overview") or {}
        matching_files = status_data.get("matching_files") or []

        folder_explanation = (
            "📂 **Come organizzo le cartelle su Google Drive**:\n"
            "Tutti i tuoi file vengono archiviati in modo strutturato dentro la cartella principale **`DoveLoAIMesso`** sul tuo Google Drive:\n"
            "• **Documenti con scadenza**: `DoveLoAIMesso / <Anno> / <Categoria> / <File>` (es. `DoveLoAIMesso/2026/Bollette & Utenze/...`)\n"
            "• **Documenti senza scadenza**: `DoveLoAIMesso / <Categoria> / <File>` (es. `DoveLoAIMesso/Documenti & Foto/...`)\n\n"
            "Le categorie automatiche create sono:\n"
            "- ⚡ *Bollette & Utenze* (luce, gas, acqua)\n"
            "- 🏛️ *Fisco & Tasse* (modelli F24, tributi, tasse)\n"
            "- 💳 *Fatture & Spese* (fatture d'acquisto, scontrini, ricevute)\n"
            "- 📑 *Contratti & Polizze* (contratti d'affitto, polizze assicurative)\n"
            "- 📁 *Documenti & Foto* (credenziali, file generici, foto personali)"
        )

        if total_files == 0:
            files_explanation = "📄 **File attualmente archiviati su Google Drive**: Al momento non ci sono file sincronizzati. Non appena carichi un file qui nella chat (📎 o 📷), lo caricherò automaticamente nella sua cartella dedicata su Drive!"
        else:
            files_lines = []
            for f_path, f_titles in folders_overview.items():
                files_lines.append(f"• 📁 **{f_path}**:")
                for t in f_titles:
                    files_lines.append(f"  - 📄 {t}")
            files_explanation = f"📄 **File attualmente archiviati su Google Drive ({total_files} file)**:\n" + "\n".join(files_lines)

        reply_text = (
            f"☁️ **Google Drive Cloud Sync è attivo e collegato** all'account **`{email}`**!\n\n"
            f"⚙️ **Modalità di archiviazione attiva**: {mode_label}.\n\n"
            f"{folder_explanation}\n\n"
            f"{files_explanation}\n\n"
            "💡 *Puoi aprire direttamente qualsiasi file su Google Drive cliccando sul pulsante **[Drive ↗]** presente sulla scheda del documento qui sotto!*"
        )

        return ChatResponse(
            reply=reply_text,
            action="get_google_drive_status",
            data=status_data,
            documents=matching_files[:5]
        )

    def resolve_agent_model(self, user_text: str, lower_t: str, configured_model: str) -> str:
        """
        Risolve dinamicamente il modello da utilizzare:
        - Se configured_model != 'auto', rispetta la scelta manuale dell'utente.
        - Se configured_model == 'auto':
            - Se l'intento è di immagazzinamento/salvataggio/caricamento rapido:
                -> 'google/gemini-2.5-flash-lite'
            - Se l'intento è di ricerca, calcolo, scadenze, domande complesse o spiegazioni:
                -> 'google/gemini-2.5-pro'
            - Default per richieste generiche: 'google/gemini-2.5-pro' (massima intelligenza)
        """
        cfg = (configured_model or "").strip()
        if not cfg:
            cfg = "auto"

        if cfg != "auto":
            return cfg

        # 1. Ricerche, calcoli, scadenze, domande e spiegazioni -> PRO (Thinking Process)
        search_calc_patterns = [
            "dov'è", "dov'e", "dove è", "dove sono", "dove si trova", "dove ho messo", "dove sta", "dove ",
            "cerca", "trova", "trovami", "mostrami", "fammi vedere",
            "scadenz", "bollett", "fattur", "polizz", "mutuo", "assicuraz",
            "quanto", "quant'è", "quant'e", "somma", "totale", "calcola", "spesa", "spese",
            "spiega", "spiegami", "chiarisci", "cosa copre", "cosa c'è", "cosa ce", "cosa contiene",
            "come funziona", "dimmi", "elenca", "quali", "?"
        ]
        is_search_or_reasoning = any(p in lower_t for p in search_calc_patterns)

        # 2. Immagazzinamento rapido / posizioni / allegati foto -> FLASH LITE
        storage_patterns = [
            "ho messo", "ho riposto", "ho posato", "ho infilato", "ho lasciato", "ho salvato",
            "salva", "salvami", "memorizza", "memorizzami", "registra",
            "riponi", "posiziona", "sposta", "spostato", "aggiorna la posizione",
            "ti allego", "allego foto", "ecco la foto", "foto per", "foto della",
            "messo nel", "messa nel", "messo in", "messa in", "messo sulla", "messo sullo"
        ]
        is_storage = any(p in lower_t for p in storage_patterns)

        if is_storage and not is_search_or_reasoning:
            return "google/gemini-2.5-flash-lite"

        if is_search_or_reasoning:
            return "google/gemini-2.5-pro"

        pos_preps = [" nel ", " nello ", " nella ", " nei ", " negli ", " nelle ", " sul ", " sullo ", " sulla ", " in "]
        if any(prep in lower_t for prep in pos_preps) and not is_search_or_reasoning:
            return "google/gemini-2.5-flash-lite"

        return "google/gemini-2.5-pro"

    def run_turn(
        self,
        user_text: str,
        db: Session,
        thread_id: str = "general",
        quoted_message: Optional[dict] = None,
        audio_base64: Optional[str] = None,
        audio_format: Optional[str] = "wav"
    ) -> ChatResponse:
        """Esegue un turno conversazionale applicando la risoluzione del modello tramite Router Intelligente."""
        lower_t = user_text.lower()
        configured_model = get_app_setting(db, "ai_model", default=self.settings.OPENROUTER_MODEL) or "auto"
        effective_model = self.resolve_agent_model(user_text, lower_t, configured_model)

        resp = self._run_turn_impl(
            user_text=user_text,
            db=db,
            thread_id=thread_id,
            quoted_message=quoted_message,
            audio_base64=audio_base64,
            audio_format=audio_format,
            effective_model=effective_model
        )

        if resp:
            resp.routed_model = effective_model
            if resp.data is None:
                resp.data = {"routed_model": effective_model}
            elif isinstance(resp.data, dict) and "routed_model" not in resp.data:
                resp.data["routed_model"] = effective_model

        return resp

    def _run_turn_impl(
        self,
        user_text: str,
        db: Session,
        thread_id: str = "general",
        quoted_message: Optional[dict] = None,
        audio_base64: Optional[str] = None,
        audio_format: Optional[str] = "wav",
        effective_model: Optional[str] = None
    ) -> ChatResponse:
        """Esegue l'elaborazione interna di un turno conversazionale con tool-calling dell'agente."""
        lower_t = user_text.lower()

        # Intercetta immediatamente domande sulla data/ora odierna, ieri o domani con calcolo istantaneo esatto
        temp_resp = self._handle_temporal_intent(user_text, lower_t)
        if temp_resp:
            return temp_resp

        # Intercetta immediatamente richieste di cancellazione/eliminazione sicura
        del_resp = self._handle_deletion_intent(user_text, lower_t, db, thread_id=thread_id)
        if del_resp:
            return del_resp

        # Rileva se si tratta di una richiesta esplicita di lista o elenco
        is_listing_phrase = any(k in lower_t for k in [
            "lista", "elenco", "elencami", "quali documenti", "quali oggetti",
            "cosa c'è", "cosa ce", "cosa ho", "cosa hai", "che documenti", "che oggetti"
        ])

        # Intercetta risposte affermative, selezioni multiple ("entrambi", "tutti e due", "si di entrambi", "scaricali") e richieste di download
        is_download_intent = any(k in lower_t for k in [
            "download", "scarica", "scaricarla", "scaricarlo", "scaricalo", "scaricala", "scaricarli", "scaricali", "scaricare",
            "fare il download", "voglio scaricare", "voglio il download", "voglio fare il download", "scaricale", "scaricali"
        ])
        is_multi_select = (
            lower_t.strip(" !.?") in [
                "entrambi", "entrambe", "tutti", "tutte", "tutti e due", "tutte e due", "tutti quanti",
                "si di entrambi", "sì di entrambi", "si entrambi", "sì entrambi", "tutti e 2", "tutte e 2",
                "scaricali", "scaricale", "scaricali entrambi", "scarica entrambi", "scaricali tutti", "scarica tutti",
                "scarica tutte", "scaricale tutte", "mostrali tutti", "mostrameli tutti", "mostrale tutte", "mostramele tutte",
                "apri entrambi", "apri tutti", "visualizzali entrambi", "visualizzali tutti", "vedili entrambi", "vedili tutti"
            ]
            or any(k in lower_t for k in [
                "entrambi", "entrambe", "tutti e due", "tutte e due", "tutti e 2", "tutte e 2",
                "mostrameli tutti", "mostrali tutti", "mostrale tutte", "mostramele tutte",
                "scarica tutti", "scarica tutte", "scarica entrambi", "scaricali entrambi", "scaricali tutti", "scaricale tutte",
                "scaricali", "scaricale", "si di entrambi", "sì di entrambi", "apri entrambi", "visualizzali entrambi"
            ])
        ) and not is_listing_phrase

        is_affirmative = (
            lower_t.strip(" !.?") in [
                "si", "sì", "ok", "va bene", "certo", "mostramelo", "mostramela", "mostrameli", "mostrali", "mostrale",
                "fammi vedere", "apri", "yes", "vai", "entrambi", "entrambe", "tutti e due", "tutte e due",
                "si di entrambi", "sì di entrambi", "si entrambi", "sì entrambi", "tutti", "tutte",
                "scaricali", "scaricale", "scaricalo", "scaricala", "scarica", "download", "apri entrambi", "mostrali tutti"
            ]
            or is_multi_select
            or (is_download_intent and len(lower_t.split()) <= 6)
        ) and not is_listing_phrase
        if is_affirmative:
            last_asst = (
                db.query(ChatMessage)
                .filter(ChatMessage.thread_id == thread_id, ChatMessage.sender == "assistant")
                .order_by(ChatMessage.id.desc())
                .first()
            )
            if last_asst and last_asst.content:
                all_docs = db.query(Document).order_by(Document.created_at.desc()).all()
                matched_docs = []

                # 1. Trova documenti il cui titolo compare direttamente nel testo del messaggio precedente
                for d in all_docs:
                    if d.title and len(d.title) >= 3 and d.title.lower() in last_asst.content.lower():
                        if d not in matched_docs:
                            matched_docs.append(d)

                # 2. Cerca nomi esplicitamente citati tra virgolette, grassetto o punti elenco (* 📄 Titolo)
                cand_names = (
                    re.findall(r"['\"]([^'\"]{2,})['\"]", last_asst.content) +
                    re.findall(r"\*\*([^*]{2,})\*\*", last_asst.content) +
                    re.findall(r"[*•-]\s*(?:📄\s*)?([^\n:]+?)(?:\s*:|\s*—|\s*\(|$)", last_asst.content)
                )

                for cand in cand_names:
                    c_clean = cand.strip(" *📄\"'")
                    if c_clean and len(c_clean) >= 3:
                        s_matches = search_vault_documents(db, c_clean, thread_id=thread_id)
                        if s_matches:
                            top_d = db.query(Document).filter(Document.id == s_matches[0]["id"]).first()
                            if top_d and top_d not in matched_docs:
                                matched_docs.append(top_d)
                        for d in all_docs:
                            if d.title and (d.title.lower() == c_clean.lower() or c_clean.lower() in d.title.lower() or d.title.lower() in c_clean.lower()):
                                if d not in matched_docs:
                                    matched_docs.append(d)

                # 3. Se non trovati per titolo intero, controlla sovrapposizione parole chiave
                if not matched_docs:
                    for d in all_docs:
                        d_words = [w for w in re.split(r"[^\w]+", d.title.lower()) if len(w) > 3 and w not in ITALIAN_STOPWORDS]
                        if d_words and sum(1 for w in d_words if w in last_asst.content.lower()) >= max(1, len(d_words) * 0.5):
                            if d not in matched_docs:
                                matched_docs.append(d)

                # 4. Controlla se fa riferimento a un oggetto fisico
                matched_item = None
                if not matched_docs:
                    all_items = db.query(PhysicalItem).order_by(PhysicalItem.updated_at.desc()).all()
                    for it in all_items:
                        if it.item_name and len(it.item_name) >= 3 and it.item_name.lower() in last_asst.content.lower():
                            matched_item = it
                            break
                    if not matched_item and cand_names:
                        for cand in cand_names:
                            c_clean = cand.strip(" *📄\"'")
                            for it in all_items:
                                if it.item_name and (it.item_name.lower() == c_clean.lower() or c_clean.lower() in it.item_name.lower()):
                                    matched_item = it
                                    break

                # Se ci sono documenti trovati:
                if matched_docs:
                    # Se l'utente non ha chiesto 'entrambi' o 'tutti' e ha specificato parole di uno solo:
                    specific_doc = None
                    if not is_multi_select and not any(k in lower_t for k in ["entrambi", "tutti", "tutte", "scaricali", "scaricale", "mostrali", "mostrameli"]):
                        for d in matched_docs:
                            d_words = [w for w in re.split(r"[^\w]+", d.title.lower()) if len(w) > 2 and w not in ITALIAN_STOPWORDS]
                            if any(w in lower_t for w in d_words):
                                specific_doc = d
                                break

                    docs_to_show = [specific_doc] if specific_doc else matched_docs
                    doc_ids_to_call = [d.id for d in docs_to_show]
                    card_res = self.execute_tool("show_document_card", {"document_ids": doc_ids_to_call}, db=db, thread_id=thread_id)
                    docs_info = card_res.get("documents") or []
                    if docs_info:
                        if len(docs_info) > 1:
                            lines = [f"- 📄 **{d['title']}** ({d.get('issuer') or d.get('doc_type', '')})" for d in docs_info]
                            reply_text = (
                                f"📄 Certamente! Ecco le schede per i {len(docs_info)} documenti:\n\n" +
                                "\n".join(lines) +
                                "\n\nPuoi visualizzarli con il pulsante 'Vedi' o scaricarli direttamente con il pulsante 'Scarica' nelle rispettive schede qui sotto! ⬇️"
                            )
                        else:
                            d = docs_info[0]
                            reply_text = f"📄 Eccolo! Ho recuperato il documento **{d['title']}** ({d.get('issuer') or d.get('doc_type', '')}):\n💡 {d.get('summary', '')}"

                        return ChatResponse(
                            reply=reply_text,
                            action="show_document_card",
                            data=card_res,
                            documents=docs_info
                        )

                elif matched_item:
                    loc_str = matched_item.primary_location + (f" ({matched_item.detailed_location})" if matched_item.detailed_location else "")
                    return ChatResponse(
                        reply=f"📍 Ho verificato la posizione di **{matched_item.item_name}**: si trova in **{loc_str}**.",
                        action="search_vault",
                        data={"item": {"item_id": matched_item.id, "item_name": matched_item.item_name, "location_str": loc_str}}
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
            any(re.search(rf"\b{re.escape(k)}\b", lower_t) for k in [
                "messo", "riposto", "salvato", "lasciato", "conservato", "posizionato", "sistemato",
                "modifica la posizione", "cambia la posizione", "aggiorna la posizione",
                "sposta", "spostato", "spostata", "spostare",
                "mettilo", "mettila", "mettili", "mettile", "metti",
                "ora è in", "ora si trova in", "adesso è in", "adesso si trova in"
            ])
            and not any(re.search(rf"\b{re.escape(k)}\b", lower_t) for k in ["dov'è", "dov'e", "dove ho", "dove si trova", "dove sono", "dove sta", "dove è", "dove"])
            and not any(re.search(rf"\b{re.escape(k)}\b", lower_t) for k in ["ti ricordi", "ti ricordi di", "ti ricordi questo", "ricordi", "sto quotando"])
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
        # Rileva se la richiesta menziona un documento o entità specifica (es. patente, garanzia, persona)
        has_specific_subject = any(k in lower_t for k in [
            "patente", "garanzia", "iphone", "apple", "carta", "passaporto", "contratto", "polizza",
            "assicurazione", "visura", "certificato", "tessera", "730", "f24", "mutuo", "multa", "verbale",
            "mario", "rossi", "andrea", "conti", "hera", "enel", "eni", "amazon", "scontrino",
            "della ", "del ", "dell'", "dei ", "delle ", "di ", "per "
        ]) or any(k in lower_t for k in ["rinnovo", "rinnovare", "valida fino", "validità", "fino a quando"])

        is_deadline_request = (
            any(k in lower_t for k in [
                "scadenz", "da pagare", "bollette da pagare", "tributi da pagare",
                "cosa devo pagare", "quanto devo pagare", "prossime scadenze", "scadenze in sospeso"
            ])
            and not is_listing_request
            and not is_store_or_update
            and not has_specific_subject
        )

        is_rename_request = (
            any(k in lower_t for k in [
                "chiamalo", "chiamala", "rinominalo", "rinominala", "rinomina",
                "salvalo come", "salvala come", "dagli il nome", "dalle il nome", "dai il nome", "dagli come nome", "dalle come nome"
            ])
            and not is_store_or_update
            and not is_where_request
        )

        # Rileva intenzione di collegare foto ad oggetto fisico (es. "ti allego una foto per il piano", "ecco la foto delle chiavi")
        linked_photo_item = self._extract_link_photo_item(user_text)
        is_link_photo_intent = bool(linked_photo_item)

        is_download_or_show = (
            any(k in lower_t for k in [
                "scarica", "scaricarla", "scaricarlo", "scaricalo", "scaricala", "scaricarli", "scaricali", "scaricare",
                "download", "fare il download", "voglio scaricare", "voglio il download", "voglio fare il download",
                "apri il documento", "apri il file", "mostramelo", "mostramela", "mostrameli", "mostra le schede", "mostrami le schede",
                "fammi vedere il file", "fammi vedere il documento", "voglio vederlo", "voglio vederla", "voglio vederli",
                "apri il pdf", "mostra la scheda", "vedi il documento", "mandami il pdf"
            ])
            and not is_store_or_update
            and not is_where_request
            and not is_link_photo_intent
        )

        is_delete_request = any(re.search(rf"\b{re.escape(k)}\b", lower_t) for k in [
            "elimina", "cancella", "rimuovi", "butta", "eliminami", "cancellami", "svuota", "eliminali", "cancellali", "rimuovili"
        ]) and not any(re.search(rf"\b{re.escape(k)}\b", lower_t) for k in [
            "non eliminare", "non cancellare", "senza eliminare", "senza cancellare", "sto quotando", "quotando un messaggio", "ti ricordi", "questo messaggio"
        ])

        is_doc_search_request = (
            any(k in lower_t for k in [
                "document", "file", "bollett", "fattur", "contratt", "certificat", "ricevut",
                "cedolin", "busta paga", "patente", "passaporto", "carta", "f24", "730", "estratto",
                "identit", "identificazion", "mutuo", "visura", "tessera", "tasse", "tribut",
                "garanzia", "iphone", "scontrino", "multa", "verbale", "polizza", "polizze", "assicurazion"
            ])
            and (
                any(k in lower_t for k in [
                    "dammi", "mostra", "mostrami", "cerca", "trova", "trovami", "apri", "vedi", "prendi",
                    "fammi vedere", "visualizza", "voglio", "scarica",
                    "quando scade", "data di scadenza", "scadenza di", "scadenza del", "scadenza della", "scadenza dell",
                    "rinnovo", "rinnovare", "valida fino", "fino a quando", "quanto ho pagato", "quanti"
                ])
                or has_specific_subject
            )
            and not is_where_request
            and not is_store_or_update
            and not is_listing_request
            and not is_delete_request
            and not is_link_photo_intent
        ) or (
            lower_t.strip(" !.?") in [
                "documenti di identità", "documenti di identita", "documenti personali",
                "documenti identità", "documenti identita", "tessera sanitaria", "ricevute", "bollette",
                "i documenti di identità", "i documenti di identita", "documenti"
            ]
        )

        stored_item_result = None
        if is_store_or_update:
            item_n, loc_n = self._extract_item_and_location(user_text, last_item_in_context=last_item_name)
            if item_n and loc_n:
                stored_item_result = self.execute_tool("store_physical_item", {"item_name": item_n, "primary_location": loc_n}, db=db, thread_id=thread_id)
            else:
                is_store_or_update = False

        # Se non c'è chiave API, fallback deterministico per test offline
        if not self.settings.OPENROUTER_API_KEY:
            # Fallback deterministico per richieste di eliminazione nei test offline
            del_resp = self._handle_deletion_intent(user_text, lower_t, db, thread_id=thread_id)
            if del_resp:
                return del_resp

            # Fallback deterministico per richieste Google Drive nei test offline
            drive_resp = self._handle_drive_intent(user_text, lower_t, db, thread_id=thread_id)
            if drive_resp:
                return drive_resp

            clean_test = lower_t.replace("?", "").strip()

            if is_link_photo_intent:
                tool_out = self.execute_tool("link_document_to_item", {"item_name": linked_photo_item}, db=db, thread_id=thread_id)
                if tool_out.get("success"):
                    it_name = tool_out.get("item_name", linked_photo_item)
                    return ChatResponse(
                        reply=f"✅ Ho associato la foto alla posizione di **{it_name}**! Quando mi chiederai dove si trova, ti mostrerò subito la foto della sua posizione. 📸",
                        action="link_document_to_item",
                        data=tool_out,
                        documents=tool_out.get("documents")
                    )
                else:
                    return ChatResponse(
                        reply=tool_out.get("error", "Non sono riuscito ad associare la foto all'oggetto."),
                        action="link_document_to_item",
                        data=tool_out
                    )

            if is_download_or_show or is_doc_search_request:
                last_asst_msg = (
                    db.query(ChatMessage)
                    .filter(ChatMessage.thread_id == thread_id, ChatMessage.sender == "assistant")
                    .order_by(ChatMessage.id.desc())
                    .first()
                )
                target_docs = []
                if is_download_or_show and last_asst_msg and last_asst_msg.content:
                    all_docs = db.query(Document).order_by(Document.created_at.desc()).all()
                    for d in all_docs:
                        if d.title and len(d.title) >= 3 and d.title.lower() in last_asst_msg.content.lower():
                            if d not in target_docs:
                                target_docs.append(d)
                    if not target_docs:
                        cand_lines = [line.strip(" *🏛️📄:-") for line in last_asst_msg.content.split("\n") if any(k in line.lower() for k in ["f24", "bolletta", "ricevuta", "contratto", "estratto", "certificato", "tessera", "mutuo"])]
                        for cl in cand_lines:
                            s_res = search_vault_documents(db, cl, thread_id=thread_id)
                            if s_res:
                                td = db.query(Document).filter(Document.id == s_res[0]["id"]).first()
                                if td and td not in target_docs:
                                    target_docs.append(td)

                if not target_docs:
                    clean_query = re.sub(
                        r"^(?:dammi|mostrami|mostra|apri|visualizza|prendi|vedi|scarica|trovami|trova|voglio\s+vedere|fammi\s+vedere|cerca)\s*(?:il|la|lo|le|i|l'|un|una|uno)?\s*",
                        "", lower_t
                    ).strip(" ?.")
                    clean_query = re.sub(
                        r"\s*(?:nel\s+drive|su\s+drive|in\s+drive|sul\s+drive|su\s+google\s+drive|in\s+google\s+drive|dal\s+drive|da\s+drive|nel\s+caveau|in\s+caveau)$",
                        "", clean_query, flags=re.IGNORECASE
                    ).strip(" ?.")
                    s_matches = search_vault_documents(db, clean_query or user_text, thread_id=thread_id)
                    for m in s_matches[:4]:
                        td = db.query(Document).filter(Document.id == m["id"]).first()
                        if td and td not in target_docs:
                            target_docs.append(td)

                # Se richiesta singolare esplicita ("il", "la") e non plurale/collettiva
                is_sing = any(re.search(rf"\b{w}\b", lower_t) for w in ["il", "lo", "la", "l'", "un", "una"]) and not any(re.search(rf"\b{w}\b", lower_t) for w in ["i", "gli", "le", "tutti", "tutte", "entrambi", "entrambe", "documenti", "ricevute", "bollette"])
                if is_sing and len(target_docs) > 1:
                    for d in target_docs:
                        d_words = [w for w in re.split(r"[^\w]+", d.title.lower()) if len(w) > 2 and w not in ITALIAN_STOPWORDS]
                        if any(w in lower_t for w in d_words):
                            target_docs = [d]
                            break

                args_card = {"document_ids": [d.id for d in target_docs]} if target_docs else {}
                tool_out = self.execute_tool("show_document_card", args_card, db=db, thread_id=thread_id)
                docs = tool_out.get("documents", [])
                if docs:
                    if len(docs) > 1:
                        lines = [f"- 📄 **{d['title']}** ({d.get('issuer') or d.get('doc_type', '')})" for d in docs]
                        rep = (
                            f"📄 Ho trovato i seguenti **{len(docs)} documenti** nel caveau:\n\n" +
                            "\n".join(lines) +
                            "\n\nEcco le schede con i pulsanti 'Vedi' e 'Scarica' per ciascun file qui sotto! ⬇️"
                        )
                    else:
                        rep = f"📄 Ecco la scheda per **{docs[0]['title']}**! Puoi visualizzarlo o scaricarlo direttamente con il pulsante qui sotto. ⬇️"
                    return ChatResponse(
                        reply=rep,
                        action="show_document_card",
                        data=tool_out,
                        documents=docs
                    )

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
                    linked_d = None
                    if it.get("document_id"):
                        d_rec = db.query(Document).filter(Document.id == it["document_id"]).first()
                        if d_rec:
                            fn = Path(d_rec.file_path).name if d_rec.file_path else ""
                            linked_d = {
                                "id": d_rec.id, "document_id": d_rec.id, "title": d_rec.title,
                                "file_url": f"/uploads/{fn}" if fn else None,
                                "download_url": f"/api/documents/{d_rec.id}/download",
                                "file_type": d_rec.file_type
                            }
                    elif it.get("image_url"):
                        linked_d = {
                            "id": it.get("item_id"), "document_id": it.get("item_id"), "title": f"Foto {it['item_name']}",
                            "file_url": it["image_url"], "download_url": it["image_url"], "file_type": "image"
                        }
                    photo_note = "\n📸 Ho allegato la foto della posizione qui sotto!" if (it.get("has_photo") or linked_d) else ""
                    return ChatResponse(
                        reply=f"📍 **{it['item_name']}** si trova in: {loc_desc}.{photo_note}",
                        action="search_vault",
                        data=tool_out,
                        documents=[linked_d] if linked_d else None
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

            if audio_base64:
                return ChatResponse(
                    reply="🎤 Ho ascoltato il tuo messaggio vocale! Tutto chiaro, richiesta registrata con successo.",
                    action="REPLY"
                )

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

        # Iniezione telemetria UI client (se ci sono stati errori recenti di visualizzazione o download)
        ui_telemetry_note = self._build_ui_telemetry_prompt_note(db, thread_id=thread_id)
        if ui_telemetry_note:
            history_messages.append({"role": "system", "content": ui_telemetry_note})

        if quoted_message and quoted_message.get("text"):
            q_sender = quoted_message.get("sender") or "Messaggio precedente"
            q_text = str(quoted_message.get("text", "")).strip()
            user_llm_content = f'[In risposta a {q_sender}: "{q_text}"]\n{user_text}'
        else:
            user_llm_content = user_text

        if audio_base64:
            clean_fmt = (audio_format or "wav").lower().lstrip(".")
            voice_prompt = (
                user_llm_content
                if user_llm_content and user_llm_content != "🎤 Messaggio vocale"
                else "Ascolta attentamente questo messaggio vocale dell'utente in italiano ed esegui le azioni necessarie tramite gli strumenti o rispondi in modo naturale e preciso."
            )
            history_messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": voice_prompt},
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": audio_base64,
                            "format": clean_fmt
                        }
                    }
                ]
            })
        else:
            history_messages.append({"role": "user", "content": user_llm_content})

        headers = {
            "Authorization": f"Bearer {self.settings.OPENROUTER_API_KEY.strip()}",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Dove lo AI messo",
            "Content-Type": "application/json"
        }

        tool_action = "REPLY"
        tool_data = None

        agent_model = effective_model or get_app_setting(db, "ai_model", default=self.settings.OPENROUTER_MODEL) or "google/gemini-2.5-flash-lite"


        is_drive_status_request = (
            (
                any(k in lower_t for k in ["google drive", "su drive", "in drive", "mio drive", "tuo drive", "nostro drive"])
                or ("drive" in lower_t and any(k in lower_t for k in ["stato", "conness", "collegat", "cartell", "organizzat", "cosa c'è", "cosa ce", "quali file", "come funziona", "spiegami", "come hai"]))
            )
            and not is_doc_search_request
            and not is_where_request
            and not is_listing_request
        )

        if is_delete_request:
            tool_choice_cfg = {"type": "function", "function": {"name": "delete_vault_record"}}
        elif is_link_photo_intent:
            tool_choice_cfg = {"type": "function", "function": {"name": "link_document_to_item"}}
        elif is_rename_request:
            tool_choice_cfg = {"type": "function", "function": {"name": "rename_vault_document"}}
        elif is_download_or_show:
            tool_choice_cfg = {"type": "function", "function": {"name": "show_document_card"}}
        elif is_doc_search_request or is_where_request:
            tool_choice_cfg = {"type": "function", "function": {"name": "search_vault"}}
        elif is_drive_status_request:
            tool_choice_cfg = {"type": "function", "function": {"name": "get_google_drive_status"}}
        elif is_listing_request:
            tool_choice_cfg = {"type": "function", "function": {"name": "list_vault_contents"}}
        elif is_store_or_update:
            tool_choice_cfg = {"type": "function", "function": {"name": "store_physical_item"}}
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
                    "max_tokens": 8192,
                    "temperature": 0.2
                },
                timeout=60.0
            )

            # Retry automatico: se la prima chiamata fallisce (es. "model output must contain
            # either output text or tool calls" con tool_choice forzato), riproviamo con "auto"
            if r1.status_code != 200 and tool_choice_cfg != "auto":
                err_body = ""
                try:
                    err_body = r1.json().get("error", {}).get("message", r1.text[:200])
                except Exception:
                    err_body = r1.text[:200]
                logger.warning(
                    f"OpenRouter r1 non-200 (status={r1.status_code}) con tool_choice={tool_choice_cfg!r}: {err_body}. "
                    "Retry con tool_choice='auto'..."
                )
                r1 = httpx.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json={
                        "model": agent_model,
                        "messages": history_messages,
                        "tools": TOOLS_DEFINITION,
                        "tool_choice": "auto",
                        "max_tokens": 8192,
                        "temperature": 0.2
                    },
                    timeout=60.0
                )

            if r1.status_code == 200:
                data1 = r1.json()
                msg1 = data1.get("choices", [{}])[0].get("message", {})
                tool_calls1 = msg1.get("tool_calls")
                
                if tool_calls1 and len(tool_calls1) > 0:
                    call1 = tool_calls1[0]
                    call_func = call1.get("function", {})
                    name1 = call_func.get("name")
                    try:
                        args1 = json.loads(call_func.get("arguments", "{}"))
                    except Exception:
                        args1 = {}

                    logger.info(f"Agentic calling tool: {name1} with args: {args1}")
                    tool_data = self.execute_tool(name1, args1, db, thread_id=thread_id)
                    tool_action = name1

                    history_messages.append(msg1)
                    history_messages.append({
                        "role": "tool",
                        "tool_call_id": call1.get("id", "call_1"),
                        "name": name1,
                        "content": json.dumps(tool_data, ensure_ascii=False)
                    })

                    r2 = httpx.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers=headers,
                        json={
                            "model": agent_model,
                            "messages": history_messages,
                            "max_tokens": 8192,
                            "temperature": 0.2
                        },
                        timeout=60.0
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
                            elif tool_action == "show_document_card":
                                d_tit = (docs_found[0]["title"] if docs_found else "documento")
                                final_text = f"📄 Ecco la scheda per **{d_tit}**! Puoi visualizzarlo o scaricarlo direttamente dalla scheda qui sotto. ⬇️"
                            elif tool_action == "link_document_to_item":
                                it_name = (tool_data or {}).get("item_name") or "oggetto"
                                final_text = f"✅ Ho associato la foto alla posizione di **{it_name}**! Quando mi chiederai dove si trova, ti mostrerò subito la foto della sua posizione. 📸"
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
                            elif tool_action == "delete_vault_record":
                                t_tit = (tool_data or {}).get("title") or "elemento"
                                final_text = f"⚠️ Ho preparato la richiesta per eliminare **{t_tit}** dal caveau. Clicca sul pulsante qui sotto per confermare o annullare l'operazione."
                            else:
                                final_text = "Operazione completata con successo nel caveau."
                        else:
                            # Validazione e ancoraggio stretto della risposta del modello al database SQLite reale:
                            if tool_action == "show_document_card":
                                final_text = re.sub(r"\[(?:Link per scaricare|Scarica|Download)[^\]]*\]", "la scheda del documento allegata qui sotto", final_text, flags=re.IGNORECASE)
                                if not final_text:
                                    d_tit = (docs_found[0]["title"] if docs_found else "documento")
                                    final_text = f"📄 Ecco la scheda per **{d_tit}**! Puoi visualizzarlo o scaricarlo direttamente dalla scheda qui sotto. ⬇️"

                            elif tool_action == "link_document_to_item":
                                it_name = (tool_data or {}).get("item_name") or "oggetto"
                                if "associat" not in final_text.lower() and "collegat" not in final_text.lower():
                                    final_text = f"✅ Ho associato la foto alla posizione di **{it_name}**! {final_text}"

                            elif tool_action == "list_vault_contents":
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
                                    if it.get("has_photo") or it.get("document_id"):
                                        if "📸" not in final_text:
                                            final_text += "\n📸 Ho allegato la foto della posizione qui sotto!"
                                        if not docs_found:
                                            d_rec = None
                                            if it.get("document_id"):
                                                d_rec = db.query(Document).filter(Document.id == it["document_id"]).first()
                                            elif it.get("image_path"):
                                                d_rec = db.query(Document).filter(Document.file_path == it["image_path"]).first()
                                            if d_rec:
                                                fn = Path(d_rec.file_path).name if d_rec.file_path else ""
                                                docs_found = [{
                                                    "id": d_rec.id, "document_id": d_rec.id, "title": d_rec.title,
                                                    "issuer": d_rec.issuer, "amount": d_rec.amount,
                                                    "due_date": d_rec.due_date.isoformat() if d_rec.due_date else None,
                                                    "summary": d_rec.summary,
                                                    "file_url": f"/uploads/{fn}" if fn else None,
                                                    "download_url": f"/api/documents/{d_rec.id}/download",
                                                    "file_type": d_rec.file_type
                                                }]

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

                        # Sanitizzazione anti-esitazione e proattività NLU:
                        final_text = re.sub(r"per scaricare entrambi i documenti,?\s*dovrai farlo singolarmente\.?", "", final_text, flags=re.IGNORECASE).strip()
                        hesitation_pattern = r"(?:desideri\s+che\s+ti\s+mostri\s+la\s+scheda\s+di\s+uno\s+(?:di\s+questi\s+documenti\s+)?in\s+particolare\??|quale\s+(?:di\s+questi\s+)?(?:vuoi|desideri|preferisci)\s*(?:vedere|scaricare|aprire)?\??|vuoi\s+che\s+ti\s+mostri\s+la\s+scheda\??|quale\s+vuoi\??|quale\s+preferisci\??)"
                        if docs_found and len(docs_found) > 0 and re.search(hesitation_pattern, final_text, flags=re.IGNORECASE):
                            final_text = re.sub(
                                hesitation_pattern,
                                "Ecco le schede con i pulsanti 'Vedi' e 'Scarica' per ciascun documento qui sotto! ⬇️",
                                final_text,
                                flags=re.IGNORECASE
                            ).strip()
                            filtered_docs = docs_found[:4]
                            tool_action = "show_document_card"

                        if tool_action == "show_document_card":
                            filtered_docs = docs_found
                        else:
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

                    # Se non è stato trovato nulla, rispondi con un messaggio negativo onesto e pulito (nessuna allucinazione o file recente casuale)
                    return ChatResponse(
                        reply="Ho cercato nel caveau, ma non ho trovato nessun documento o dato corrispondente alla tua richiesta.",
                        action="search_vault",
                        data=t_out
                    )

                # Pulisci sempre il testo diretto prima di usarlo (rimuove eventuali tag residui)
                direct_reply = strip_tool_tags(direct_reply)

                if direct_reply:
                    if is_delete_request:
                        is_bulk_phrase = any(k in lower_t for k in ["tutti", "tutte", "tutto"])
                        t_type = "bulk_documents" if is_bulk_phrase else ("physical_item" if any(k in lower_t for k in ["patente", "passaporto", "chiav", "oggett"]) else "document")
                        del_tool_res = self.execute_tool("delete_vault_record", {"target_type": t_type, "title": user_text}, db=db, thread_id=thread_id)
                        conf_b = del_tool_res.get("confirmation")
                        c_docs = del_tool_res.get("documents")
                        return ChatResponse(
                            reply=direct_reply,
                            action="REQUEST_DELETE" if conf_b else "REPLY",
                            data=del_tool_res,
                            documents=c_docs,
                            confirmation=conf_b
                        )

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
                            docs_to_attach = []
                            if it.get("has_photo") or it.get("document_id"):
                                clean_rep += "\n\n📸 Ho allegato la foto della posizione qui sotto!"
                                if it.get("document_id"):
                                    d_rec = db.query(Document).filter(Document.id == it["document_id"]).first()
                                    if d_rec:
                                        fn = Path(d_rec.file_path).name if d_rec.file_path else ""
                                        docs_to_attach.append({
                                            "id": d_rec.id, "document_id": d_rec.id, "title": d_rec.title,
                                            "issuer": d_rec.issuer, "amount": d_rec.amount,
                                            "due_date": d_rec.due_date.isoformat() if d_rec.due_date else None,
                                            "summary": d_rec.summary, "file_url": f"/uploads/{fn}" if fn else None,
                                            "download_url": f"/api/documents/{d_rec.id}/download", "file_type": d_rec.file_type
                                        })
                            return ChatResponse(reply=clean_rep, action="search_vault", data=s_res, documents=docs_to_attach if docs_to_attach else None)
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

                    if is_download_or_show:
                        last_asst_msg = (
                            db.query(ChatMessage)
                            .filter(ChatMessage.thread_id == thread_id, ChatMessage.sender == "assistant")
                            .order_by(ChatMessage.id.desc())
                            .first()
                        )
                        target_docs = []
                        if last_asst_msg and last_asst_msg.content:
                            all_docs = db.query(Document).order_by(Document.created_at.desc()).all()
                            for d in all_docs:
                                if d.title and len(d.title) >= 3 and d.title.lower() in last_asst_msg.content.lower():
                                    if d not in target_docs:
                                        target_docs.append(d)
                            if not target_docs:
                                cand_lines = [line.strip(" *🏛️📄:-") for line in last_asst_msg.content.split("\n") if any(k in line.lower() for k in ["f24", "bolletta", "ricevuta", "contratto", "estratto", "certificato", "tessera"])]
                                for cl in cand_lines:
                                    s_res = search_vault_documents(db, cl, thread_id=thread_id)
                                    if s_res:
                                        td = db.query(Document).filter(Document.id == s_res[0]["id"]).first()
                                        if td and td not in target_docs:
                                            target_docs.append(td)

                        if len(target_docs) > 1 and not any(k in lower_t for k in ["entrambi", "tutti", "tutte", "download", "scarica"]):
                            for d in target_docs:
                                d_words = [w for w in re.split(r"[^\w]+", d.title.lower()) if len(w) > 2 and w not in ITALIAN_STOPWORDS]
                                if any(w in lower_t for w in d_words):
                                    target_docs = [d]
                                    break

                        args_card = {"document_ids": [d.id for d in target_docs]} if target_docs else {}
                        card_res = self.execute_tool("show_document_card", args_card, db=db, thread_id=thread_id)
                        c_docs = card_res.get("documents", [])
                        if c_docs:
                            clean_reply = re.sub(r"\[(?:Link per scaricare|Scarica|Download)[^\]]*\]", "la scheda del documento allegata qui sotto", direct_reply, flags=re.IGNORECASE)
                            clean_reply = re.sub(r"per scaricare entrambi i documenti,?\s*dovrai farlo singolarmente\.?", "", clean_reply, flags=re.IGNORECASE).strip()
                            return ChatResponse(
                                reply=clean_reply,
                                action="show_document_card",
                                data=card_res,
                                documents=c_docs
                            )

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

                    # Auto-attachment: se la risposta cita documenti presenti nel DB e documents è vuoto o incompleto
                    if not fallback_docs and (is_doc_intent or is_download_or_show):
                        all_d = db.query(Document).order_by(Document.created_at.desc()).all()
                        found_in_text = []
                        for d in all_d:
                            if d.title and len(d.title) >= 3 and d.title.lower() in direct_reply.lower():
                                fn = Path(d.file_path).name if d.file_path else ""
                                found_in_text.append({
                                    "id": d.id, "document_id": d.id, "thread_id": d.thread_id,
                                    "title": d.title, "issuer": d.issuer, "amount": d.amount,
                                    "due_date": d.due_date.isoformat() if d.due_date else None,
                                    "summary": d.summary, "doc_type": d.doc_type, "status": d.status,
                                    "file_url": f"/uploads/{fn}" if fn else None,
                                    "download_url": f"/api/documents/{d.id}/download", "file_type": d.file_type
                                })
                        if found_in_text:
                            fallback_docs = found_in_text

                    direct_clean = re.sub(r"\[(?:Link per scaricare|Scarica|Download)[^\]]*\]", "la scheda allegata qui sotto", direct_reply, flags=re.IGNORECASE)
                    direct_clean = re.sub(r"per scaricare entrambi i documenti,?\s*dovrai farlo singolarmente\.?", "", direct_clean, flags=re.IGNORECASE).strip()
                    return ChatResponse(
                        reply=direct_clean,
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
        # 0. Eliminazione sicura di documenti o oggetti
        del_resp = self._handle_deletion_intent(user_text, lower_t, db, thread_id=thread_id)
        if del_resp:
            return del_resp

        # 0a. Fallback Google Drive se l'API esterna è irraggiungibile
        drive_resp = self._handle_drive_intent(user_text, lower_t, db, thread_id=thread_id)
        if drive_resp:
            return drive_resp

        # 0a. Collegamento foto/documento a oggetto fisico
        linked_photo_item = self._extract_link_photo_item(user_text)
        if linked_photo_item:
            tool_out = self.execute_tool("link_document_to_item", {"item_name": linked_photo_item}, db=db, thread_id=thread_id)
            if tool_out.get("success"):
                it_name = tool_out.get("item_name", linked_photo_item)
                return ChatResponse(
                    reply=f"✅ Ho associato la foto alla posizione di **{it_name}**! Quando mi chiederai dove si trova, ti mostrerò subito la foto della sua posizione. 📸",
                    action="link_document_to_item",
                    data=tool_out,
                    documents=tool_out.get("documents")
                )
            else:
                return ChatResponse(
                    reply=tool_out.get("error", "Non sono riuscito ad associare la foto all'oggetto."),
                    action="link_document_to_item",
                    data=tool_out
                )

        # 0b. Mostra scheda documento o download
        if any(k in lower_t for k in [
            "scarica", "scaricarla", "scaricarlo", "scaricalo", "scaricala", "scaricarli", "scaricali", "scaricare",
            "download", "fare il download", "voglio scaricare", "voglio il download", "voglio fare il download",
            "apri il documento", "apri il file", "mostramelo", "mostramela", "mostrameli", "fammi vedere il file",
            "fammi vedere il documento", "voglio vederlo", "voglio vederla", "apri il pdf", "mostra la scheda",
            "vedi il documento", "mandami il pdf"
        ]):
            last_asst_msg = (
                db.query(ChatMessage)
                .filter(ChatMessage.thread_id == thread_id, ChatMessage.sender == "assistant")
                .order_by(ChatMessage.id.desc())
                .first()
            )
            target_docs = []
            if last_asst_msg and last_asst_msg.content:
                all_docs = db.query(Document).order_by(Document.created_at.desc()).all()
                for d in all_docs:
                    if d.title and len(d.title) >= 3 and d.title.lower() in last_asst_msg.content.lower():
                        if d not in target_docs:
                            target_docs.append(d)
                if not target_docs:
                    cand_lines = [line.strip(" *🏛️📄:-") for line in last_asst_msg.content.split("\n") if any(k in line.lower() for k in ["f24", "bolletta", "ricevuta", "contratto", "estratto", "certificato", "tessera"])]
                    for cl in cand_lines:
                        s_res = search_vault_documents(db, cl, thread_id=thread_id)
                        if s_res:
                            td = db.query(Document).filter(Document.id == s_res[0]["id"]).first()
                            if td and td not in target_docs:
                                target_docs.append(td)

            if len(target_docs) > 1 and not any(k in lower_t for k in ["entrambi", "tutti", "tutte", "download", "scarica"]):
                for d in target_docs:
                    d_words = [w for w in re.split(r"[^\w]+", d.title.lower()) if len(w) > 2 and w not in ITALIAN_STOPWORDS]
                    if any(w in lower_t for w in d_words):
                        target_docs = [d]
                        break

            args_card = {"document_ids": [d.id for d in target_docs]} if target_docs else {}
            card_res = self.execute_tool("show_document_card", args_card, db=db, thread_id=thread_id)
            c_docs = card_res.get("documents", [])
            if c_docs:
                if len(c_docs) > 1:
                    rep = f"📄 Ecco le schede per i documenti richiesti! Puoi visualizzarli con 'Vedi' o scaricarli direttamente con il pulsante 'Scarica' qui sotto. ⬇️"
                else:
                    rep = f"📄 Ecco la scheda per **{c_docs[0]['title']}**! Puoi visualizzarlo o scaricarlo direttamente dalla scheda qui sotto. ⬇️"
                return ChatResponse(
                    reply=rep,
                    action="show_document_card",
                    data=card_res,
                    documents=c_docs
                )

        # 1. Rinomina documento / foto
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
            (
                any(k in lower_t for k in [
                    "lista", "elenco", "elencami", "quali documenti", "quali oggetti",
                    "mostrami tutti", "mostrami tutte", "mostra tutti", "mostra tutte",
                    "cosa c'è nel caveau", "cosa ce nel caveau", "cosa ho nel caveau", "cosa hai nel caveau",
                    "vedere tutti", "vedere tutte", "tutti i documenti", "tutti gli oggetti", "che oggetti", "che documenti"
                ])
                or lower_t.strip(" !.?") in ["documenti", "oggetti", "tutti i documenti", "tutti gli oggetti", "tutto", "i miei documenti", "i miei oggetti"]
            )
            and not any(k in lower_t for k in ["elimina", "cancella", "rimuovi", "butta", "eliminami", "cancellami", "svuota", "eliminali", "cancellali", "rimuovili"])
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
            r"^(?:dov'è|dov'e|dove ho messo|dove sono|dove|cerca|trovami|trova|dammi|mostrami|apri|visualizza|prendi|scarica|vedi)\s*(?:il|la|lo|le|i|l'|un|una|uno)?\s*",
            "", lower_t
        ).strip(" ?.")
        clean_q = search_q or user_text
        if len(clean_q) >= 2:
            s_res = self.execute_tool("search_vault", {"query": clean_q}, db=db, thread_id=thread_id)
            f_docs = s_res.get("found_documents", [])
            f_items = s_res.get("found_physical_items", [])
            is_where_intent = any(k in lower_t for k in ["dov'è", "dov'e", "dove è", "dove sono", "dove si trova", "dove si trovano", "dove ho messo", "dove ho riposto", "dove ho lasciato", "dove sta", "dove stanno"])
            if is_where_intent and f_items:
                it = f_items[0]
                loc = it['primary_location'] + (f" ({it['detailed_location']})" if it.get('detailed_location') else "")
                linked_d = None
                if it.get("document_id"):
                    d_rec = db.query(Document).filter(Document.id == it["document_id"]).first()
                    if d_rec:
                        fn = Path(d_rec.file_path).name if d_rec.file_path else ""
                        linked_d = {
                            "id": d_rec.id, "document_id": d_rec.id, "title": d_rec.title,
                            "issuer": d_rec.issuer, "amount": d_rec.amount,
                            "due_date": d_rec.due_date.isoformat() if d_rec.due_date else None,
                            "summary": d_rec.summary,
                            "file_url": f"/uploads/{fn}" if fn else None,
                            "download_url": f"/api/documents/{d_rec.id}/download",
                            "file_type": d_rec.file_type
                        }
                elif it.get("image_url"):
                    linked_d = {
                        "id": it.get("item_id"), "document_id": it.get("item_id"), "title": f"Foto {it['item_name']}",
                        "file_url": it["image_url"], "download_url": it["image_url"], "file_type": "image"
                    }
                photo_note = "\n📸 Ho allegato la foto della posizione qui sotto!" if (it.get("has_photo") or linked_d) else ""
                return ChatResponse(
                    reply=f"📍 **{it['item_name']}** si trova in: {loc}.{photo_note}",
                    action="search_vault",
                    data=s_res,
                    documents=[linked_d] if linked_d else None
                )

            if f_docs:
                if len(f_docs) == 1:
                    d = f_docs[0]
                    amt_str = f" ({d['amount']:.2f} €)" if d.get('amount') else ""
                    due_str = f" - scadenza: {d['due_date']}" if d.get('due_date') else ""
                    return ChatResponse(
                        reply=f"📄 Ho trovato il documento **{d['title']}**{amt_str}{due_str}:\n💡 {d.get('summary', '')}",
                        action="show_document_card",
                        data=s_res,
                        documents=[d]
                    )
                else:
                    lines = [f"- 📄 **{d['title']}** ({d.get('issuer') or d.get('doc_type', '')})" for d in f_docs]
                    rep = (
                        f"📄 Ho trovato i seguenti **{len(f_docs)} documenti** nel caveau:\n\n" +
                        "\n".join(lines) +
                        "\n\nEcco le schede con i pulsanti 'Vedi' e 'Scarica' per ciascun file qui sotto! ⬇️"
                    )
                    return ChatResponse(
                        reply=rep,
                        action="show_document_card",
                        data=s_res,
                        documents=f_docs
                    )
            if f_items:
                it = f_items[0]
                loc = it['primary_location'] + (f" ({it['detailed_location']})" if it.get('detailed_location') else "")
                linked_d = None
                if it.get("document_id"):
                    d_rec = db.query(Document).filter(Document.id == it["document_id"]).first()
                    if d_rec:
                        fn = Path(d_rec.file_path).name if d_rec.file_path else ""
                        linked_d = {
                            "id": d_rec.id, "document_id": d_rec.id, "title": d_rec.title,
                            "issuer": d_rec.issuer, "amount": d_rec.amount,
                            "due_date": d_rec.due_date.isoformat() if d_rec.due_date else None,
                            "summary": d_rec.summary,
                            "file_url": f"/uploads/{fn}" if fn else None,
                            "download_url": f"/api/documents/{d_rec.id}/download",
                            "file_type": d_rec.file_type
                        }
                elif it.get("image_url"):
                    linked_d = {
                        "id": it.get("item_id"), "document_id": it.get("item_id"), "title": f"Foto {it['item_name']}",
                        "file_url": it["image_url"], "download_url": it["image_url"], "file_type": "image"
                    }
                photo_note = "\n📸 Ho allegato la foto della posizione qui sotto!" if (it.get("has_photo") or linked_d) else ""
                return ChatResponse(
                    reply=f"📍 **{it['item_name']}** si trova in: {loc}.{photo_note}",
                    action="search_vault",
                    data=s_res,
                    documents=[linked_d] if linked_d else None
                )

        return ChatResponse(
            reply=f"Non ho trovato nessun documento o oggetto corrispondente a '{user_text}' nel tuo caveau. Puoi chiedermi dove si trova un oggetto, cercare un documento o verificare le scadenze!",
            action="REPLY"
        )


AgentService = AgenticChatService

