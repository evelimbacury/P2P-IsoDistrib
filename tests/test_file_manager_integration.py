"""
Testes de integração para upload/download peer-to-peer.

Sobe servidores de upload reais (sockets TCP) e exercita os ciclos completos
de download_single_chunk e download_file_parallel com arquivos temporários.
"""
import hashlib
import os
import socket
import threading

import pytest

import src.peer.file_manager as fm
from src.peer.file_manager import (
    download_file_parallel,
    download_single_chunk,
    start_upload_server,
)
from src.common.protocol import CHUNK_SIZE, recv_json as _recv_json, send_chunk_header as _send_header


# ==============================================================================
# Helpers
# ==============================================================================

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _all_chunks(n: int) -> list:
    return list(range(n))


def _chunk_args(chunks_status, total=1):
    """Retorna os argumentos compartilhados para download_single_chunk."""
    return (
        chunks_status,
        threading.Lock(),   # chunks_lock
        {},                 # peer_workload
        threading.Lock(),   # workload_lock
        [0],                # active_count
        threading.Lock(),   # active_lock
    )


@pytest.fixture
def dirs(tmp_path):
    shared = tmp_path / "shared"
    downloads = tmp_path / "downloads"
    shared.mkdir()
    downloads.mkdir()
    return shared, downloads


# ==============================================================================
# download_single_chunk
# ==============================================================================

def test_single_chunk_downloads_correctly(dirs, monkeypatch):
    shared, downloads = dirs
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))
    monkeypatch.setattr(fm, "DOWNLOAD_FOLDER", str(downloads))

    content = os.urandom(CHUNK_SIZE + 500)
    (shared / "test.iso").write_bytes(content)

    port = _free_port()
    server = start_upload_server(port)
    try:
        chunks_status = [None, None]
        cs_lock = threading.Lock()
        pw = {}
        pw_lock = threading.Lock()
        ac = [0]
        ac_lock = threading.Lock()

        ok = download_single_chunk(
            [{"ip": "127.0.0.1", "port": port}],
            "test.iso", 0, 2,
            chunks_status, cs_lock, pw, pw_lock, ac, ac_lock,
        )

        assert ok is True
        assert chunks_status[0] is not None
        assert open(chunks_status[0], "rb").read() == content[:CHUNK_SIZE]
    finally:
        server.close()


def test_single_chunk_saves_correct_partial_data(dirs, monkeypatch):
    """Chunk 1 de arquivo com 1.5 chunks deve ter apenas os bytes restantes."""
    shared, downloads = dirs
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))
    monkeypatch.setattr(fm, "DOWNLOAD_FOLDER", str(downloads))

    tail = os.urandom(500)
    content = os.urandom(CHUNK_SIZE) + tail
    (shared / "test.iso").write_bytes(content)

    port = _free_port()
    server = start_upload_server(port)
    try:
        chunks_status = [None, None]
        cs_lock = threading.Lock()
        pw = {}
        pw_lock = threading.Lock()
        ac = [0]
        ac_lock = threading.Lock()

        ok = download_single_chunk(
            [{"ip": "127.0.0.1", "port": port}],
            "test.iso", 1, 2,
            chunks_status, cs_lock, pw, pw_lock, ac, ac_lock,
        )

        assert ok is True
        assert open(chunks_status[1], "rb").read() == tail
    finally:
        server.close()


def test_single_chunk_retries_on_refused_connection(dirs, monkeypatch):
    """Deve tentar o próximo peer quando o primeiro recusar conexão."""
    shared, downloads = dirs
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))
    monkeypatch.setattr(fm, "DOWNLOAD_FOLDER", str(downloads))

    content = os.urandom(CHUNK_SIZE)
    (shared / "test.iso").write_bytes(content)

    bad_port = _free_port()   # nada escutando
    good_port = _free_port()
    server = start_upload_server(good_port)
    try:
        chunks_status = [None]
        cs_lock = threading.Lock()
        pw = {}
        pw_lock = threading.Lock()
        ac = [0]
        ac_lock = threading.Lock()

        ok = download_single_chunk(
            [
                {"ip": "127.0.0.1", "port": bad_port},
                {"ip": "127.0.0.1", "port": good_port},
            ],
            "test.iso", 0, 1,
            chunks_status, cs_lock, pw, pw_lock, ac, ac_lock,
        )

        assert ok is True
        assert chunks_status[0] is not None
    finally:
        server.close()


