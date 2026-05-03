import argparse
import os
import sys
import threading
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.common.protocol import (
    HEARTBEAT_INTERVAL, PEER_BASE_PORT,
    SHARED_FOLDER, DOWNLOAD_FOLDER,
)
from src.peer.network import (
    calculate_sha256,
    connect_to_tracker,
    send_heartbeat,
    send_lookup,
    send_register,
    send_unregister,
)
from src.peer.file_manager import (
    download_file_parallel,
    start_upload_server,
)

# Evento para controle de shutdown
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
            # Tenta reconectar ao tracker
            current_sock = connect_to_tracker()
            if current_sock is None:
                failures += 1
                if failures == 3:
                    print("[Warning] Tracker unreachable")
                shutdown_event.wait(HEARTBEAT_INTERVAL / 2)
                continue

        if send_heartbeat(current_sock, port):
            failures = 0
        else:
            failures += 1
            # Conexão perdida, fecha socket e zera para reconectar na próxima iteração
            try:
                current_sock.close()
            except OSError:
                pass
            current_sock = None

        if failures == 3:
            print("[Warning] Tracker unreachable")

        shutdown_event.wait(HEARTBEAT_INTERVAL)


def list_local_files():
    """Lista arquivos .iso disponíveis na pasta compartilhada."""
    if not os.path.isdir(SHARED_FOLDER):
        os.makedirs(SHARED_FOLDER, exist_ok=True)

    iso_files = [
        filename
        for filename in sorted(os.listdir(SHARED_FOLDER))
        if filename.lower().endswith(".iso")
        and os.path.isfile(os.path.join(SHARED_FOLDER, filename))
    ]

    if not iso_files:
        print(f"[Local] No .iso files found in {SHARED_FOLDER}/")
        return

    print("[Local Files]")
    for filename in iso_files:
        filepath = os.path.join(SHARED_FOLDER, filename)
        size = format_size(os.path.getsize(filepath))
        sha256 = calculate_sha256(filepath)
        print(f"{filename:<36} | {size:<10} | SHA256: {sha256}")


def print_search_results(result):
    """Exibe resultados de busca formatados."""
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
    print("[Peer] Shutting down...")


def run_cli(tracker_sock, peer_port, upload_server_sock=None):
    """Loop principal da CLI."""
    while True:
        try:
            raw_command = input("peer> ").strip()
        except EOFError:
            shutdown(tracker_sock, peer_port, upload_server_sock)
            return

        if not raw_command:
            continue

        parts = raw_command.split()
        command = parts[0].lower()
        args = parts[1:]

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

                send_register(tracker_sock, peer_port, filepath)

            elif command == "search":
                if not args:
                    print("[Error] Usage: search <word|sha256:hash>")
                    continue

                query = args[0]
                if query.startswith("sha256:"):
                    sha256 = query.split(":", 1)[1]
                    result = send_lookup(tracker_sock, sha256=sha256)
                else:
                    result = send_lookup(tracker_sock, filename=query)

                if result:
                    print_search_results(result)
                else:
                    print(f"[Search] No results for '{query}'")

            elif command == "download":
                if not args:
                    print("[Error] Usage: download <filename>")
                    continue

                if tracker_sock is None:
                    print("[Error] Cannot download: not connected to tracker")
                    continue

                query = args[0]
                result = send_lookup(tracker_sock, filename=query)
                if result is None:
                    continue

                file_info = result.get("file_info", {})
                peers_list = result.get("peers", [])

                if not peers_list:
                    print(f"[Download] No peers available for {query}")
                    continue

                path = download_file_parallel(file_info, peers_list)
                if path:
                    print(f"[Download] Saved to {path}")
                    if tracker_sock is not None:
                        send_register(tracker_sock, peer_port, path)
                else:
                    print(f"[Download] Failed to download {file_info.get('name', query)}")

            elif command == "list_local":
                list_local_files()

            elif command == "help":
                print_help()

            elif command == "exit":
                shutdown(tracker_sock, peer_port)
                sys.exit(0)

            else:
                print(f"[Error] Unknown command: {command}")
                print_help()

        except BrokenPipeError:
            print("[Warning] Tracker connection was lost")
        except ConnectionRefusedError:
            print("[Warning] Tracker refused the connection")
        except KeyboardInterrupt:
            raise
        except OSError as exc:
            print(f"[Error] Network error: {exc}")


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
    return parser.parse_args()


def main():
    """Função principal do peer."""
    global offline_mode

    peer_ip = "127.0.0.1"  # Para exibição local
    args = parse_args()
    peer_port = args.port

    os.makedirs(SHARED_FOLDER, exist_ok=True)
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

    upload_server_sock = start_upload_server(peer_port)
    print(f"[Peer] Started on {peer_ip}:{peer_port}")

    tracker_sock = connect_to_tracker()
    if tracker_sock is None:
        choice = input("[Peer] Continue offline? [y/N] ").strip().lower()
        if choice not in {"y", "yes"}:
            print("[Peer] Shutting down...")
            if upload_server_sock:
                upload_server_sock.close()
            return 1
        offline_mode = True

    # Inicia thread de heartbeat com o socket persistente
    heartbeat_thread = threading.Thread(
        target=heartbeat_loop,
        args=(tracker_sock, peer_port),
        daemon=True,
    )
    heartbeat_thread.start()

    try:
        run_cli(tracker_sock, peer_port, upload_server_sock)
    except KeyboardInterrupt:
        print()
        shutdown(tracker_sock, peer_port, upload_server_sock)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())