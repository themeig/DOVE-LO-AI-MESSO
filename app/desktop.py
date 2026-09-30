import os
import sys
import time
import json
import threading
import urllib.request
import logging
from pathlib import Path
from typing import Tuple, Optional
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


def check_existing_vault_server(host: str = "127.0.0.1", port: int = 8000) -> bool:
    """
    Verifica se il server FastAPI di 'Dove lo AI messo' è già attivo e in ascolto sulla porta specificata.
    Controlla sia l'endpoint /api/version che la root /.
    """
    check_host = "127.0.0.1" if host == "0.0.0.0" else host
    url = f"http://{check_host}:{port}/api/version"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DoveLoAIMessoDesktopLauncher"})
        with urllib.request.urlopen(req, timeout=1.2) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if "app_name" in data or "version" in data:
                    return True
    except Exception:
        pass

    try:
        req = urllib.request.Request(f"http://{check_host}:{port}/", headers={"User-Agent": "DoveLoAIMessoDesktopLauncher"})
        with urllib.request.urlopen(req, timeout=1.2) as resp:
            if resp.status == 200:
                return True
    except Exception:
        pass

    return False


def _lock_file(handle):
    """Acquisisce un lock non bloccante sul file per identificare sessioni desktop attive."""
    if sys.platform == "win32":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def acquire_desktop_profile(profiles_base: Path, requested_profile: Optional[str] = None) -> Tuple[str, str, any]:
    """
    Trova e acquisisce in modo esclusivo un profilo WebView2 per garantire
    che finestre desktop multiple abbiano storage, cookie e sessioni isolate
    (consentendo di testare chat di gruppo tra account differenti contemporaneamente).
    Restituisce: (profile_name, profile_dir_path, lock_file_handle)
    """
    profiles_base.mkdir(parents=True, exist_ok=True)

    if requested_profile:
        cleaned = requested_profile.strip()
        if cleaned.isdigit():
            candidates = [f"sessione_{cleaned}"]
        else:
            candidates = [cleaned]
    else:
        candidates = [f"sessione_{i}" for i in range(1, 20)]

    for name in candidates:
        prof_dir = profiles_base / name
        lock_file = profiles_base / f"{name}.lock"
        try:
            prof_dir.mkdir(parents=True, exist_ok=True)
            handle = open(lock_file, "a+")
            handle.seek(0)
            _lock_file(handle)
            handle.truncate(0)
            handle.write(f"PID: {os.getpid()}\n")
            handle.flush()
            return name, str(prof_dir.resolve()), handle
        except (OSError, PermissionError):
            if requested_profile:
                print(f"[AVVISO] Il profilo '{requested_profile}' è già in uso. Ricerca sessione alternativa...")
                return acquire_desktop_profile(profiles_base, None)
            continue

    fallback_name = f"sessione_temp_{os.getpid()}"
    fallback_dir = profiles_base / fallback_name
    fallback_dir.mkdir(parents=True, exist_ok=True)
    return fallback_name, str(fallback_dir.resolve()), None


