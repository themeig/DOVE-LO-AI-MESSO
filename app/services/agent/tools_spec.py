# Definizione JSON Schema dei 20 tool ufficiali del Caveau

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
            "name": "recategorize_vault_document",
            "description": (
                "Modifica o assegna la sezione/categoria tematica di un documento nel caveau "
                "(es. 'spostalo in Canzoni', 'crea la sezione Ricette e metti questo file', 'metti la ricevuta in Spese Auto', 'sposta in Utenze & Bollette'). "
                "Puoi creare qualsiasi nuova sezione a tua discrezione o su richiesta dell'utente. "
                "NOTA: Gli oggetti fisici hanno una sezione separata nell'inventario e non sono categorie di documenti; se un file ritrae un oggetto, catalogalo in 'Foto & Immagini'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category_label": {
                        "type": "string",
                        "description": "Il titolo visibile ed elegante della sezione/categoria (es. 'Canzoni & Testi Musicali', 'Ricette & Cucina', 'Appunti Universitari', 'Automobili & Manutenzione')"
                    },
                    "document_id": {
                        "type": "integer",
                        "description": "ID numerico opzionale del documento da spostare o ricatalogare. Se non fornito, fa riferimento all'ultimo documento o a quello cercato per titolo."
                    },
                    "document_title": {
                        "type": "string",
                        "description": "Titolo o nome del documento da ricatalogare (es. 'Testo Canzone', 'Modello F24')"
                    },
                    "category": {
                        "type": "string",
                        "description": "Slug normalizzato opzionale della categoria (es. 'canzoni_musica', 'ricette_cucina')"
                    },
                    "category_icon": {
                        "type": "string",
                        "description": "Icona FontAwesome 6 adatta (es. 'fa-music', 'fa-utensils', 'fa-graduation-cap', 'fa-car', 'fa-paw', 'fa-bolt', 'fa-landmark')"
                    },
                    "subfolder": {
                        "type": "string",
                        "description": "Sottocartella temporale o tematica opzionale (es. '2026', '2025', 'Locazioni', 'Bozze'). Se omessa, viene dedotta automaticamente dall'anno di scadenza o dal testo del documento."
                    }
                },
                "required": ["category_label"]
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
                "('dual' = locale + cloud, 'cloud_only' = solo Google Drive, o 'local_only' = solo locale nel caveau), l'account Google associato, "
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
    },
    {
        "type": "function",
        "function": {
            "name": "read_vault_document_content",
            "description": (
                "Legge, ispeziona ed estrae il contenuto tabellare e testuale reale e puntuale di un file salvato nel caveau "
                "(es. fogli di calcolo Excel .xlsx/.xls, file CSV, documenti Word .docx, PDF o file di testo). "
                "DEVI USARLO OBBLIGATORIAMENTE quando l'utente fa domande specifiche sui dati interni di un file "
                "(es. 'cosa c'è nella riga 4?', 'qual è l'importo nel foglio?', 'leggimi la colonna B', 'chi ha fatturato di più nel file Excel?', "
                "'quante righe ci sono?', 'cerca il valore Y nella tabella'). "
                "DIVIETO ASSOLUTO DI INVENTARE DATI O NUMERI: usa sempre questo strumento per consultare i dati effettivi."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "integer",
                        "description": "ID numerico opzionale del documento da ispezionare nel caveau."
                    },
                    "document_title": {
                        "type": "string",
                        "description": "Titolo o nome del file da leggere (es. 'Bilancio 2026', 'Fatturato.xlsx', 'Spese Casa')."
                    },
                    "sheet_name": {
                        "type": "string",
                        "description": "Nome del foglio di calcolo Excel da leggere (se omesso o vuoto, legge il primo foglio)."
                    },
                    "query": {
                        "type": "string",
                        "description": "Parola chiave o valore per filtrare e trovare righe specifiche all'interno della tabella o del documento."
                    },
                    "max_rows": {
                        "type": "integer",
                        "description": "Numero massimo di righe da estrarre (default 50)."
                    }
                }
            }
        }
    }
]

