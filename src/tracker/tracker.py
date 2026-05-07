"""
tracker.py - Servidor Central do Sistema P2P-IsoDistrib (Tema 7)

Responsável por: registro de peers, heartbeat, lookup de arquivos e limpeza de inativos.

Execução (a partir da raiz do projeto):
    python -m src.tracker.tracker
"""

import os
import socket
import threading
import json
import time

from src.common.logging_config import get_logger, setup_logging
from src.common.protocol import (
    HEARTBEAT_INTERVAL,
    TRACKER_BIND_HOST,
    TRACKER_PORT,
    CHUNK_SIZE,
    PEER_TIMEOUT,
    ACTION_REGISTER,
    ACTION_HEARTBEAT,
    ACTION_LOOKUP,
    ACTION_UNREGISTER,
    ACTION_UPDATE_CHUNKS,
    ACTION_LIST_PEERS,
    send_json,
    recv_json,
    clear_recv_buffer,
    MAX_JSON_SIZE,
)

# ==============================================================================
# ESTRUTURA DE DADOS GLOBAL
# ==============================================================================
# {
#     "IP:PORTA": {
#         "ip": "127.0.0.1",
#         "port": 6000,
#         "files": {
#             "ubuntu.iso": {
#                 "size": 4980736000,
#                 "sha256": "abc123...",
#                 "total_chunks": 4750,
#                 "chunks_available": [0, 1, 2, ..., 4749]  # None = todos os chunks
#             }
#         },
#         "last_heartbeat": 1714857600.123,
#         "heartbeat_count": 12
#     }
# }

peers_dict = {}
peers_lock = threading.Lock()

stop_event = threading.Event()

heartbeat_log_counter = {}
heartbeat_log_lock = threading.Lock()

logger = get_logger()
LOG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "tracker.log"))

MAX_CONNECTIONS = 1000
LISTEN_BACKLOG = 256
active_connections = 0
connection_lock = threading.Lock()

peer_last_heartbeat_time = {}
HEARTBEAT_MIN_INTERVAL = 1  # Mínimo 1 segundo entre heartbeats do mesmo peer


# ==============================================================================
# FUNÇÕES DE GERENCIAMENTO DE PEERS
# ==============================================================================

def is_valid_ip(ip):
    """Valida se é um IP válido (IPv4)."""
    try:
        parts = ip.split('.')
        if len(parts) != 4:
            return False
        for part in parts:
            num = int(part)
            if num < 0 or num > 255:
                return False
        return True
    except (ValueError, AttributeError):
        return False


def is_valid_port(port):
    """Valida se é uma porta válida."""
    try:
        port_num = int(port)
        return 1 <= port_num <= 65535
    except (ValueError, TypeError):
        return False


def cleanup_timeouts():
    """
    Thread que remove peers que não enviaram heartbeat dentro do tempo limite.
    Executa a cada 10 segundos.
    """
    while not stop_event.is_set():
        stop_event.wait(10)
        if stop_event.is_set():
            break
        _do_cleanup()


def _do_cleanup():
    now = time.time()
    peers_to_remove = []

    with peers_lock:
        items = list(peers_dict.items())
        for peer_key, peer_info in items:
            time_since_last_hb = now - peer_info["last_heartbeat"]
            if time_since_last_hb > PEER_TIMEOUT:
                peers_to_remove.append((peer_key, time_since_last_hb))

    for peer_key, elapsed in peers_to_remove:
        with peers_lock:
            if peer_key in peers_dict:
                del peers_dict[peer_key]
                logger.info(
                    f"[Tracker] [Timeout] Removed peer {peer_key} "
                    f"(no heartbeat for {elapsed:.0f}s)"
                )
        with heartbeat_log_lock:
            heartbeat_log_counter.pop(peer_key, None)
        peer_last_heartbeat_time.pop(peer_key, None)

    if peers_to_remove:
        with peers_lock:
            logger.info(f"[Tracker] Active peers: {len(peers_dict)}")


# ==============================================================================
# HANDLERS DE AÇÕES
# ==============================================================================

