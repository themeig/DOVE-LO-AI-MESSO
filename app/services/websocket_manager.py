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
        Rimuove automaticamente le connessioni non più attive o interrotte.
        """
        if group_id not in self._connections:
            return

        dead_connections = []
        for ws in list(self._connections[group_id]):
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.warning(f"Errore broadcast su client WebSocket nel gruppo {group_id}: {e}")
                dead_connections.append(ws)

        for dead_ws in dead_connections:
            self.disconnect(group_id, dead_ws)


group_ws_manager = GroupWebSocketManager()
