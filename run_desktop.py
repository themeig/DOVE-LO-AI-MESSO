#!/usr/bin/env python3
"""
Dove lo AI messo - Desktop Application Launcher
Avvia l'assistente e il caveau in una finestra desktop nativa per Windows con accesso al file system locale.
"""
import sys
from app.desktop import start_desktop_app

if __name__ == "__main__":
    debug = "--debug" in sys.argv
    start_desktop_app(host="127.0.0.1", port=8000, debug=debug)
