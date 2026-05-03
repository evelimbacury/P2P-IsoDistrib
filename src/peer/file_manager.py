import hashlib
import os
import socket
import threading
import time

from src.common.logging_config import get_logger
from src.common.protocol import (
    CHUNK_SIZE, BUFFER_SIZE, DOWNLOAD_FOLDER, SHARED_FOLDER,
    ACTION_GET_CHUNK,
    send_json, recv_json,
    send_chunk_header, recv_chunk_header,
)

logger = get_logger("P2P-IsoDistrib.Peer")
MAX_CONCURRENT_DOWNLOADS = 4


def format_size(size_bytes):
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024


def _emit_log(on_log, message):
    if on_log:
        on_log(message)
    else:
        logger.info(message)


def _emit_progress(
    on_progress,
    filename,
    completed_chunks,
    total_chunks,
    active_peers,
    speed_bytes_per_second,
    status="downloading",
):
    if not on_progress:
        return

    percent = int(completed_chunks / total_chunks * 100) if total_chunks > 0 else 0
    on_progress({
        "filename": filename,
        "completed_chunks": completed_chunks,
        "total_chunks": total_chunks,
        "percent": percent,
        "active_peers": active_peers,
        "speed_bytes_per_second": speed_bytes_per_second,
        "status": status,
    })


def start_upload_server(peer_port, on_log=None):
    """Create and start a TCP server for serving file chunks."""
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('0.0.0.0', peer_port))
    server_socket.listen(5)

    thread = threading.Thread(
        target=serve_uploads_forever,
        args=(server_socket, on_log),
        daemon=True,
    )
    thread.start()

    _emit_log(on_log, f"[Upload] Server listening on port {peer_port}")
    return server_socket


def serve_uploads_forever(server_socket, on_log=None):
    """Accept incoming chunk requests indefinitely."""
    while True:
        try:
            client_sock, address = server_socket.accept()
            threading.Thread(
                target=handle_upload_request,
                args=(client_sock, address, on_log),
                daemon=True,
            ).start()
        except OSError:
            break
        except Exception as e:
            _emit_log(on_log, f"[Upload] Error accepting connection: {e}")


def handle_upload_request(client_sock, address, on_log=None):
    """Serve a single GET_CHUNK request from a peer."""
    try:
        request = recv_json(client_sock)
        if not request or request.get("action") != ACTION_GET_CHUNK:
            return

        filename = request.get("filename", "")
        chunk_index = request.get("chunk_index", 0)
        filepath = os.path.join(SHARED_FOLDER, filename)

        if not os.path.isfile(filepath):
            filepath = os.path.join(DOWNLOAD_FOLDER, filename)
        if not os.path.isfile(filepath):
            send_json(client_sock, {"status": "ERROR", "message": "File not found"})
            return

        total_size = os.path.getsize(filepath)
        total_chunks = (total_size + CHUNK_SIZE - 1) // CHUNK_SIZE

        with open(filepath, "rb") as f:
            f.seek(chunk_index * CHUNK_SIZE)
            data = f.read(CHUNK_SIZE)

        send_chunk_header(client_sock, chunk_index, total_chunks, len(data))
        client_sock.sendall(data)

        ip, port = address
        _emit_log(
            on_log,
            f"[Upload] Sent chunk {chunk_index + 1}/{total_chunks}"
            f" ({format_size(len(data))}) to {ip}:{port}",
        )

    except Exception as e:
        ip, port = address
        _emit_log(on_log, f"[Upload] Error handling request from {ip}:{port}: {e}")
    finally:
        client_sock.close()


def _recv_data(sock, data_len):
    """Receive exactly data_len bytes, returning None on connection failure."""
    data = bytearray()
    while len(data) < data_len:
        try:
            received = sock.recv(min(BUFFER_SIZE, data_len - len(data)))
        except socket.timeout:
            return None
        if not received:
            return None
        data.extend(received)
    return bytes(data)


def download_single_chunk(
    peers_with_chunk, filename, chunk_index, total_chunks,
    chunks_status, chunks_lock,
    peer_workload, workload_lock,
    active_count, active_lock,
    on_log=None,
):
    """Download one chunk, retrying on different peers on failure."""
    primary_key = f"{peers_with_chunk[0]['ip']}:{peers_with_chunk[0]['port']}"

    with active_lock:
        active_count[0] += 1

    try:
        for peer in peers_with_chunk[:3]:
            peer_key = f"{peer['ip']}:{peer['port']}"
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(30)
                sock.connect((peer["ip"], peer["port"]))

                send_json(sock, {
                    "action": ACTION_GET_CHUNK,
                    "filename": filename,
                    "chunk_index": chunk_index,
                })

                header = recv_chunk_header(sock)
                if header is None:
                    raise ConnectionError("No chunk header received")

                _, _, data_len = header
                data = _recv_data(sock, data_len)
                if data is None or len(data) != data_len:
                    got = len(data) if data else 0
                    raise ConnectionError(f"Incomplete data: got {got}/{data_len} bytes")

                part_path = os.path.join(DOWNLOAD_FOLDER, f"{filename}.part{chunk_index}")
                with open(part_path, "wb") as f:
                    f.write(data)

                with chunks_lock:
                    chunks_status[chunk_index] = part_path

                _emit_log(
                    on_log,
                    f"[Chunk] {chunk_index + 1}/{total_chunks}"
                    f" downloaded from {peer['ip']}:{peer['port']}",
                )
                return True

            except Exception as e:
                _emit_log(on_log, f"[Chunk] Failed chunk {chunk_index} from {peer_key}: {e}")
            finally:
                if sock:
                    try:
                        sock.close()
                    except OSError:
                        pass

        return False

    finally:
        with active_lock:
            active_count[0] -= 1
        with workload_lock:
            peer_workload[primary_key] = max(0, peer_workload.get(primary_key, 0) - 1)