def test_single_chunk_returns_false_when_all_peers_fail(tmp_path, monkeypatch):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    monkeypatch.setattr(fm, "DOWNLOAD_FOLDER", str(downloads))

    chunks_status = [None]
    cs_lock = threading.Lock()
    pw = {}
    pw_lock = threading.Lock()
    ac = [0]
    ac_lock = threading.Lock()

    ok = download_single_chunk(
        [{"ip": "127.0.0.1", "port": _free_port()}],
        "ghost.iso", 0, 1,
        chunks_status, cs_lock, pw, pw_lock, ac, ac_lock,
    )

    assert ok is False
    assert chunks_status[0] is None


def test_workload_decremented_after_success(dirs, monkeypatch):
    shared, downloads = dirs
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))
    monkeypatch.setattr(fm, "DOWNLOAD_FOLDER", str(downloads))

    content = os.urandom(CHUNK_SIZE)
    (shared / "test.iso").write_bytes(content)

    port = _free_port()
    peer_key = f"127.0.0.1:{port}"
    server = start_upload_server(port)
    try:
        chunks_status = [None]
        cs_lock = threading.Lock()
        pw = {peer_key: 3}
        pw_lock = threading.Lock()
        ac = [0]
        ac_lock = threading.Lock()

        download_single_chunk(
            [{"ip": "127.0.0.1", "port": port}],
            "test.iso", 0, 1,
            chunks_status, cs_lock, pw, pw_lock, ac, ac_lock,
        )

        assert pw[peer_key] == 2
    finally:
        server.close()


def test_workload_decremented_after_failure(tmp_path, monkeypatch):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    monkeypatch.setattr(fm, "DOWNLOAD_FOLDER", str(downloads))

    bad_port = _free_port()
    peer_key = f"127.0.0.1:{bad_port}"
    chunks_status = [None]
    cs_lock = threading.Lock()
    pw = {peer_key: 2}
    pw_lock = threading.Lock()
    ac = [0]
    ac_lock = threading.Lock()

    download_single_chunk(
        [{"ip": "127.0.0.1", "port": bad_port}],
        "ghost.iso", 0, 1,
        chunks_status, cs_lock, pw, pw_lock, ac, ac_lock,
    )

    assert pw[peer_key] == 1


def test_active_count_restored_after_download(dirs, monkeypatch):
    """active_count deve voltar ao valor inicial após o download completar
    (a função incrementa no início e decrementa no finally)."""
    shared, downloads = dirs
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))
    monkeypatch.setattr(fm, "DOWNLOAD_FOLDER", str(downloads))

    content = os.urandom(CHUNK_SIZE)
    (shared / "test.iso").write_bytes(content)

    port = _free_port()
    server = start_upload_server(port)
    try:
        chunks_status = [None]
        cs_lock = threading.Lock()
        pw = {}
        pw_lock = threading.Lock()
        ac = [0]
        ac_lock = threading.Lock()

        download_single_chunk(
            [{"ip": "127.0.0.1", "port": port}],
            "test.iso", 0, 1,
            chunks_status, cs_lock, pw, pw_lock, ac, ac_lock,
        )

        # Após completar: incrementou 1 (início) e decrementou 1 (finally) → volta a 0
        assert ac[0] == 0
    finally:
        server.close()


# ==============================================================================
# download_file_parallel
# ==============================================================================

def test_parallel_single_peer_small_file(dirs, monkeypatch):
    """Arquivo de 3.5 chunks baixado de um único peer deve ser idêntico ao original."""
    shared, downloads = dirs
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))
    monkeypatch.setattr(fm, "DOWNLOAD_FOLDER", str(downloads))

    content = os.urandom(3 * CHUNK_SIZE + 512)
    (shared / "test.iso").write_bytes(content)
    total = (len(content) + CHUNK_SIZE - 1) // CHUNK_SIZE

    port = _free_port()
    server = start_upload_server(port)
    try:
        file_info = {"name": "test.iso", "size": len(content), "sha256": _sha256(content)}
        peers = [{"ip": "127.0.0.1", "port": port, "chunks_available": _all_chunks(total)}]

        result = download_file_parallel(file_info, peers)

        assert result is not None
        assert open(result, "rb").read() == content
    finally:
        server.close()


def test_parallel_exact_one_chunk(dirs, monkeypatch):
    """Arquivo exatamente CHUNK_SIZE bytes deve funcionar sem .part residual."""
    shared, downloads = dirs
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))
    monkeypatch.setattr(fm, "DOWNLOAD_FOLDER", str(downloads))

    content = os.urandom(CHUNK_SIZE)
    (shared / "test.iso").write_bytes(content)

    port = _free_port()
    server = start_upload_server(port)
    try:
        file_info = {"name": "test.iso", "size": CHUNK_SIZE, "sha256": _sha256(content)}
        peers = [{"ip": "127.0.0.1", "port": port, "chunks_available": [0]}]

        result = download_file_parallel(file_info, peers)
        assert result is not None
        assert open(result, "rb").read() == content
    finally:
        server.close()