def handle_register(data, addr):
    """
    Processa a ação REGISTER: registra um peer e seus arquivos.
    O IP usado é **exclusivamente** o da conexão (addr[0]), ignorando qualquer campo 'peer_ip'.
    """
    try:
        peer_ip = addr[0]
        peer_port = data.get("port")
        files = data.get("files", [])
        size = data.get("size", 0)
        sha256 = data.get("sha256", "")
    except (KeyError, TypeError) as e:
        return {"status": "ERROR", "message": f"Invalid request format: {e}"}

    if not is_valid_ip(peer_ip):
        return {"status": "ERROR", "message": f"Invalid connection IP: {peer_ip}"}

    if not is_valid_port(peer_port):
        return {"status": "ERROR", "message": f"Invalid port: {peer_port}. Must be 1-65535"}

    if not files:
        return {"status": "ERROR", "message": "Missing 'files' in REGISTER"}

    if not sha256:
        return {"status": "ERROR", "message": "Missing 'sha256' in REGISTER"}

    if not isinstance(size, (int, float)) or size < 0:
        return {"status": "ERROR", "message": f"Invalid size: {size}"}

    peer_key = f"{peer_ip}:{peer_port}"
    total_chunks = (size + CHUNK_SIZE - 1) // CHUNK_SIZE if size > 0 else 0
    chunks_available = None if total_chunks > 0 else []  # None = possui todos

    with peers_lock:
        if peer_key in peers_dict:
            peer_info = peers_dict[peer_key]
        else:
            peer_info = {
                "ip": peer_ip,
                "port": peer_port,
                "files": {},
                "last_heartbeat": time.time(),
                "heartbeat_count": 0,
            }
            peers_dict[peer_key] = peer_info

        peer_info["last_heartbeat"] = time.time()

        for filename in files:
            peer_info["files"][filename] = {
                "size": size,
                "sha256": sha256,
                "total_chunks": total_chunks,
                "chunks_available": chunks_available,
            }
            if size > 0:
                size_gb = size / (1024 ** 3)
                logger.info(
                    f"[Tracker] [Register] Peer {peer_key} published '{filename}' "
                    f"({size_gb:.2f} GB, {total_chunks} chunks)"
                )
            else:
                logger.info(
                    f"[Tracker] [Register] Peer {peer_key} published '{filename}' (empty file)"
                )

    return {"status": "OK", "message": "Registered successfully"}


def handle_heartbeat(data, addr):
    """
    Processa a ação HEARTBEAT: atualiza o timestamp do peer.
    O IP usado é o da conexão real.
    """
    try:
        peer_ip = addr[0]
        peer_port = data.get("port")
    except (KeyError, TypeError) as e:
        return {"status": "ERROR", "message": f"Invalid request format: {e}"}

    if not is_valid_ip(peer_ip):
        return {"status": "ERROR", "message": f"Invalid connection IP: {peer_ip}"}

    if not is_valid_port(peer_port):
        return {"status": "ERROR", "message": f"Invalid port: {peer_port}"}

    peer_key = f"{peer_ip}:{peer_port}"

    now = time.time()
    if peer_key in peer_last_heartbeat_time:
        time_since_last = now - peer_last_heartbeat_time[peer_key]
        if time_since_last < HEARTBEAT_MIN_INTERVAL:
            return {
                "status": "RATE_LIMITED",
                "message": f"Heartbeat too frequent. Minimum interval: {HEARTBEAT_MIN_INTERVAL}s"
            }
    peer_last_heartbeat_time[peer_key] = now

    with peers_lock:
        if peer_key in peers_dict:
            peers_dict[peer_key]["last_heartbeat"] = now
            peers_dict[peer_key]["heartbeat_count"] += 1
            current_count = peers_dict[peer_key]["heartbeat_count"]
        else:
            return {"status": "WARNING", "message": "Peer not registered. Please REGISTER first."}

    should_log = False
    with heartbeat_log_lock:
        if peer_key not in heartbeat_log_counter:
            heartbeat_log_counter[peer_key] = 0
        heartbeat_log_counter[peer_key] += 1
        if heartbeat_log_counter[peer_key] >= 5:
            should_log = True
            heartbeat_log_counter[peer_key] = 0

    if should_log:
        logger.info(f"[Tracker] [Heartbeat] {peer_key} (total: {current_count})")

    return {"status": "OK"}