def download_file_parallel(file_info, peers_list, on_progress=None, on_log=None):
    """Download a file in parallel from multiple peers. Returns local path or None."""
    filename = file_info["name"]
    file_size = file_info["size"]
    expected_sha256 = file_info["sha256"]

    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
    dest_path = os.path.join(DOWNLOAD_FOLDER, filename)
    total_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE

    chunks_status = [None] * total_chunks
    chunks_lock = threading.Lock()
    peer_workload = {}
    workload_lock = threading.Lock()
    active_count = [0]
    active_lock = threading.Lock()

    _emit_log(
        on_log,
        f"[Download] Starting download of {filename}"
        f" ({format_size(file_size)}, {total_chunks} chunks)"
        f" from {len(peers_list)} peers",
    )

    last_done = [0]
    last_time = [time.time()]
    stop_progress = threading.Event()

    def show_progress():
        while not stop_progress.wait(2):
            with chunks_lock:
                done = sum(1 for s in chunks_status if s is not None)

            now = time.time()
            elapsed = now - last_time[0]
            speed_bytes = ((done - last_done[0]) * CHUNK_SIZE) / elapsed if elapsed > 0 else 0
            last_done[0] = done
            last_time[0] = now

            pct = int(done / total_chunks * 100) if total_chunks > 0 else 0
            bar_len = 16
            filled = int(bar_len * done / total_chunks) if total_chunks > 0 else 0
            bar = "#" * filled + "-" * (bar_len - filled)

            with active_lock:
                active = active_count[0]

            _emit_progress(
                on_progress,
                filename,
                done,
                total_chunks,
                active,
                speed_bytes,
            )
            if not on_progress:
                print(
                    f"\r[Download] {filename}: [{bar}] {pct}%"
                    f" ({done}/{total_chunks})"
                    f" - {active} peers active"
                    f" - {format_size(speed_bytes)}/s",
                    end="", flush=True,
                )

    progress_thread = threading.Thread(target=show_progress, daemon=True)
    progress_thread.start()
    _emit_progress(on_progress, filename, 0, total_chunks, 0, 0)

    active_threads = []

    try:
        for chunk_index in range(total_chunks):
            available_peers = []
            for peer in peers_list:
                ca = peer.get("chunks_available")
                if ca is None or chunk_index in ca:
                    available_peers.append(peer)

            if not available_peers:
                _emit_log(on_log, f"[Download] No peers have chunk {chunk_index}")
                continue

            with workload_lock:
                available_peers.sort(
                    key=lambda p: peer_workload.get(f"{p['ip']}:{p['port']}", 0)
                )
                primary = available_peers[0]
                primary_key = f"{primary['ip']}:{primary['port']}"
                peer_workload[primary_key] = peer_workload.get(primary_key, 0) + 1

            active_threads = [t for t in active_threads if t.is_alive()]
            while len(active_threads) >= MAX_CONCURRENT_DOWNLOADS:
                active_threads[0].join(timeout=0.5)
                active_threads = [t for t in active_threads if t.is_alive()]

            t = threading.Thread(
                target=download_single_chunk,
                args=(
                    available_peers, filename, chunk_index, total_chunks,
                    chunks_status, chunks_lock,
                    peer_workload, workload_lock,
                    active_count, active_lock,
                    on_log,
                ),
                daemon=True,
            )
            t.start()
            active_threads.append(t)

        for t in active_threads:
            t.join()

    finally:
        stop_progress.set()
        if not on_progress:
            print()

    failed = [i for i, s in enumerate(chunks_status) if s is None]
    if failed:
        _emit_log(on_log, f"[Download] Failed: {len(failed)} chunks missing")
        _emit_progress(
            on_progress,
            filename,
            total_chunks - len(failed),
            total_chunks,
            0,
            0,
            status="failed",
        )
        return None

    _emit_progress(on_progress, filename, total_chunks, total_chunks, 0, 0, status="assembling")
    _emit_log(on_log, f"[Download] Assembling {filename}...")
    with open(dest_path, "wb") as out_file:
        for i in range(total_chunks):
            with open(chunks_status[i], "rb") as part:
                out_file.write(part.read())

    for i in range(total_chunks):
        try:
            os.remove(chunks_status[i])
        except OSError:
            pass

    _emit_progress(on_progress, filename, total_chunks, total_chunks, 0, 0, status="verifying")
    _emit_log(on_log, "[Download] Verifying SHA256...")
    digest = hashlib.sha256()
    with open(dest_path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            digest.update(block)
    actual_sha256 = digest.hexdigest()

    if actual_sha256 == expected_sha256:
        _emit_progress(on_progress, filename, total_chunks, total_chunks, 0, 0, status="complete")
        _emit_log(on_log, f"[Success] File verified! {filename} is intact.")
        return dest_path

    _emit_progress(on_progress, filename, total_chunks, total_chunks, 0, 0, status="failed")
    _emit_log(
        on_log,
        f"[Error] SHA256 mismatch!\n"
        f"  Expected: {expected_sha256}\n"
        f"  Got:      {actual_sha256}",
    )
    try:
        os.remove(dest_path)
    except OSError:
        pass
    return None
