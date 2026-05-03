"""
Testes unitários para src/peer/file_manager.py.

Testa cada função individualmente usando socketpairs e arquivos temporários.
Sem dependência de tracker ou rede externa.
"""
import os
import socket
import threading
import time

import pytest

import src.peer.file_manager as fm
from src.peer.file_manager import (
    _recv_data,
    download_single_chunk,
    format_size,
    handle_upload_request,
    register_published_file,
)
from src.common.protocol import CHUNK_SIZE, recv_json, send_json, recv_chunk_header


# ==============================================================================
# format_size
# ==============================================================================

def test_format_size_zero_bytes():
    assert format_size(0) == "0 B"


def test_format_size_bytes():
    assert format_size(512) == "512 B"
    assert format_size(1023) == "1023 B"


def test_format_size_kilobytes():
    assert format_size(1024) == "1.00 KB"
    assert format_size(1536) == "1.50 KB"


def test_format_size_megabytes():
    assert format_size(1024 * 1024) == "1.00 MB"
    assert format_size(int(1.5 * 1024 * 1024)) == "1.50 MB"


def test_format_size_gigabytes():
    assert format_size(1024 ** 3) == "1.00 GB"
    assert format_size(int(4.98 * 1024 ** 3)) == "4.98 GB"


def test_format_size_terabytes():
    assert format_size(1024 ** 4) == "1.00 TB"


# ==============================================================================
# _recv_data
# ==============================================================================

def test_recv_data_exact_bytes():
    s1, s2 = socket.socketpair()
    try:
        s2.sendall(b"hello world!!")
        result = _recv_data(s1, 13)
        assert result == b"hello world!!"
    finally:
        s1.close()
        s2.close()


def test_recv_data_reassembles_fragments():
    """Deve remontar corretamente dados chegando em fragmentos."""
    s1, s2 = socket.socketpair()
    try:
        data = os.urandom(4096)

        def send_in_parts():
            for i in range(0, len(data), 512):
                s2.sendall(data[i : i + 512])
                time.sleep(0.001)

        t = threading.Thread(target=send_in_parts, daemon=True)
        t.start()
        result = _recv_data(s1, len(data))
        t.join()

        assert result == data
    finally:
        s1.close()
        s2.close()


def test_recv_data_returns_none_on_early_close():
    """Deve retornar None se a conexão fechar antes de enviar tudo."""
    s1, s2 = socket.socketpair()
    try:
        s2.sendall(b"partial")
        s2.close()
        result = _recv_data(s1, 100)
        assert result is None
    finally:
        s1.close()


def test_recv_data_single_large_block():
    s1, s2 = socket.socketpair()
    try:
        data = os.urandom(CHUNK_SIZE)
        sender = threading.Thread(target=lambda: s2.sendall(data), daemon=True)
        sender.start()
        result = _recv_data(s1, CHUNK_SIZE)
        sender.join(timeout=2)
        assert result == data
    finally:
        s1.close()
        s2.close()


# ==============================================================================
# handle_upload_request
# ==============================================================================

def _start_handler(handler_sock, address=("127.0.0.1", 9999)):
    """Inicia handle_upload_request em thread separada."""
    t = threading.Thread(
        target=handle_upload_request, args=(handler_sock, address), daemon=True
    )
    t.start()
    return t


def test_upload_serves_first_chunk_correctly(tmp_path, monkeypatch):
    """Chunk 0 deve corresponder aos primeiros CHUNK_SIZE bytes do arquivo."""
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))

    content = os.urandom(CHUNK_SIZE + 300)
    (shared / "test.iso").write_bytes(content)

    requester, handler_end = socket.socketpair()
    try:
        t = _start_handler(handler_end)
        send_json(requester, {"action": "GET_CHUNK", "filename": "test.iso", "chunk_index": 0})

        header = recv_chunk_header(requester)
        assert header is not None
        chunk_idx, total_chunks, data_len = header
        assert chunk_idx == 0
        assert total_chunks == 2
        assert data_len == CHUNK_SIZE

        received = _recv_data(requester, data_len)
        assert received == content[:CHUNK_SIZE]
        t.join(timeout=2)
    finally:
        requester.close()


def test_upload_serves_last_partial_chunk(tmp_path, monkeypatch):
    """Último chunk deve ter apenas os bytes restantes (< CHUNK_SIZE)."""
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))

    tail = b"Z" * 300
    content = b"A" * CHUNK_SIZE + tail
    (shared / "test.iso").write_bytes(content)

    requester, handler_end = socket.socketpair()
    try:
        t = _start_handler(handler_end)
        send_json(requester, {"action": "GET_CHUNK", "filename": "test.iso", "chunk_index": 1})

        header = recv_chunk_header(requester)
        assert header is not None
        _, total_chunks, data_len = header
        assert total_chunks == 2
        assert data_len == 300

        received = _recv_data(requester, data_len)
        assert received == tail
        t.join(timeout=2)
    finally:
        requester.close()


def test_upload_reports_correct_total_chunks(tmp_path, monkeypatch):
    """total_chunks no cabeçalho deve bater com o cálculo esperado."""
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))

    # Arquivo exatamente 5 chunks
    content = os.urandom(5 * CHUNK_SIZE)
    (shared / "test.iso").write_bytes(content)

    requester, handler_end = socket.socketpair()
    try:
        t = _start_handler(handler_end)
        send_json(requester, {"action": "GET_CHUNK", "filename": "test.iso", "chunk_index": 2})

        header = recv_chunk_header(requester)
        assert header is not None
        _, total_chunks, _ = header
        assert total_chunks == 5
        t.join(timeout=2)
    finally:
        requester.close()


