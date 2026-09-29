"""
Test suite per il Connection Manager WebSocket e il broadcast delle notifiche di gruppo in tempo reale.
"""
import asyncio
from app.services.websocket_manager import GroupWebSocketManager


def test_websocket_manager_connect_and_broadcast():
    async def _run():
        manager = GroupWebSocketManager()

        class DummyWS:
            def __init__(self):
                self.sent = []
                self.accepted = False

            async def accept(self):
                self.accepted = True

            async def send_json(self, data):
                self.sent.append(data)

        ws1 = DummyWS()
        ws2 = DummyWS()

        await manager.connect("group-1", ws1)
        await manager.connect("group-1", ws2)

        assert ws1.accepted is True
        assert ws2.accepted is True

        # Broadcast a tutti i membri connessi del gruppo 1
        await manager.broadcast("group-1", {"event": "DOCUMENT_UPLOADED", "title": "Bolletta Enel"})
        assert len(ws1.sent) == 1
        assert len(ws2.sent) == 1
        assert ws1.sent[0]["event"] == "DOCUMENT_UPLOADED"

        # Disconnessione ws1 e nuovo broadcast
        manager.disconnect("group-1", ws1)
        await manager.broadcast("group-1", {"event": "DOCUMENT_PAID", "title": "Enel Saldata"})
        assert len(ws1.sent) == 1
        assert len(ws2.sent) == 2
        assert ws2.sent[1]["event"] == "DOCUMENT_PAID"

    asyncio.run(_run())


def test_websocket_manager_broadcast_sync():
    async def _run():
        manager = GroupWebSocketManager()

        class DummyWS:
            def __init__(self):
                self.sent = []
                self.accepted = False

            async def accept(self):
                self.accepted = True

            async def send_json(self, data):
                self.sent.append(data)

        ws = DummyWS()
        await manager.connect("group-sync", ws)

        # Broadcast sync
        manager.broadcast_sync("group-sync", {"event": "MEMBER_JOINED", "name": "Mario"})
        # Yield to let created task execute
        await asyncio.sleep(0.05)

        assert len(ws.sent) == 1
        assert ws.sent[0]["event"] == "MEMBER_JOINED"

    asyncio.run(_run())
