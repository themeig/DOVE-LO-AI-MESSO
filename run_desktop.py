#!/usr/bin/env python3
"""
Dove lo AI messo - Desktop Application Launcher
Avvia l'assistente e il caveau in una finestra desktop nativa per Windows con accesso al file system locale.
Supporta l'avvio di istanze multiple contemporanee con profili/sessioni isolate per testare chat di gruppo ed eventi live.
"""
import argparse
import sys
from app.desktop import start_desktop_app

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Dove lo AI messo - Desktop Multi-Instance Launcher",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host di binding per il server locale")
    parser.add_argument("--port", "-p", type=int, default=8000, help="Porta HTTP del server locale")
    parser.add_argument("--profile", type=str, default=None, help="Nome sessione o profilo isolato (es. sessione_1, sessione_2)")
    parser.add_argument("--user", "-u", type=str, default=None, help="Utente simulato (es. 1/marco, 2/laura, 3/giuseppe)")
    parser.add_argument("--clean", "--new", action="store_true", help="Avvia sessione pulita senza credenziali salvate")
    parser.add_argument("--debug", action="store_true", help="Abilita developer tools nella finestra desktop")

    args = parser.parse_args()
    start_desktop_app(
        host=args.host,
        port=args.port,
        debug=args.debug,
        profile=args.profile,
        user=args.user,
        clean=args.clean
    )
