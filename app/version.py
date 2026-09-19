"""
Modulo di definizione centralizzata della versione dell'applicazione 'Dove lo AI messo'.

REGOLA DI SVILUPPO OBBLIGATORIA (AGENTS.md):
Ogni volta che viene implementata una modifica al codice, una correzione di bug
o una nuova funzionalità, il numero di versione DEVE essere incrementato.
Convenzione SemVer (MAJOR.MINOR.PATCH):
- PATCH: piccoli fix, miglioramenti grafici, correzioni testuali.
- MINOR: nuove funzionalità, nuovi endpoint, integrazioni, MCP tools ed estensioni agent.
- MAJOR: refactoring architetturali o modifiche strutturali/breaking.
"""

__version__ = "1.7.4"
APP_VERSION = __version__