def test_parallel_two_peers_full_file(dirs, monkeypatch):
    """Arquivo baixado de dois peers deve ser idêntico ao original."""
    shared, downloads = dirs
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))
    monkeypatch.setattr(fm, "DOWNLOAD_FOLDER", str(downloads))

    content = os.urandom(4 * CHUNK_SIZE)
    (shared / "test.iso").write_bytes(content)
    total = 4

    port1, port2 = _free_port(), _free_port()
    s1 = start_upload_server(port1)
    s2 = start_upload_server(port2)
    try:
        file_info = {"name": "test.iso", "size": len(content), "sha256": _sha256(content)}
        peers = [
            {"ip": "127.0.0.1", "port": port1, "chunks_available": _all_chunks(total)},
            {"ip": "127.0.0.1", "port": port2, "chunks_available": _all_chunks(total)},
        ]

        result = download_file_parallel(file_info, peers)

        assert result is not None
        assert open(result, "rb").read() == content
    finally:
        s1.close()
        s2.close()


def test_parallel_sha256_mismatch_returns_none(dirs, monkeypatch):
    shared, downloads = dirs
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))
    monkeypatch.setattr(fm, "DOWNLOAD_FOLDER", str(downloads))

    content = os.urandom(CHUNK_SIZE)
    (shared / "test.iso").write_bytes(content)

    port = _free_port()
    server = start_upload_server(port)
    try:
        file_info = {
            "name": "test.iso",
            "size": len(content),
            "sha256": "0" * 64,  # hash propositalmente errado
        }
        peers = [{"ip": "127.0.0.1", "port": port, "chunks_available": [0]}]

        result = download_file_parallel(file_info, peers)
        assert result is None
    finally:
        server.close()


def test_parallel_missing_chunk_returns_none(dirs, monkeypatch):
    """Deve retornar None quando um chunk não tem nenhum peer disponível."""
    shared, downloads = dirs
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))
    monkeypatch.setattr(fm, "DOWNLOAD_FOLDER", str(downloads))

    content = os.urandom(2 * CHUNK_SIZE)
    (shared / "test.iso").write_bytes(content)

    port = _free_port()
    server = start_upload_server(port)
    try:
        file_info = {"name": "test.iso", "size": len(content), "sha256": _sha256(content)}
        # Peer só anuncia o chunk 0; chunk 1 fica sem cobertura
        peers = [{"ip": "127.0.0.1", "port": port, "chunks_available": [0]}]

        result = download_file_parallel(file_info, peers)
        assert result is None
    finally:
        server.close()


def test_parallel_no_part_files_after_success(dirs, monkeypatch):
    """Arquivos .part temporários devem ser deletados após download bem-sucedido."""
    shared, downloads = dirs
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))
    monkeypatch.setattr(fm, "DOWNLOAD_FOLDER", str(downloads))

    content = os.urandom(2 * CHUNK_SIZE + 100)
    (shared / "test.iso").write_bytes(content)
    total = (len(content) + CHUNK_SIZE - 1) // CHUNK_SIZE

    port = _free_port()
    server = start_upload_server(port)
    try:
        file_info = {"name": "test.iso", "size": len(content), "sha256": _sha256(content)}
        peers = [{"ip": "127.0.0.1", "port": port, "chunks_available": _all_chunks(total)}]

        result = download_file_parallel(file_info, peers)
        assert result is not None

        leftover = [f for f in os.listdir(str(downloads)) if ".part" in f]
        assert leftover == []
    finally:
        server.close()


def test_parallel_sha256_mismatch_removes_corrupted_file(dirs, monkeypatch):
    """Arquivo montado deve ser deletado quando o SHA256 não bate."""
    shared, downloads = dirs
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))
    monkeypatch.setattr(fm, "DOWNLOAD_FOLDER", str(downloads))

    content = os.urandom(CHUNK_SIZE)
    (shared / "test.iso").write_bytes(content)

    port = _free_port()
    server = start_upload_server(port)
    try:
        file_info = {
            "name": "test.iso",
            "size": len(content),
            "sha256": "0" * 64,  # hash propositalmente errado
        }
        peers = [{"ip": "127.0.0.1", "port": port, "chunks_available": [0]}]

        result = download_file_parallel(file_info, peers)
        assert result is None
        assert not os.path.exists(str(downloads / "test.iso"))
    finally:
        server.close()