def test_upload_file_not_found_returns_error_json(tmp_path, monkeypatch):
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))

    requester, handler_end = socket.socketpair()
    try:
        t = _start_handler(handler_end)
        send_json(requester, {"action": "GET_CHUNK", "filename": "missing.iso", "chunk_index": 0})

        response = recv_json(requester, timeout=2)
        assert response is not None
        assert response["status"] == "ERROR"
        assert "not found" in response["message"].lower()
        t.join(timeout=2)
    finally:
        requester.close()


def test_upload_serves_registered_external_file(tmp_path, monkeypatch):
    shared = tmp_path / "shared"
    downloads = tmp_path / "downloads"
    external = tmp_path / "external"
    shared.mkdir()
    downloads.mkdir()
    external.mkdir()
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))
    monkeypatch.setattr(fm, "DOWNLOAD_FOLDER", str(downloads))

    content = b"external iso content"
    filepath = external / "external.iso"
    filepath.write_bytes(content)
    register_published_file(str(filepath))

    requester, handler_end = socket.socketpair()
    try:
        t = _start_handler(handler_end)
        send_json(requester, {"action": "GET_CHUNK", "filename": "external.iso", "chunk_index": 0})

        header = recv_chunk_header(requester)
        assert header is not None
        chunk_idx, total_chunks, data_len = header
        assert chunk_idx == 0
        assert total_chunks == 1
        assert data_len == len(content)

        received = _recv_data(requester, data_len)
        assert received == content
        t.join(timeout=2)
    finally:
        requester.close()


def test_download_single_chunk_reports_peer_json_error(tmp_path, monkeypatch):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    monkeypatch.setattr(fm, "DOWNLOAD_FOLDER", str(downloads))

    server_sock, client_sock = socket.socketpair()
    try:
        class FakeSocket:
            def __init__(self, wrapped):
                self.wrapped = wrapped

            def settimeout(self, timeout):
                self.wrapped.settimeout(timeout)

            def gettimeout(self):
                return self.wrapped.gettimeout()

            def connect(self, _address):
                return None

            def sendall(self, data):
                self.wrapped.sendall(data)

            def recv(self, size, *flags):
                return self.wrapped.recv(size, *flags)

            def fileno(self):
                return self.wrapped.fileno()

            def close(self):
                self.wrapped.close()

        def fake_socket(*_args, **_kwargs):
            return FakeSocket(client_sock)

        def send_error():
            recv_json(server_sock)
            send_json(server_sock, {"status": "ERROR", "message": "File not found"})

        thread = threading.Thread(target=send_error, daemon=True)
        thread.start()
        monkeypatch.setattr(fm.socket, "socket", fake_socket)

        chunks_status = [None]
        ok = download_single_chunk(
            [{"ip": "127.0.0.1", "port": 6000}],
            "missing.iso", 0, 1,
            chunks_status, threading.Lock(), {}, threading.Lock(), [0], threading.Lock(),
        )

        assert ok is False
        assert chunks_status == [None]
        thread.join(timeout=2)
    finally:
        server_sock.close()


def test_upload_invalid_action_closes_without_sending(tmp_path, monkeypatch):
    """Action desconhecida deve fechar o socket sem enviar resposta."""
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))

    requester, handler_end = socket.socketpair()
    try:
        t = _start_handler(handler_end)
        send_json(requester, {"action": "INVALID_ACTION"})

        response = recv_json(requester, timeout=1)
        assert response is None  # socket fechado sem dados
        t.join(timeout=2)
    finally:
        requester.close()


def test_upload_falls_back_to_download_folder(tmp_path, monkeypatch):
    """Arquivo ausente em shared_files/ deve ser servido de downloads/."""
    shared = tmp_path / "shared"
    downloads = tmp_path / "downloads"
    shared.mkdir()
    downloads.mkdir()
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))
    monkeypatch.setattr(fm, "DOWNLOAD_FOLDER", str(downloads))

    content = os.urandom(512)
    (downloads / "test.iso").write_bytes(content)

    requester, handler_end = socket.socketpair()
    try:
        t = _start_handler(handler_end)
        send_json(requester, {"action": "GET_CHUNK", "filename": "test.iso", "chunk_index": 0})

        header = recv_chunk_header(requester)
        assert header is not None
        _, _, data_len = header
        received = _recv_data(requester, data_len)
        assert received == content
        t.join(timeout=2)
    finally:
        requester.close()


def test_upload_single_chunk_file(tmp_path, monkeypatch):
    """Arquivo com menos de CHUNK_SIZE deve ser servido em 1 chunk."""
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(fm, "SHARED_FOLDER", str(shared))

    content = b"small file" * 10
    (shared / "test.iso").write_bytes(content)

    requester, handler_end = socket.socketpair()
    try:
        t = _start_handler(handler_end)
        send_json(requester, {"action": "GET_CHUNK", "filename": "test.iso", "chunk_index": 0})

        header = recv_chunk_header(requester)
        assert header is not None
        chunk_idx, total_chunks, data_len = header
        assert chunk_idx == 0
        assert total_chunks == 1
        assert data_len == len(content)

        received = _recv_data(requester, data_len)
        assert received == content
        t.join(timeout=2)
    finally:
        requester.close()
