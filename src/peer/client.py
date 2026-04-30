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

heartbeat_running = True


def format_size(size_bytes):
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024


def format_chunks(chunks):
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
    shared_root = os.path.abspath(SHARED_FOLDER)
    candidate = os.path.abspath(filepath)
    try:
        return os.path.commonpath([shared_root, candidate]) == shared_root
    except ValueError:
        return False


def heartbeat_loop(tracker_sock, port):
    failures = 0

    while heartbeat_running:
        if send_heartbeat(tracker_sock, port):
            failures = 0
        else:
            failures += 1

        if failures == 3:
            print("[Warning] Tracker unreachable")

        time.sleep(HEARTBEAT_INTERVAL)


def list_local_files():
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
    print("Commands:")
    print("  publish <path.iso>")
    print("  search <word|sha256:hash>")
    print("  list_local")
    print("  exit")


def shutdown(tracker_sock, peer_port):
    global heartbeat_running

    heartbeat_running = False
    if tracker_sock is not None:
        try:
            send_unregister(tracker_sock, peer_port)
        except (BrokenPipeError, OSError):
            pass
        try:
            tracker_sock.close()
        except OSError:
            pass

    print("[Peer] Shutting down...")


def run_cli(tracker_sock, peer_port):
    while True:
        try:
            raw_command = input("peer> ").strip()
        except EOFError:
            shutdown(tracker_sock, peer_port)
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


def parse_args():
    parser = argparse.ArgumentParser(description="P2P-IsoDistrib peer client")
    parser.add_argument("--port", type=int, default=PEER_BASE_PORT, help="Peer port")
    return parser.parse_args()


def main():
    global heartbeat_running

    heartbeat_running = True
    peer_ip = "127.0.0.1"
    args = parse_args()
    peer_port = args.port

    os.makedirs(SHARED_FOLDER, exist_ok=True)
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

    print(f"[Peer] Started on {peer_ip}:{peer_port}")
    tracker_sock = connect_to_tracker()

    if tracker_sock is None:
        choice = input("[Peer] Continue offline? [y/N] ").strip().lower()
        if choice not in {"y", "yes"}:
            print("[Peer] Shutting down...")
            return 1

    heartbeat_thread = threading.Thread(
        target=heartbeat_loop,
        args=(tracker_sock, peer_port),
        daemon=True,
    )
    heartbeat_thread.start()

    try:
        run_cli(tracker_sock, peer_port)
    except KeyboardInterrupt:
        print()
        shutdown(tracker_sock, peer_port)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
