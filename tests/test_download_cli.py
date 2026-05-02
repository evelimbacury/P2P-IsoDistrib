"""
Testes unitários para o comando 'download' da CLI em src/peer/client.py.

Foca nos caminhos de erro e sucesso do comando sem precisar de rede real,
usando monkeypatch em send_lookup e download_file_parallel.
"""
import pytest

import src.peer.client as client_module
from src.peer.client import run_cli


class _MockSock:
    """Socket falso para evitar I/O real nos testes de CLI."""
    def close(self):
        pass


@pytest.fixture(autouse=True)
def reset_client_globals(monkeypatch):
    """Reseta variáveis globais de client.py entre testes."""
    client_module.shutdown_event.clear()
    client_module.offline_mode = False
    monkeypatch.setattr(client_module, "send_register", lambda *a, **k: None)
    yield
    client_module.shutdown_event.clear()
    client_module.offline_mode = False


def _mock_input(*commands):
    """Retorna um callable que simula `input()` consumindo os comandos em ordem."""
    it = iter(commands)
    return lambda _prompt: next(it, "exit")


def _noop_unregister(*args, **kwargs):
    return True


# ==============================================================================
# Casos de erro de validação
# ==============================================================================

def test_download_without_args_prints_usage(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", _mock_input("download", "exit"))
    monkeypatch.setattr(client_module, "send_unregister", _noop_unregister)

    with pytest.raises(SystemExit):
        run_cli(_MockSock(), 6000)

    assert "[Error] Usage: download <filename>" in capsys.readouterr().out


def test_download_with_null_tracker_prints_error(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", _mock_input("download test.iso", "exit"))

    with pytest.raises(SystemExit):
        run_cli(None, 6000)

    assert "[Error] Cannot download: not connected to tracker" in capsys.readouterr().out


def test_download_no_peers_available_prints_message(monkeypatch, capsys):
    file_info = {"name": "test.iso", "size": 1024, "sha256": "abc"}

    monkeypatch.setattr(client_module, "send_lookup", lambda *a, **k: {
        "status": "FOUND", "file_info": file_info, "peers": [],
    })
    monkeypatch.setattr("builtins.input", _mock_input("download test.iso", "exit"))
    monkeypatch.setattr(client_module, "send_unregister", _noop_unregister)

    with pytest.raises(SystemExit):
        run_cli(_MockSock(), 6000)

    assert "[Download] No peers available for test.iso" in capsys.readouterr().out


def test_download_lookup_returns_none_does_nothing_extra(monkeypatch, capsys):
    """Quando send_lookup retorna None (já imprime erro internamente) não deve
    aparecer mensagem adicional de saved/failed."""
    monkeypatch.setattr(client_module, "send_lookup", lambda *a, **k: None)
    monkeypatch.setattr("builtins.input", _mock_input("download test.iso", "exit"))
    monkeypatch.setattr(client_module, "send_unregister", _noop_unregister)

    with pytest.raises(SystemExit):
        run_cli(_MockSock(), 6000)

    out = capsys.readouterr().out
    assert "[Download] Saved to" not in out
    assert "[Download] Failed" not in out


# ==============================================================================
# Caminho de sucesso
# ==============================================================================

def test_download_success_prints_saved_path(monkeypatch, capsys):
    file_info = {"name": "test.iso", "size": 1024, "sha256": "abc"}
    peers = [{"ip": "127.0.0.1", "port": 6000, "chunks_available": [0]}]

    monkeypatch.setattr(client_module, "send_lookup", lambda *a, **k: {
        "status": "FOUND", "file_info": file_info, "peers": peers,
    })
    monkeypatch.setattr(client_module, "download_file_parallel",
                        lambda fi, pl: "downloads/test.iso")
    monkeypatch.setattr("builtins.input", _mock_input("download test.iso", "exit"))
    monkeypatch.setattr(client_module, "send_unregister", _noop_unregister)

    with pytest.raises(SystemExit):
        run_cli(_MockSock(), 6000)

    assert "[Download] Saved to downloads/test.iso" in capsys.readouterr().out


def test_download_failure_prints_failed_message(monkeypatch, capsys):
    file_info = {"name": "test.iso", "size": 1024, "sha256": "abc"}
    peers = [{"ip": "127.0.0.1", "port": 6000, "chunks_available": [0]}]

    monkeypatch.setattr(client_module, "send_lookup", lambda *a, **k: {
        "status": "FOUND", "file_info": file_info, "peers": peers,
    })
    monkeypatch.setattr(client_module, "download_file_parallel", lambda fi, pl: None)
    monkeypatch.setattr("builtins.input", _mock_input("download test.iso", "exit"))
    monkeypatch.setattr(client_module, "send_unregister", _noop_unregister)

    with pytest.raises(SystemExit):
        run_cli(_MockSock(), 6000)

    assert "[Download] Failed to download test.iso" in capsys.readouterr().out


def test_download_passes_correct_file_info_to_parallel(monkeypatch):
    """Verifica que file_info e peers_list chegam corretamente a download_file_parallel."""
    file_info = {"name": "ubuntu.iso", "size": 4096, "sha256": "deadbeef"}
    peers = [{"ip": "10.0.0.1", "port": 7001, "chunks_available": [0, 1]}]

    received = {}

    def fake_download(fi, pl):
        received["file_info"] = fi
        received["peers_list"] = pl
        return "downloads/ubuntu.iso"

    monkeypatch.setattr(client_module, "send_lookup", lambda *a, **k: {
        "status": "FOUND", "file_info": file_info, "peers": peers,
    })
    monkeypatch.setattr(client_module, "download_file_parallel", fake_download)
    monkeypatch.setattr("builtins.input", _mock_input("download ubuntu.iso", "exit"))
    monkeypatch.setattr(client_module, "send_unregister", _noop_unregister)

    with pytest.raises(SystemExit):
        run_cli(_MockSock(), 6000)

    assert received["file_info"] == file_info
    assert received["peers_list"] == peers


# ==============================================================================
# Múltiplos downloads na mesma sessão
# ==============================================================================

def test_download_success_registers_as_seeder(monkeypatch):
    """Após download bem-sucedido, o peer deve chamar send_register para virar seeder."""
    file_info = {"name": "test.iso", "size": 1024, "sha256": "abc"}
    peers = [{"ip": "127.0.0.1", "port": 6001, "chunks_available": [0]}]

    registered = []

    monkeypatch.setattr(client_module, "send_lookup", lambda *a, **k: {
        "status": "FOUND", "file_info": file_info, "peers": peers,
    })
    monkeypatch.setattr(client_module, "download_file_parallel",
                        lambda fi, pl: "downloads/test.iso")
    monkeypatch.setattr(client_module, "send_register",
                        lambda sock, port, path: registered.append(path))
    monkeypatch.setattr("builtins.input", _mock_input("download test.iso", "exit"))
    monkeypatch.setattr(client_module, "send_unregister", _noop_unregister)

    with pytest.raises(SystemExit):
        run_cli(_MockSock(), 6000)

    assert registered == ["downloads/test.iso"]


def test_multiple_downloads_in_same_session(monkeypatch, capsys):
    """CLI deve permitir mais de um download consecutivo sem reiniciar."""
    files = {
        "a.iso": {"name": "a.iso", "size": 1024, "sha256": "aaa"},
        "b.iso": {"name": "b.iso", "size": 2048, "sha256": "bbb"},
    }

    def fake_lookup(*args, filename=None, sha256=None, **kwargs):
        name = f"{filename}.iso" if not filename.endswith(".iso") else filename
        if name in files:
            return {"status": "FOUND", "file_info": files[name],
                    "peers": [{"ip": "127.0.0.1", "port": 6000, "chunks_available": [0]}]}
        return None

    monkeypatch.setattr(client_module, "send_lookup", fake_lookup)
    monkeypatch.setattr(client_module, "download_file_parallel",
                        lambda fi, pl: f"downloads/{fi['name']}")
    monkeypatch.setattr("builtins.input",
                        _mock_input("download a.iso", "download b.iso", "exit"))
    monkeypatch.setattr(client_module, "send_unregister", _noop_unregister)

    with pytest.raises(SystemExit):
        run_cli(_MockSock(), 6000)

    out = capsys.readouterr().out
    assert "[Download] Saved to downloads/a.iso" in out
    assert "[Download] Saved to downloads/b.iso" in out
