"""
Gestore delle connessioni WebSockets per la sincronizzazione real-time delle attività di gruppo.
Permette a tutti i dispositivi e membri connessi a uno stesso caveau di ricevere istantaneamente
gli aggiornamenti di protocollo (nuove bollette caricate, pagamenti quietanzati, promemoria scadenze).
"""
import logging
from typing import Dict, List, Any
from collections import defaultdict

logger = logging.getLogger(__name__)


class GroupWebSocketManager:
    """Connection manager per stanze di gruppo isolate."""

    def __init__(self):
        self._connections: Dict[str, List[Any]] = defaultdict(list)

    async def connect(self, group_id: str, websocket: Any):
        """Accetta e registra una nuova connessione WebSocket per un determinato gruppo."""
        await websocket.accept()
        self._connections[group_id].append(websocket)
        logger.info(f"WebSocket connesso per gruppo {group_id} (totale connessi: {len(self._connections[group_id])})")

    def disconnect(self, group_id: str, websocket: Any):
        """Rimuove in sicurezza la connessione WebSocket disconnessa."""
        if group_id in self._connections:
            if websocket in self._connections[group_id]:
                self._connections[group_id].remove(websocket)
            if not self._connections[group_id]:
                del self._connections[group_id]
        logger.info(f"WebSocket disconnesso per gruppo {group_id}")

    async def broadcast(self, group_id: str, message: dict):
        """
        Invia un messaggio JSON a tutti i client attivi collegati al gruppo specificato.
        Supporta sia identificativi con prefisso 'group_' che raw UUID/ID.
        Rimuove automaticamente le connessioni non più attive o interrotte.
        """
        targets = [group_id]
        if group_id.startswith("group_"):
            targets.append(group_id[6:])
        else:
            targets.append(f"group_{group_id}")

        for gid in set(targets):
            if gid not in self._connections:
                continue

            dead_connections = []
            for ws in list(self._connections[gid]):
                try:
                    await ws.send_json(message)
                except Exception as e:
                    logger.warning(f"Errore broadcast su client WebSocket nel gruppo {gid}: {e}")
                    dead_connections.append(ws)

            for dead_ws in dead_connections:
                self.disconnect(gid, dead_ws)

    def broadcast_sync(self, group_id: str, message: dict):
        """
        Versione sicura e non-bloccante di broadcast invocabile da endpoint o thread sincroni.
        """
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast(group_id, message))
        except RuntimeError:
            try:
                asyncio.run(self.broadcast(group_id, message))
            except Exception as e:
                logger.warning(f"Errore broadcast_sync su gruppo {group_id}: {e}")


group_ws_manager = GroupWebSocketManager()