def handle_lookup(data, addr):
    """
    Processa a ação LOOKUP: busca por um arquivo.
    - Se 'sha256' for fornecido, busca exata por hash (ignora 'filename').
    - Caso contrário, busca por substring no nome (case insensitive) e retorna somente
      peers que compartilham o mesmo sha256 do primeiro encontrado (garantindo integridade).
    """
    sha256_query = data.get("sha256")
    filename_query = data.get("filename", "")

    if not sha256_query and not filename_query:
        return {"status": "ERROR", "message": "Either 'sha256' or 'filename' is required"}

    matching_peers = []
    file_info = None
    first_sha256 = None

    with peers_lock:
        items = list(peers_dict.items())
        for peer_key, peer_info in items:
            for fname, finfo in peer_info["files"].items():
                match = False
                if sha256_query:
                    if finfo["sha256"] == sha256_query:
                        match = True
                else:
                    if filename_query.lower() in fname.lower():
                        match = True

                if match:
                    if first_sha256 is None:
                        first_sha256 = finfo["sha256"]
                    elif finfo["sha256"] != first_sha256:
                        logger.warning(
                            f"[Tracker] [Lookup] Ignoring peer {peer_key} for '{fname}' "
                            f"due to hash mismatch ({finfo['sha256']} vs {first_sha256})"
                        )
                        continue

                    chunks_available = finfo["chunks_available"]
                    if chunks_available is None:
                        chunks_available = list(range(finfo["total_chunks"]))
                    matching_peers.append({
                        "ip": peer_info["ip"],
                        "port": peer_info["port"],
                        "chunks_available": chunks_available,
                    })
                    if file_info is None:
                        file_info = {
                            "name": fname,
                            "size": finfo["size"],
                            "sha256": finfo["sha256"],
                        }

    if matching_peers:
        logger.info(
            f"[Tracker] [Lookup] Search for '{sha256_query or filename_query}' "
            f"returned {len(matching_peers)} peers"
        )
        return {
            "status": "FOUND",
            "file_info": file_info,
            "peers": matching_peers,
        }
    else:
        logger.info(f"[Tracker] [Lookup] No peers found for '{sha256_query or filename_query}'")
        return {
            "status": "NOT_FOUND",
            "message": f"No peers have '{sha256_query or filename_query}'",
        }


def handle_unregister(data, addr):
    """
    Processa a ação UNREGISTER: remove um peer.
    O IP usado é o da conexão real.
    """
    try:
        peer_ip = addr[0]
        peer_port = data["port"]
    except KeyError as e:
        return {"status": "ERROR", "message": f"Missing required field: {e}"}

    if not is_valid_ip(peer_ip):
        return {"status": "ERROR", "message": "Unable to determine peer IP"}

    peer_key = f"{peer_ip}:{peer_port}"

    with peers_lock:
        if peer_key in peers_dict:
            del peers_dict[peer_key]
            logger.info(f"[Tracker] [Unregister] Peer {peer_key} removed")
            result = {"status": "OK", "message": "Unregistered successfully"}
        else:
            result = {"status": "WARNING", "message": "Peer was not registered"}

    with heartbeat_log_lock:
        heartbeat_log_counter.pop(peer_key, None)
    peer_last_heartbeat_time.pop(peer_key, None)

    return result