def test_parallel_peer_with_partial_chunks(dirs, monkeypatch):
    """Peer com apenas alguns chunks deve servir somente esses chunks."""
    shared, downloads = dirs
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))
    monkeypatch.setattr(fm, "DOWNLOAD_FOLDER", str(downloads))

    content = os.urandom(4 * CHUNK_SIZE)
    (shared / "test.iso").write_bytes(content)

    port1, port2 = _free_port(), _free_port()
    s1 = start_upload_server(port1)
    s2 = start_upload_server(port2)
    try:
        file_info = {"name": "test.iso", "size": len(content), "sha256": _sha256(content)}
        # Peer1 tem chunks 0 e 1; peer2 tem chunks 2 e 3
        peers = [
            {"ip": "127.0.0.1", "port": port1, "chunks_available": [0, 1]},
            {"ip": "127.0.0.1", "port": port2, "chunks_available": [2, 3]},
        ]

        result = download_file_parallel(file_info, peers)

        assert result is not None
        assert open(result, "rb").read() == content
    finally:
        s1.close()
        s2.close()


# ==============================================================================
# Retry com queda de peer no meio da transferência
# ==============================================================================

def test_single_chunk_retries_on_mid_transfer_drop(dirs, monkeypatch):
    """Deve fazer retry quando o peer envia cabeçalho + metade dos dados e cai."""
    shared, downloads = dirs
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))
    monkeypatch.setattr(fm, "DOWNLOAD_FOLDER", str(downloads))

    content = os.urandom(CHUNK_SIZE)
    (shared / "test.iso").write_bytes(content)

    ready = threading.Event()
    drop_port = _free_port()

    def flaky_server():
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("", drop_port))
        srv.listen(1)
        srv.settimeout(5)
        ready.set()
        try:
            conn, _ = srv.accept()
            _recv_json(conn)                          # consome o GET_CHUNK
            _send_header(conn, 0, 1, CHUNK_SIZE)      # cabeçalho correto
            conn.sendall(content[: CHUNK_SIZE // 2])  # metade dos dados
            conn.close()                              # cai aqui
        finally:
            srv.close()

    threading.Thread(target=flaky_server, daemon=True).start()
    ready.wait()

    good_port = _free_port()
    good_server = start_upload_server(good_port)
    try:
        chunks_status = [None]
        cs_lock = threading.Lock()
        pw = {}
        pw_lock = threading.Lock()
        ac = [0]
        ac_lock = threading.Lock()

        ok = download_single_chunk(
            [
                {"ip": "127.0.0.1", "port": drop_port},   # cai no meio
                {"ip": "127.0.0.1", "port": good_port},   # funciona
            ],
            "test.iso", 0, 1,
            chunks_status, cs_lock, pw, pw_lock, ac, ac_lock,
        )

        assert ok is True
        assert open(chunks_status[0], "rb").read() == content
    finally:
        good_server.close()


# ==============================================================================
# ISO de 100 MB com dois peers e chunks alternados
# ==============================================================================

def test_parallel_100mb_two_peers(dirs, monkeypatch):
    """100 MB baixado de 2 peers com chunks alternados deve passar na verificação SHA256."""
    shared, downloads = dirs
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))
    monkeypatch.setattr(fm, "DOWNLOAD_FOLDER", str(downloads))

    size = 100 * CHUNK_SIZE   # 100 MB exatos
    content = os.urandom(size)
    expected_sha256 = _sha256(content)
    (shared / "big.iso").write_bytes(content)
    del content   # libera 100 MB de RAM antes do download
    total = 100   # chunks

    port1, port2 = _free_port(), _free_port()
    s1 = start_upload_server(port1)
    s2 = start_upload_server(port2)
    try:
        file_info = {"name": "big.iso", "size": size, "sha256": expected_sha256}
        peers = [
            # peer1 serve chunks pares (0, 2, 4 …)
            {"ip": "127.0.0.1", "port": port1, "chunks_available": list(range(0, total, 2))},
            # peer2 serve chunks ímpares (1, 3, 5 …)
            {"ip": "127.0.0.1", "port": port2, "chunks_available": list(range(1, total, 2))},
        ]

        result = download_file_parallel(file_info, peers)

        # download_file_parallel já verifica SHA256 internamente;
        # retornar caminho significa que os 100 MB estão íntegros.
        assert result is not None
    finally:
        s1.close()
        s2.close()
