import hashlib
import os
import socket
import threading

from src.common.logging_config import get_logger
from src.common.protocol import (
    TRACKER_HOST, TRACKER_PORT,
    ACTION_REGISTER, ACTION_HEARTBEAT, ACTION_LOOKUP, ACTION_UNREGISTER,
    ACTION_UPDATE_CHUNKS,
    ACTION_LIST_PEERS,
    send_json, recv_json
)

logger = get_logger("P2P-IsoDistrib.Peer")
_tracker_io_lock = threading.Lock()


def resolve_tracker_address(tracker_host=None, tracker_port=None):
    """Resolve host/porta do tracker a partir de argumentos ou ambiente."""
    host = tracker_host or os.environ.get("TRACKER_HOST", TRACKER_HOST)
    port = int(tracker_port if tracker_port is not None else os.environ.get("TRACKER_PORT", TRACKER_PORT))
    return host, port


def connect_to_tracker(tracker_host=None, tracker_port=None):
    """Cria e retorna um socket conectado ao tracker."""
    host, port = resolve_tracker_address(tracker_host, tracker_port)

    tracker_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        tracker_sock.connect((host, port))
        return tracker_sock
    except (ConnectionRefusedError, OSError):
        tracker_sock.close()
        logger.error("[Peer] Cannot connect to tracker at %s:%s", host, port)
        return None


def calculate_sha256(filepath):
    """Calcula o hash SHA256 de um arquivo."""
    digest = hashlib.sha256()
    with open(filepath, "rb") as file_obj:
        for block in iter(lambda: file_obj.read(4096), b""):
            digest.update(block)
    return digest.hexdigest()


def _send_tracker_message(tracker_sock, message, timeout=10, tracker_host=None, tracker_port=None):
    """
    Envia uma mensagem JSON ao tracker usando uma conexão curta.
    O parâmetro tracker_sock é mantido por compatibilidade com a CLI e testes.
    Retorna o dicionário de resposta ou None em caso de erro.
    """
    if tracker_sock is None:
        return None

    host, port = resolve_tracker_address(tracker_host, tracker_port)

    with _tracker_io_lock:
        request_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            request_sock.connect((host, port))
            if not send_json(request_sock, message):
                return None
            return recv_json(request_sock, timeout=timeout)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return None
        finally:
            try:
                request_sock.close()
            except OSError:
                pass


def send_register(tracker_sock, port, filepath, tracker_host=None, tracker_port=None):
    """
    Registra um arquivo .iso no tracker.
    Retorna True se registrado com sucesso, False caso contrário.
    """
    if not filepath or not os.path.exists(filepath):
        logger.error("[Peer] File not found: %s", filepath)
        return False

    if not filepath.lower().endswith(".iso"):
        logger.error("[Peer] Only .iso files are supported")
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

    response = _send_tracker_message(
        tracker_sock,
        message,
        tracker_host=tracker_host,
        tracker_port=tracker_port,
    )
    if response and response.get("status") == "OK":
        logger.info("[Peer] [Published] %s registered on tracker", filename)
        return True

    error_message = response.get("message", "Tracker did not respond") if response else "Tracker did not respond"
    logger.error("[Peer] %s", error_message)
    return False


def send_heartbeat(tracker_sock, port, tracker_host=None, tracker_port=None):
    """Envia sinal de heartbeat para o tracker."""
    message = {
        "action": ACTION_HEARTBEAT,
        "port": port,
    }

    response = _send_tracker_message(
        tracker_sock,
        message,
        timeout=5,
        tracker_host=tracker_host,
        tracker_port=tracker_port,
    )
    if not response:
        return False

    status = response.get("status", "")
    return status not in {"ERROR"}


def send_lookup(tracker_sock, filename=None, sha256=None, tracker_host=None, tracker_port=None):
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

    response = _send_tracker_message(
        tracker_sock,
        message,
        tracker_host=tracker_host,
        tracker_port=tracker_port,
    )
    if response and response.get("status") == "FOUND":
        return response

    if response and response.get("status") == "NOT_FOUND":
        logger.info("[Peer] %s", response.get("message", f"No peers have '{query}'"))
    elif response and response.get("status") == "ERROR":
        logger.error("[Peer] %s", response.get("message", "Lookup failed"))
    else:
        logger.error("[Peer] Tracker did not respond")

    return None


def send_unregister(tracker_sock, port, tracker_host=None, tracker_port=None):
    """Remove o peer do tracker."""
    message = {
        "action": ACTION_UNREGISTER,
        "port": port,
    }

    response = _send_tracker_message(
        tracker_sock,
        message,
        timeout=5,
        tracker_host=tracker_host,
        tracker_port=tracker_port,
    )
    return bool(response and response.get("status") == "OK")


def send_list_peers(tracker_sock, tracker_host=None, tracker_port=None):
    """Busca a lista atual de peers ativos no tracker."""
    message = {
        "action": ACTION_LIST_PEERS,
    }

    response = _send_tracker_message(
        tracker_sock,
        message,
        timeout=5,
        tracker_host=tracker_host,
        tracker_port=tracker_port,
    )
    if response and response.get("status") == "OK":
        return response

    return None


def send_update_chunks(tracker_sock, port, filename, chunks_available, tracker_host=None, tracker_port=None):
    """Informa ao tracker quais chunks o peer possui disponíveis."""
    message = {
        "action": ACTION_UPDATE_CHUNKS,
        "port": port,
        "filename": filename,
        "chunks_available": list(chunks_available),
    }

    response = _send_tracker_message(
        tracker_sock,
        message,
        tracker_host=tracker_host,
        tracker_port=tracker_port,
    )
    return bool(response and response.get("status") == "OK")
