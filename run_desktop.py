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
    parser.add_argument("--profile", "-u", type=str, default=None, help="Nome sessione o profilo isolato (es. 1, 2, laura, test)")
    parser.add_argument("--debug", action="store_true", help="Abilita developer tools nella finestra desktop")

    args = parser.parse_args()
    start_desktop_app(host=args.host, port=args.port, debug=args.debug, profile=args.profile)
