import sys
import time
import threading
import urllib.request
import logging
import uvicorn

from app.config import get_settings
from app.main import app

logger = logging.getLogger(__name__)

class ServerThread(threading.Thread):
    def __init__(self, host: str, port: int):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.config = uvicorn.Config(app, host=self.host, port=self.port, log_level="warning")
        self.server = uvicorn.Server(self.config)

    def run(self):
        self.server.run()

    def stop(self):
        self.server.should_exit = True


def wait_for_server(url: str, timeout: float = 10.0) -> bool:
    """Attende che il server FastAPI sia pronto e risponda prima di aprire la finestra."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.1)
    return False


def get_lan_ip() -> str:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'
    finally:
        s.close()


def start_desktop_app(host: str = "0.0.0.0", port: int = 8000, debug: bool = False):
    """
    Avvia l'applicazione nativa Desktop Windows ("Dove lo AI messo")
    incorporando FastAPI e WebView2 in una finestra standalone.
    """
    try:
        import webview
    except ImportError:
        print("[ERRORE] pywebview non installato. Esegui: pip install pywebview")
        sys.exit(1)

    lan_ip = get_lan_ip()
    print("=" * 64)
    print("  DOVE LO AI MESSO - Server Locale Attivo")
    print(f"  • Computer Desktop : http://127.0.0.1:{port}")
    print(f"  • Smartphone / APK : http://{lan_ip}:{port}")
    print("=" * 64)

    server_thread = ServerThread(host=host, port=port)
    server_thread.start()

    webview_host = "127.0.0.1" if host == "0.0.0.0" else host
    url = f"http://{webview_host}:{port}"
    ready = wait_for_server(url, timeout=12.0)
    if not ready:
        print("[AVVISO] Il server sta impiegando più tempo del previsto per avviarsi...")

    print("[*] Creazione della finestra Desktop nativa...")
    window = webview.create_window(
        title="Dove lo AI messo - Desktop",
        url=url,
        width=1280,
        height=880,
        min_size=(960, 640),
        resizable=True,
        text_select=True,
        confirm_close=False,
        background_color="#EFEAE2"
    )

    try:
        # Avvia il loop grafico della finestra nativa
        webview.start(debug=debug)
    finally:
        print("[*] Chiusura finestra: arresto del server...")
        server_thread.stop()
        print("[*] Applicazione chiusa correttamente.")


if __name__ == "__main__":
    start_desktop_app()
