import socket
import time

from src.common.protocol import (
    send_json,
    recv_json,
    TRACKER_CONNECT_HOST,
    TRACKER_PORT,
)


def _connect_to_tracker(retries=20, delay=0.05):
    """Tenta conectar ao tracker com pequenas retentativas para bursts de carga."""
    last_error = None
    for _ in range(retries):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect((TRACKER_CONNECT_HOST, TRACKER_PORT))
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
            time.sleep(delay)
    raise last_error


def simulate_peer(peer_id, with_heartbeat=True, duration=10, filename_prefix="file",
                  base_port=6000, sha256=None):
    """
    Simula um peer registrando arquivo e enviando heartbeats.
    Se 'sha256' for None, usa hash único por peer (compatível com testes antigos).
    Caso contrário, usa o hash fornecido (útil para testes de integridade).
    """
    sock = _connect_to_tracker()
    port = base_port + peer_id

    # REGISTER – não envia peer_ip (o tracker obtém da conexão)
    file_hash = sha256 if sha256 is not None else f"hash_{peer_id}"
    send_json(sock, {
        "action": "REGISTER",
        "port": port,
        "files": [f"{filename_prefix}_{peer_id}.iso"],
        "size": 10_000_000,
        "sha256": file_hash
    })

    response = recv_json(sock)
    if response is None or response.get("status") != "OK":
        sock.close()
        raise AssertionError(f"REGISTER falhou para peer {peer_id}: {response}")

    start = time.time()
    while with_heartbeat and (time.time() - start < duration):
        send_json(sock, {
            "action": "HEARTBEAT",
            "port": port
        })
        response = recv_json(sock)
        if response is None or response.get("status") not in {"OK", "RATE_LIMITED"}:
            sock.close()
            raise AssertionError(f"HEARTBEAT falhou para peer {peer_id}: {response}")
        time.sleep(1)

    sock.close()


def simulate_lookup(query="file"):
    sock = _connect_to_tracker()
    send_json(sock, {
        "action": "LOOKUP",
        "filename": query
    })
    response = recv_json(sock)
    sock.close()
    return response


def simulate_churn(peer_id, filename_prefix="churn", base_port=7000):
    sock = _connect_to_tracker()
    port = base_port + peer_id

    # REGISTER – sem peer_ip
    send_json(sock, {
        "action": "REGISTER",
        "port": port,
        "files": [f"{filename_prefix}_{peer_id}.iso"],
        "size": 1000,
        "sha256": "hash"
    })
    response = recv_json(sock)
    if response is None or response.get("status") != "OK":
        sock.close()
        raise AssertionError(f"REGISTER falhou no churn {peer_id}: {response}")

    # UNREGISTER – sem peer_ip
    send_json(sock, {
        "action": "UNREGISTER",
        "port": port
    })
    response = recv_json(sock)
    if response is None or response.get("status") != "OK":
        sock.close()
        raise AssertionError(f"UNREGISTER falhou no churn {peer_id}: {response}")

    sock.close()