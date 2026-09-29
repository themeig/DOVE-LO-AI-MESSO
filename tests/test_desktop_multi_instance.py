"""
Test suite per la gestione multi-istanza desktop e l'isolamento dei profili sessione.
Verifica che finestre desktop multiple possano essere avviate contemporaneamente
con profili isolati per consentire il testing delle chat di gruppo tra account diversi.
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.desktop import (
    acquire_desktop_profile,
    check_existing_vault_server,
    wait_for_server
)


def test_acquire_desktop_profile_isolation(tmp_path):
    """Verifica che istanze contemporanee acquisiscano profili separati e lock esclusivi."""
    profiles_base = tmp_path / "profiles"

    # Istanza 1
    name1, dir1, handle1 = acquire_desktop_profile(profiles_base)
    assert name1 == "sessione_1"
    assert Path(dir1).exists()
    assert handle1 is not None

    # Istanza 2 (mentre Istanza 1 è attiva)
    name2, dir2, handle2 = acquire_desktop_profile(profiles_base)
    assert name2 == "sessione_2"
    assert Path(dir2).exists()
    assert dir1 != dir2
    assert handle2 is not None

    # Istanza 3
    name3, dir3, handle3 = acquire_desktop_profile(profiles_base)
    assert name3 == "sessione_3"
    assert dir3 != dir2 and dir3 != dir1
    assert handle3 is not None

    # Rilascio istanza 1
    handle1.close()

    # Nuova richiesta: sessione_1 deve tornare disponibile
    name_reused, dir_reused, handle_reused = acquire_desktop_profile(profiles_base)
    assert name_reused == "sessione_1"
    assert dir_reused == dir1

    # Pulizia
    if handle2:
        handle2.close()
    if handle3:
        handle3.close()
    if handle_reused:
        handle_reused.close()


def test_acquire_desktop_profile_custom_name(tmp_path):
    """Verifica che un profilo personalizzato (es. 'laura') venga acquisito correttamente."""
    profiles_base = tmp_path / "profiles"
    name, pdir, handle = acquire_desktop_profile(profiles_base, requested_profile="laura")
    assert name == "laura"
    assert "laura" in pdir
    assert Path(pdir).exists()
    if handle:
        handle.close()


def test_check_existing_vault_server_offline():
    """Verifica che su porta libera o non attiva restituisca False."""
    is_active = check_existing_vault_server(host="127.0.0.1", port=59999)
    assert is_active is False


def test_check_existing_vault_server_online():
    """Verifica che quando il server risponde correttamente restituisca True."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b'{"version": "2.14.0", "app_name": "Dove lo AI messo"}'
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        is_active = check_existing_vault_server(host="127.0.0.1", port=8000)
        assert is_active is True
