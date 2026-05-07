import argparse
from functools import partial
import os
import shlex
import sys
import threading
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.common.logging_config import get_logger, setup_logging
from src.common.protocol import (
    HEARTBEAT_INTERVAL, PEER_BASE_PORT,
    SHARED_FOLDER, DOWNLOAD_FOLDER,
)
from src.app.models import SearchResult
from src.app.peer_session import PeerSession
from src.peer.network import (
    calculate_sha256,
    connect_to_tracker,
    resolve_tracker_address,
    send_heartbeat,
    send_lookup,
    send_register,
    send_unregister,
)
from src.peer.file_manager import (
    download_file_parallel,
    start_upload_server,
)

logger = get_logger("P2P-IsoDistrib.Peer")
PEER_LOG_FILE = os.path.abspath(os.path.join(PROJECT_ROOT, "peer.log"))

shutdown_event = threading.Event()
offline_mode = False


def format_size(size_bytes):
    """Formata tamanho em bytes para representação legível."""
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024


def format_chunks(chunks):
    """Formata lista de chunks para representação compacta."""
    if not chunks:
        return "none"

    sorted_chunks = sorted(set(chunks))
    ranges = []
    start = previous = sorted_chunks[0]

    for chunk in sorted_chunks[1:]:
        if chunk == previous + 1:
            previous = chunk
            continue
        ranges.append(f"{start}" if start == previous else f"{start}-{previous}")
        start = previous = chunk

    ranges.append(f"{start}" if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def is_inside_shared_folder(filepath):
    """Verifica se o arquivo está dentro da pasta compartilhada."""
    shared_root = os.path.abspath(SHARED_FOLDER)
    candidate = os.path.abspath(filepath)
    try:
        return os.path.commonpath([shared_root, candidate]) == shared_root
    except ValueError:
        return False


def heartbeat_loop(tracker_sock, port):
    """
    Thread que envia heartbeats periodicamente.
    Se a conexão falhar, tenta reconectar automaticamente.
    """
    global offline_mode
    failures = 0
    current_sock = tracker_sock

    while not shutdown_event.is_set():
        if offline_mode:
            shutdown_event.wait(HEARTBEAT_INTERVAL)
            continue

        if current_sock is None:
            current_sock = connect_to_tracker()
            if current_sock is None:
                failures += 1
                if failures == 3:
                    logger.warning("[Peer] Tracker unreachable")
                shutdown_event.wait(HEARTBEAT_INTERVAL / 2)
                continue

        if send_heartbeat(current_sock, port):
            failures = 0
        else:
            failures += 1
            try:
                current_sock.close()
            except OSError:
                pass
            current_sock = None

        if failures == 3:
            logger.warning("[Peer] Tracker unreachable")

        shutdown_event.wait(HEARTBEAT_INTERVAL)


def list_local_files():
    """Lista arquivos .iso disponíveis na pasta compartilhada."""
    local_files = PeerSession.scan_local_files(calculate_sha256)

    if not local_files:
        print(f"[Local] No .iso files found in {SHARED_FOLDER}/")
        return

    print("[Local Files]")
    for local_file in local_files:
        size = format_size(local_file.size)
        print(f"{local_file.name:<36} | {size:<10} | SHA256: {local_file.sha256}")


def print_search_results(result):
    """Exibe resultados de busca formatados."""
    if isinstance(result, SearchResult):
        file_info = result.file_info.to_dict()
        peers = [peer.to_dict() for peer in result.peers]
    else:
        file_info = result["file_info"]
        peers = result["peers"]

    print("[Search Results]")
    print(f"File: {file_info['name']}")
    print(f"Size: {format_size(file_info['size'])}")
    print(f"SHA256: {file_info['sha256']}")
    print("Peers:")
    for index, peer in enumerate(peers, start=1):
        chunks = format_chunks(peer.get("chunks_available", []))
        print(f"  [{index}] {peer['ip']}:{peer['port']} (chunks: {chunks})")


def print_help():
    """Exibe comandos disponíveis."""
    print("Commands:")
    print("  publish <path.iso>")
    print("  search <word|sha256:hash>")
    print("  download <filename>")
    print("  list_local")
    print("  exit")


def shutdown(tracker_sock, peer_port, upload_server_sock=None):
    """Finaliza graciosamente o peer."""
    shutdown_event.set()
    if tracker_sock is not None and not offline_mode:
        try:
            send_unregister(tracker_sock, peer_port)
        except (BrokenPipeError, OSError):
            pass
        try:
            tracker_sock.close()
        except OSError:
            pass

        if upload_server_sock:
            try:
                upload_server_sock.close()
            except OSError:
                pass
    logger.info("[Peer] Shutting down")
    print("[Peer] Shutting down...")


def build_cli_session(tracker_sock, peer_port, upload_server_sock=None, tracker_host=None, tracker_port=None):
    """Cria uma PeerSession usando as operações atuais do módulo da CLI."""
    def with_tracker_target(func):
        if tracker_host is None and tracker_port is None:
            return func
        return partial(func, tracker_host=tracker_host, tracker_port=tracker_port)

    return PeerSession(
        port=peer_port,
        tracker_sock=tracker_sock,
        upload_server_sock=upload_server_sock,
        connect_func=with_tracker_target(connect_to_tracker),
        register_func=with_tracker_target(send_register),
        heartbeat_func=with_tracker_target(send_heartbeat),
        lookup_func=with_tracker_target(send_lookup),
        unregister_func=with_tracker_target(send_unregister),
        download_func=download_file_parallel,
        upload_server_func=start_upload_server,
        sha256_func=calculate_sha256,
    )


def run_cli(tracker_sock, peer_port, upload_server_sock=None, session=None):
    """Loop principal da CLI."""
    session = session or build_cli_session(tracker_sock, peer_port, upload_server_sock)

    while True:
        try:
            raw_command = input("peer> ").strip()
        except EOFError:
            session.stop()
            logger.info("[Peer] Shutting down")
            print("[Peer] Shutting down...")
            return

        if not raw_command:
            continue

        parts = shlex.split(raw_command, posix=False)
        command = parts[0].lower()
        args = [arg.strip('"') for arg in parts[1:]]

        try:
            if command == "publish":
                if not args:
                    print("[Error] Usage: publish <path.iso>")
                    continue

                filepath = args[0]
                if not os.path.exists(filepath):
                    print(f"[Error] File not found: {filepath}")
                    continue
                if not filepath.lower().endswith(".iso"):
                    print("[Error] Only .iso files are supported")
                    continue
                if not is_inside_shared_folder(filepath):
                    print("[Warning] File is not in shared_files/ folder. Other peers may not find it.")

                session.publish(filepath)

            elif command == "search":
                if not args:
                    print("[Error] Usage: search <word|sha256:hash>")
                    continue

                query = args[0]
                result = session.search(query)

                if result:
                    print_search_results(result)
                else:
                    print(f"[Search] No results for '{query}'")

            elif command == "download":
                if not args:
                    print("[Error] Usage: download <filename>")
                    continue

                if session.tracker_sock is None or session.offline_mode:
                    print("[Error] Cannot download: not connected to tracker")
                    continue

                query = args[0]
                result = session.search(query)
                if result is None:
                    continue

                file_info = result.file_info.to_dict()
                peers_list = [peer.to_dict() for peer in result.peers]

                if not peers_list:
                    print(f"[Download] No peers available for {query}")
                    continue

                path = session._call_download(file_info, peers_list)
                if path:
                    print(f"[Download] Saved to {path}")
                    session.register_func(session.tracker_sock, peer_port, path)
                else:
                    print(f"[Download] Failed to download {file_info.get('name', query)}")

            elif command == "list_local":
                list_local_files()

            elif command == "help":
                print_help()

            elif command == "exit":
                session.stop()
                logger.info("[Peer] Shutting down")
                print("[Peer] Shutting down...")
                sys.exit(0)

            else:
                print(f"[Error] Unknown command: {command}")
                print_help()

        except BrokenPipeError:
            logger.warning("[Peer] Tracker connection was lost")
        except ConnectionRefusedError:
            logger.warning("[Peer] Tracker refused the connection")
        except KeyboardInterrupt:
            raise
        except OSError as exc:
            logger.error("[Peer] Network error: %s", exc)


def validate_port(value):
    """Valida se a porta está no intervalo 1-65535."""
    try:
        port = int(value)
        if not (1 <= port <= 65535):
            raise argparse.ArgumentTypeError(f"Port must be between 1 and 65535, got {port}")
        return port
    except ValueError:
        raise argparse.ArgumentTypeError(f"Port must be an integer, got '{value}'")


def parse_args():
    """Configura e processa argumentos da linha de comando."""
    parser = argparse.ArgumentParser(description="P2P-IsoDistrib peer client")
    parser.add_argument("--port", type=validate_port, default=PEER_BASE_PORT,
                        help="Peer listening port (1-65535)")
    parser.add_argument("--tracker-host", default=None,
                        help="Tracker host/IP (default: TRACKER_HOST env or protocol default)")
    parser.add_argument("--tracker-port", type=validate_port, default=None,
                        help="Tracker port (default: TRACKER_PORT env or protocol default)")
    return parser.parse_args()


def main():
    """Função principal do peer."""
    global offline_mode

    setup_logging(log_file=PEER_LOG_FILE)

    peer_ip = "127.0.0.1"
    args = parse_args()
    peer_port = args.port
    tracker_host, tracker_port = resolve_tracker_address(args.tracker_host, args.tracker_port)

    os.makedirs(SHARED_FOLDER, exist_ok=True)
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

    session = build_cli_session(
        tracker_sock=None,
        peer_port=peer_port,
        tracker_host=tracker_host,
        tracker_port=tracker_port,
    )
    started = session.start(allow_offline=False)
    logger.info("[Peer] Started on %s:%s", peer_ip, peer_port)
    print(f"[Peer] Started on {peer_ip}:{peer_port}")
    print(f"[Peer] Tracker target: {tracker_host}:{tracker_port}")

    if not started:
        choice = input("[Peer] Continue offline? [y/N] ").strip().lower()
        if choice not in {"y", "yes"}:
            logger.info("[Peer] Shutting down")
            print("[Peer] Shutting down...")
            session.stop(unregister=False)
            return 1
        session = build_cli_session(
            tracker_sock=None,
            peer_port=peer_port,
            tracker_host=tracker_host,
            tracker_port=tracker_port,
        )
        session.start(allow_offline=True)
        offline_mode = True

    try:
        run_cli(session.tracker_sock, peer_port, session.upload_server_sock, session=session)
    except KeyboardInterrupt:
        print()
        session.stop()
        logger.info("[Peer] Shutting down")
        print("[Peer] Shutting down...")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
