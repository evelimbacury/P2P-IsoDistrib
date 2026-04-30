import socket
import threading
import time

from src.common.protocol import recv_chunk_header, recv_json


def test_recv_json_handles_fragmented_message():
    server_sock, client_sock = socket.socketpair()

    try:
        payload = b'{"action":"LOOKUP","filename":"ubuntu"}\n'

        def sender():
            client_sock.sendall(payload[:12])
            time.sleep(0.05)
            client_sock.sendall(payload[12:])

        thread = threading.Thread(target=sender)
        thread.start()

        message = recv_json(server_sock, timeout=1)
        thread.join()

        assert message == {"action": "LOOKUP", "filename": "ubuntu"}
    finally:
        server_sock.close()
        client_sock.close()


def test_recv_json_reads_multiple_messages_from_same_stream():
    server_sock, client_sock = socket.socketpair()

    try:
        client_sock.sendall(
            b'{"action":"LOOKUP","filename":"file1"}\n'
            b'{"action":"LOOKUP","filename":"file2"}\n'
        )

        first = recv_json(server_sock, timeout=1)
        second = recv_json(server_sock, timeout=1)

        assert first == {"action": "LOOKUP", "filename": "file1"}
        assert second == {"action": "LOOKUP", "filename": "file2"}
    finally:
        server_sock.close()
        client_sock.close()


def test_recv_chunk_header_handles_partial_header():
    server_sock, client_sock = socket.socketpair()

    try:
        header = b"\x00\x00\x00\x02\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x10\x00"

        def sender():
            client_sock.sendall(header[:5])
            time.sleep(0.05)
            client_sock.sendall(header[5:11])
            time.sleep(0.05)
            client_sock.sendall(header[11:])

        thread = threading.Thread(target=sender)
        thread.start()

        parsed = recv_chunk_header(server_sock)
        thread.join()

        assert parsed == (2, 8, 4096)
    finally:
        server_sock.close()
        client_sock.close()
