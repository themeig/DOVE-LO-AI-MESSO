"""
Script di bundling ed aggregazione per i moduli frontend di 'Dove lo AI messo'.
Assembla ordinatamente i singoli moduli di static/js/modules/ in static/js/app-bundle.js.
"""
from pathlib import Path

MODULES_DIR = Path("static/js/modules")
BUNDLE_FILE = Path("static/js/app-bundle.js")

MODULE_ORDER = [
    "01-core.js",
    "02-navigation.js",
    "03-threads.js",
    "04-cloud.js",
    "05-chat.js",
    "06-panel.js",
    "07-modals.js",
]

def build_bundle():
    print(f"Aggregazione moduli frontend da {MODULES_DIR} a {BUNDLE_FILE}...")
    bundle_parts = [
        "/**\n",
        " * DOVE LO AI MESSO - Frontend App Bundle (Compilato da Architettura Modulare)\n",
        " * Moduli sorgente situati in: static/js/modules/\n",
        " * 1. 01-core.js: Autenticazione, Badge Versione, Sicurezza & Lock Screen\n",
        " * 2. 02-navigation.js: Carousel Slide, Touch Gestures 1:1 & Popstate\n",
        " * 3. 03-threads.js: Canali Conversazionali, Gruppi, Modelli AI & Schede Sistema\n",
        " * 4. 04-cloud.js: Google Drive Cloud Sync & Google Calendar Sync\n",
        " * 5. 05-chat.js: Chat Engine, Vocale Whisper, Markdown & Schede Protocollo\n",
        " * 6. 06-panel.js: Hub Pannello 4 Quadrati, FinTech KPI, Ledger & Scadenze\n",
        " * 7. 07-modals.js: Viewer File Office/PDF, Backup ZIP & Folders Watcher\n",
        " */\n\n"
    ]

    for mod_name in MODULE_ORDER:
        mod_path = MODULES_DIR / mod_name
        if not mod_path.exists():
            raise FileNotFoundError(f"Modulo mancante: {mod_path}")
        with open(mod_path, "r", encoding="utf-8") as f:
            content = f.read()
        bundle_parts.append(f"\n// >>> INIZIO MODULO: {mod_name} <<<\n")
        bundle_parts.append(content)
        bundle_parts.append(f"\n// <<< FINE MODULO: {mod_name} >>>\n\n")

    full_bundle = "".join(bundle_parts)
    with open(BUNDLE_FILE, "w", encoding="utf-8") as out:
        out.write(full_bundle)

    print(f"Bundle generato con successo! Dimensione: {len(full_bundle)} bytes.")

if __name__ == "__main__":
    build_bundle()