def handle_update_chunks(data, addr):
    """
    Processa a ação UPDATE_CHUNKS: atualiza a lista de chunks disponíveis de um peer.
    Mensagem esperada:
        {"action": "UPDATE_CHUNKS", "port": 6000, "filename": "ubuntu.iso", "chunks_available": [0,2,5]}
    """
    try:
        peer_ip = addr[0]
        port = data["port"]
        filename = data["filename"]
        chunks_available = data.get("chunks_available", [])
    except KeyError as e:
        return {"status": "ERROR", "message": f"Missing required field: {e}"}

    if not is_valid_port(port):
        return {"status": "ERROR", "message": f"Invalid port: {port}"}

    peer_key = f"{peer_ip}:{port}"

    with peers_lock:
        peer_info = peers_dict.get(peer_key)
        if not peer_info:
            return {"status": "ERROR", "message": "Peer not registered"}
        if filename not in peer_info["files"]:
            return {"status": "ERROR", "message": "File not registered for this peer"}

        peer_info["files"][filename]["chunks_available"] = sorted(set(chunks_available))
        logger.info(
            f"[Tracker] [UpdateChunks] Peer {peer_key} updated '{filename}' "
            f"with {len(peer_info['files'][filename]['chunks_available'])} chunks"
        )

    return {"status": "OK", "message": "Chunks updated"}


def handle_list_peers(_data, _addr):
    """Retorna um snapshot dos peers ativos e dos arquivos publicados por cada um."""
    now = time.time()

    with peers_lock:
        peers = [
            {
                "ip": peer_info["ip"],
                "port": peer_info["port"],
                "files": sorted(peer_info["files"].keys()),
                "file_count": len(peer_info["files"]),
                "last_heartbeat_age_seconds": round(max(0.0, now - peer_info["last_heartbeat"]), 2),
            }
            for peer_info in peers_dict.values()
        ]

    peers.sort(key=lambda peer: (peer["ip"], peer["port"]))
    return {
        "status": "OK",
        "peer_count": len(peers),
        "peers": peers,
    }


# ==============================================================================
# HANDLER PRINCIPAL DE CLIENTE
# ==============================================================================

def handle_client_with_limit(client_socket, addr):
    try:
        handle_client(client_socket, addr)
    finally:
        global active_connections
        with connection_lock:
            active_connections = max(0, active_connections - 1)


def handle_client(client_socket, addr):
    """
    Lida com uma conexão de cliente (peer) em uma thread separada.
    Processa múltiplas mensagens até a conexão ser fechada.
    """
    peer_addr_str = f"{addr[0]}:{addr[1]}"
    logger.debug(f"[Tracker] New connection from {peer_addr_str}")

    try:
        while not stop_event.is_set():
            data = recv_json(client_socket, timeout=HEARTBEAT_INTERVAL + 30)
            if data is None:
                break

            if not isinstance(data, dict):
                response = {"status": "ERROR", "message": "Invalid JSON format"}
                send_json(client_socket, response)
                continue

            action = data.get("action", "").upper()
            response = None

            if action == ACTION_REGISTER:
                response = handle_register(data, addr)
            elif action == ACTION_HEARTBEAT:
                response = handle_heartbeat(data, addr)
            elif action == ACTION_LOOKUP:
                response = handle_lookup(data, addr)
            elif action == ACTION_UNREGISTER:
                response = handle_unregister(data, addr)
            elif action == ACTION_UPDATE_CHUNKS:
                response = handle_update_chunks(data, addr)
            elif action == ACTION_LIST_PEERS:
                response = handle_list_peers(data, addr)
            else:
                response = {
                    "status": "ERROR",
                    "message": f"Unknown action: '{action}'. Valid: REGISTER, HEARTBEAT, LOOKUP, UNREGISTER, UPDATE_CHUNKS, LIST_PEERS"
                }
                logger.warning(f"[Tracker] Unknown action '{action}' from {peer_addr_str}")

            if response:
                if not send_json(client_socket, response):
                    logger.warning(f"[Tracker] Failed to send response to {peer_addr_str}; closing connection")
                    break

    except json.JSONDecodeError as e:
        logger.warning(f"[Tracker] Invalid JSON from {peer_addr_str}: {e}")
        try:
            send_json(client_socket, {"status": "ERROR", "message": f"Invalid JSON: {str(e)}"})
        except Exception:
            pass
    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
        logger.info(f"[Tracker] Connection lost with {peer_addr_str}")
    except Exception as e:
        logger.error(f"[Tracker] Error handling client {peer_addr_str}: {e}")
        try:
            send_json(client_socket, {"status": "ERROR", "message": f"Internal error: {str(e)}"})
        except Exception:
            pass
    finally:
        clear_recv_buffer(client_socket)
        try:
            client_socket.close()
        except Exception:
            pass
        logger.debug(f"[Tracker] Connection closed with {peer_addr_str}")


