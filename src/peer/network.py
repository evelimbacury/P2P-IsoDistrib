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
    tracker_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        tracker_sock.connect((TRACKER_HOST, TRACKER_PORT))
        return tracker_sock
    except (ConnectionRefusedError, OSError):
        tracker_sock.close()
        print(f"[Error] Cannot connect to tracker at {TRACKER_HOST}:{TRACKER_PORT}")
        return None


def calculate_sha256(filepath):
    digest = hashlib.sha256()
    with open(filepath, "rb") as file_obj:
        for block in iter(lambda: file_obj.read(4096), b""):
            digest.update(block)
    return digest.hexdigest()


def _request_tracker(tracker_sock, message):
    with _tracker_io_lock:
        request_sock = connect_to_tracker()
        if request_sock is None:
            return None

        try:
            return _send_tracker_message(request_sock, message)
        finally:
            try:
                request_sock.close()
            except OSError:
                pass


def _send_tracker_message(tracker_sock, message):
    if tracker_sock is None:
        return None

    try:
        if not send_json(tracker_sock, message):
            return None
        return recv_json(tracker_sock)
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
        return None


def _resolve_port_and_filepath(peer_ip_or_port, peer_port_or_filepath=None, filepath=None):
    if filepath is None:
        return peer_ip_or_port, peer_port_or_filepath
    return peer_port_or_filepath, filepath


def _resolve_port(peer_ip_or_port, peer_port=None):
    return peer_ip_or_port if peer_port is None else peer_port


def send_register(tracker_sock, peer_ip_or_port, peer_port_or_filepath=None, filepath=None):
    port, filepath = _resolve_port_and_filepath(
        peer_ip_or_port,
        peer_port_or_filepath,
        filepath,
    )

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

    response = _request_tracker(tracker_sock, message)
    if response and response.get("status") == "OK":
        print(f"[Published] {filename} registered on tracker")
        return True

    error_message = response.get("message", "Tracker did not respond") if response else "Tracker did not respond"
    print(f"[Error] {error_message}")
    return False


def send_heartbeat(tracker_sock, peer_ip_or_port, peer_port=None):
    port = _resolve_port(peer_ip_or_port, peer_port)
    message = {
        "action": ACTION_HEARTBEAT,
        "port": port,
    }

    response = _request_tracker(tracker_sock, message)
    if not response:
        return False

    return response.get("status") not in {"ERROR"}


def send_lookup(tracker_sock, filename=None, sha256=None):
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

    response = _request_tracker(tracker_sock, message)
    if response and response.get("status") == "FOUND":
        return response

    if response and response.get("status") == "NOT_FOUND":
        print(response.get("message", f"No peers have '{query}'"))
    elif response and response.get("status") == "ERROR":
        print(f"[Error] {response.get('message', 'Lookup failed')}")
    else:
        print("[Error] Tracker did not respond")

    return None


def send_unregister(tracker_sock, peer_ip_or_port, peer_port=None):
    port = _resolve_port(peer_ip_or_port, peer_port)
    message = {
        "action": ACTION_UNREGISTER,
        "port": port,
    }

    response = _request_tracker(tracker_sock, message)
    return bool(response and response.get("status") == "OK")


def send_update_chunks(tracker_sock, port, filename, chunks_available):
    message = {
        "action": ACTION_UPDATE_CHUNKS,
        "port": port,
        "filename": filename,
        "chunks_available": list(chunks_available),
    }

    response = _request_tracker(tracker_sock, message)
    return bool(response and response.get("status") == "OK")
