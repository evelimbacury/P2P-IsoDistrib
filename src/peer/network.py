import hashlib
import os
import socket
import threading

from src.common.protocol import (
    TRACKER_HOST, TRACKER_PORT,
    ACTION_REGISTER, ACTION_HEARTBEAT, ACTION_LOOKUP, ACTION_UNREGISTER,
    ACTION_UPDATE_CHUNKS,
    send_json, recv_json
)

_tracker_io_lock = threading.Lock()


def connect_to_tracker():
    """Cria e retorna um socket conectado ao tracker."""
    tracker_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        tracker_sock.connect((TRACKER_HOST, TRACKER_PORT))
        return tracker_sock
    except (ConnectionRefusedError, OSError):
        tracker_sock.close()
        print(f"[Error] Cannot connect to tracker at {TRACKER_HOST}:{TRACKER_PORT}")
        return None


def calculate_sha256(filepath):
    """Calcula o hash SHA256 de um arquivo."""
    digest = hashlib.sha256()
    with open(filepath, "rb") as file_obj:
        for block in iter(lambda: file_obj.read(4096), b""):
            digest.update(block)
    return digest.hexdigest()


def _send_tracker_message(tracker_sock, message, timeout=10):
    """
    Envia uma mensagem JSON e aguarda a resposta usando o socket fornecido.
    Aplica lock para serializar o uso do socket.
    Retorna o dicionário de resposta ou None em caso de erro.
    """
    if tracker_sock is None:
        return None

    with _tracker_io_lock:
        try:
            if not send_json(tracker_sock, message):
                return None
            return recv_json(tracker_sock, timeout=timeout)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return None


def send_register(tracker_sock, port, filepath):
    """
    Registra um arquivo .iso no tracker.
    Retorna True se registrado com sucesso, False caso contrário.
    """
    if not filepath or not os.path.exists(filepath):
        print(f"[Error] File not found: {filepath}")
        return False

    if not filepath.lower().endswith(".iso"):
        print("[Error] Only .iso files are supported")
        return False

    filename = os.path.basename(filepath)
    size = os.path.getsize(filepath)
    sha256 = calculate_sha256(filepath)

    message = {
        "action": ACTION_REGISTER,
        "port": port,
        "files": [filename],
        "size": size,
        "sha256": sha256,
    }

    response = _send_tracker_message(tracker_sock, message)
    if response and response.get("status") == "OK":
        print(f"[Published] {filename} registered on tracker")
        return True

    error_message = response.get("message", "Tracker did not respond") if response else "Tracker did not respond"
    print(f"[Error] {error_message}")
    return False


def send_heartbeat(tracker_sock, port):
    """Envia sinal de heartbeat para o tracker."""
    message = {
        "action": ACTION_HEARTBEAT,
        "port": port,
    }

    response = _send_tracker_message(tracker_sock, message, timeout=5)
    if not response:
        return False

    status = response.get("status", "")
    return status not in {"ERROR"}


def send_lookup(tracker_sock, filename=None, sha256=None):
    """
    Busca por arquivo no tracker (por nome ou hash SHA256).
    Retorna o dicionário completo da resposta se encontrado, None caso contrário.
    """
    if sha256:
        message = {
            "action": ACTION_LOOKUP,
            "sha256": sha256,
        }
        query = sha256
    else:
        message = {
            "action": ACTION_LOOKUP,
            "filename": filename or "",
        }
        query = filename or ""

    response = _send_tracker_message(tracker_sock, message)
    if response and response.get("status") == "FOUND":
        return response

    if response and response.get("status") == "NOT_FOUND":
        print(response.get("message", f"No peers have '{query}'"))
    elif response and response.get("status") == "ERROR":
        print(f"[Error] {response.get('message', 'Lookup failed')}")
    else:
        print("[Error] Tracker did not respond")

    return None


def send_unregister(tracker_sock, port):
    """Remove o peer do tracker."""
    message = {
        "action": ACTION_UNREGISTER,
        "port": port,
    }

    response = _send_tracker_message(tracker_sock, message, timeout=5)
    return bool(response and response.get("status") == "OK")


def send_update_chunks(tracker_sock, port, filename, chunks_available):
    """Informa ao tracker quais chunks o peer possui disponíveis."""
    message = {
        "action": ACTION_UPDATE_CHUNKS,
        "port": port,
        "filename": filename,
        "chunks_available": list(chunks_available),
    }

    response = _send_tracker_message(tracker_sock, message)
    return bool(response and response.get("status") == "OK")