# ==============================================================================
# CONSOLE DO TRACKER
# ==============================================================================

def tracker_console():
    import sys
    if not sys.stdin.isatty():
        logger.info("[Tracker] Console disabled (stdin not available)")
        return
    logger.info("[Tracker] Console ready. Commands: 'list', 'exit'")

    while not stop_event.is_set():
        try:
            cmd = input().strip().lower()
            if cmd == "list":
                with peers_lock:
                    if not peers_dict:
                        logger.info("[Tracker] No peers connected.")
                    else:
                        logger.info("[Tracker] ========== Active Peers (%d) ==========", len(peers_dict))
                        now = time.time()
                        for peer_key, peer_info in peers_dict.items():
                            time_ago = now - peer_info["last_heartbeat"]
                            files_str = ", ".join([
                                f"{fname} ({finfo['size'] / (1024 ** 3):.2f}GB)"
                                for fname, finfo in peer_info["files"].items()
                            ])
                            hb_count = peer_info.get("heartbeat_count", 0)
                            logger.info("  %s", peer_key)
                            logger.info("    Files: %s", files_str)
                            logger.info("    Heartbeats received: %d", hb_count)
                            logger.info("    Last heartbeat: %.0fs ago", time_ago)
                        logger.info("[Tracker] ==========================================")

            elif cmd == "exit":
                logger.info("[Tracker] Shutting down...")
                stop_event.set()
                break
            elif cmd:
                logger.info(f"[Tracker] Unknown command: '{cmd}'. Use 'list' or 'exit'.")

        except EOFError:
            break
        except KeyboardInterrupt:
            print("\n[Tracker] Shutting down...")
            stop_event.set()
            break
        except OSError:
            break


# ==============================================================================
# PONTO DE ENTRADA
# ==============================================================================

def main():
    global active_connections
    setup_logging(log_file=LOG_FILE)
    bind_host = os.environ.get("TRACKER_BIND_HOST", TRACKER_BIND_HOST)
    bind_port = int(os.environ.get("TRACKER_PORT", TRACKER_PORT))
    logger.info("=" * 60)
    logger.info("  P2P-IsoDistrib - Tracker Server (Tema 7)")
    logger.info("=" * 60)

    cleanup_thread = threading.Thread(target=cleanup_timeouts, daemon=True)
    cleanup_thread.start()
    logger.info(f"[Tracker] Cleanup thread started (timeout: {PEER_TIMEOUT}s, check interval: 10s)")

    console_thread = threading.Thread(target=tracker_console, daemon=True)
    console_thread.start()

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_socket.bind((bind_host, bind_port))
        server_socket.listen(LISTEN_BACKLOG)
        server_socket.settimeout(1.0)
        logger.info(f"[Tracker] Running on {bind_host}:{bind_port}")
        logger.info("[Tracker] Waiting for peer connections...\n")

        while not stop_event.is_set():
            try:
                client_socket, addr = server_socket.accept()
                with connection_lock:
                    if active_connections >= MAX_CONNECTIONS:
                        logger.warning(f"[Tracker] Connection rejected from {addr} (max {MAX_CONNECTIONS})")
                        try:
                            client_socket.close()
                        except Exception:
                            pass
                        continue
                    active_connections += 1

                client_thread = threading.Thread(
                    target=handle_client_with_limit,
                    args=(client_socket, addr),
                    daemon=True,
                )
                client_thread.start()
            except socket.timeout:
                continue
            except Exception as e:
                if not stop_event.is_set():
                    logger.error(f"[Tracker] Error accepting connection: {e}")

    except OSError as e:
        logger.error(f"[Tracker] Failed to bind port {bind_port}: {e}")
        logger.error("[Tracker] Is another instance running?")
    finally:
        stop_event.set()
        server_socket.close()
        logger.info("[Tracker] Server stopped.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n[Tracker] Interrupted. Shutting down...")
        stop_event.set()