def get_lan_ip() -> str:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def start_desktop_app(
    host: str = "0.0.0.0",
    port: int = 8000,
    debug: bool = False,
    profile: Optional[str] = None,
    user: Optional[str] = None,
    clean: bool = False
):
    """
    Avvia l'applicazione nativa Desktop Windows ("Dove lo AI messo")
    incorporando FastAPI e WebView2 in una finestra standalone.
    Supporta multi-istanza automatica: se un'istanza primaria è già attiva,
    la seconda istanza si collega al server esistente e apre una finestra
    con sessione/profilo isolata per testare account e chat di gruppo.
    """
    try:
        import webview
    except ImportError:
        print("[ERRORE] pywebview non installato. Esegui: pip install pywebview")
        sys.exit(1)

    lan_ip = get_lan_ip()
    webview_host = "127.0.0.1" if host == "0.0.0.0" else host
    url = f"http://{webview_host}:{port}"

    # 1. Rileva se un'istanza del server è già in esecuzione
    is_server_already_running = check_existing_vault_server(host=host, port=port)
    server_thread = None

    if is_server_already_running:
        print("=" * 64)
        print("  DOVE LO AI MESSO - Server Locale Esistente Rilevato!")
        print(f"  • Collegamento all'istanza attiva su porta : {port}")
        print(f"  • Computer Desktop : {url}")
        print(f"  • Smartphone / APK : http://{lan_ip}:{port}")
        print("  • Avvio nuova finestra desktop multi-istanza indipendente...")
        print("=" * 64)
    else:
        print("=" * 64)
        print("  DOVE LO AI MESSO - Avvio Server Locale Primario")
        print(f"  • Computer Desktop : {url}")
        print(f"  • Smartphone / APK : http://{lan_ip}:{port}")
        print("=" * 64)
        server_thread = ServerThread(host=host, port=port)
        server_thread.start()

        ready = wait_for_server(url, timeout=12.0)
        if not ready:
            print("[AVVISO] Il server sta impiegando più tempo del previsto per avviarsi...")

    # 2. Assegna un profilo isolato per consentire login indipendenti
    profiles_base = get_settings().BASE_DIR / "storage" / "desktop_profiles"
    profile_name, profile_dir, lock_handle = acquire_desktop_profile(profiles_base, requested_profile=profile)

    # Se richiesto avvio pulito, rimuovi cache sessione precedente
    if clean:
        import shutil
        print(f"[*] Pulizia storage per sessione pulita: {profile_dir}")
        try:
            shutil.rmtree(profile_dir, ignore_errors=True)
            Path(profile_dir).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    # 3. Mappatura automatica utente simulato per test chat condivisa
    user_mapping = {
        "1": ("marco", "Marco Rossi"),
        "marco": ("marco", "Marco Rossi"),
        "2": ("laura", "Laura Bianchi"),
        "laura": ("laura", "Laura Bianchi"),
        "3": ("giuseppe", "Giuseppe Verdi"),
        "giuseppe": ("giuseppe", "Giuseppe Verdi"),
        "marcone": ("marcone", "Marcone")
    }

    sim_key = None
    display_name = None
    if user:
        cleaned_user = user.strip().lower()
        if cleaned_user in user_mapping:
            sim_key, display_name = user_mapping[cleaned_user]
        else:
            sim_key = cleaned_user
            display_name = user.strip().capitalize()
    elif not clean:
        if profile_name == "sessione_1":
            sim_key, display_name = "marco", "Marco Rossi"
        elif profile_name == "sessione_2":
            sim_key, display_name = "laura", "Laura Bianchi"
        elif profile_name == "sessione_3":
            sim_key, display_name = "giuseppe", "Giuseppe Verdi"

    # Aggiorna URL e titolo finestra
    if sim_key and not clean:
        url = f"{url}?sim_user={sim_key}"
        window_title = f"Dove lo AI messo - Desktop [{display_name}]"
    else:
        session_num = profile_name.replace("sessione_", "").capitalize()
        window_title = f"Dove lo AI messo - Desktop (Sessione {session_num})"

    print(f"[*] Profilo finestra: {profile_name} (Storage: {profile_dir})")
    if sim_key:
        print(f"[*] Simulazione Utente Attiva: {display_name} ({sim_key})")
    print(f"[*] Creazione della finestra Desktop: '{window_title}'...")

    window = webview.create_window(
        title=window_title,
        url=url,
        width=1280,
        height=880,
        min_size=(960, 640),
        resizable=True,
        text_select=True,
        confirm_close=False,
        background_color="#F8F5EE"
    )

    try:
        # Avvia il loop grafico con profilo isolato
        webview.start(
            debug=debug,
            storage_path=profile_dir,
            private_mode=False
        )
    finally:
        # Rilascia il lockfile di sessione
        if lock_handle:
            try:
                lock_handle.close()
            except Exception:
                pass

        # Arresta il server solo se questa istanza è il server primario
        if server_thread is not None:
            print("[*] Chiusura istanza primaria: arresto del server...")
            server_thread.stop()
            print("[*] Server arrestato correttamente.")
        else:
            print(f"[*] Finestra secondaria ({profile_name}) chiusa. Il server primario rimane attivo.")


if __name__ == "__main__":
    start_desktop_app()
