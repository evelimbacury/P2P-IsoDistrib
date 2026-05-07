import json
import os
import socket
import threading
from dataclasses import asdict
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from src.app.events import AppEvent
from src.app.models import DownloadProgress, LocalFile, NetworkSnapshot, SearchResult
from src.app.peer_session import PeerSession
from src.common.logging_config import get_logger, setup_logging
from src.common.protocol import DOWNLOAD_FOLDER, PEER_BASE_PORT, SHARED_FOLDER, TRACKER_HOST, TRACKER_PORT
from src.peer.file_manager import download_file_parallel, start_upload_server
from src.peer.network import (
    calculate_sha256,
    connect_to_tracker,
    resolve_tracker_address,
    send_heartbeat,
    send_list_peers,
    send_lookup,
    send_register,
    send_unregister,
)

logger = get_logger("P2P-IsoDistrib.DesktopAPI")
API_LOG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "desktop_api.log"))


def _find_free_port():
    with socket.socket() as sock:
        sock.bind(("", 0))
        return sock.getsockname()[1]


def _coerce_port(value, fallback):
    try:
        port = int(value)
    except (TypeError, ValueError):
        return fallback
    if 1 <= port <= 65535:
        return port
    return fallback


def _coerce_size_mb(value, fallback=50):
    try:
        size_mb = int(value)
    except (TypeError, ValueError):
        return fallback
    return min(max(size_mb, 1), 4096)


class DesktopAppState:
    def __init__(self):
        self._lock = threading.RLock()
        self.session: PeerSession | None = None
        self.downloads: dict[str, dict] = {}
        self.local_files: list[LocalFile] = []
        self.network_snapshot: NetworkSnapshot | None = None
        self.search_result: SearchResult | None = None
        self.messages: list[dict] = []
        self.status = "Pronto para iniciar."
        self.status_level = "idle"
        self.started = False
        self.runtime_root = os.path.abspath(os.path.join(os.getcwd(), "desktop_runtime"))
        self.config = {
            "tracker_host": TRACKER_HOST,
            "tracker_port": TRACKER_PORT,
            "peer_port": PEER_BASE_PORT,
            "shared_folder": os.path.join(self.runtime_root, SHARED_FOLDER),
            "download_folder": os.path.join(self.runtime_root, DOWNLOAD_FOLDER),
        }

    def _push_message(self, level, text):
        with self._lock:
            self.messages.append({"level": level, "text": text})
            self.messages = self.messages[-25:]

    def _event_handler(self, event: AppEvent):
        with self._lock:
            if event.kind == "status":
                self.status = event.message
                self.status_level = "info"
            elif event.kind == "warning":
                self.status = event.message
                self.status_level = "warning"
            elif event.kind == "error":
                self.status = event.message
                self.status_level = "error"
            elif event.kind == "local_files":
                self.local_files = list(event.payload or [])
            elif event.kind == "network_peers":
                self.network_snapshot = event.payload
            elif event.kind == "search":
                self.status = event.message
                self.status_level = "info"
            elif event.kind == "search_result":
                self.search_result = event.payload
            elif event.kind == "published":
                self.status = f"Arquivo compartilhado: {os.path.basename(str(event.payload))}"
                self.status_level = "success"
            elif event.kind == "download_complete":
                self.status = "Download concluido."
                self.status_level = "success"
            elif event.kind == "download_progress":
                progress = event.payload
                if isinstance(progress, DownloadProgress):
                    self.downloads[progress.filename] = {
                        "filename": progress.filename,
                        "completed_chunks": progress.completed_chunks,
                        "total_chunks": progress.total_chunks,
                        "percent": progress.percent,
                        "active_peers": progress.active_peers,
                        "speed_bytes_per_second": progress.speed_bytes_per_second,
                        "status": progress.status,
                    }
            elif event.kind == "download_log":
                self._push_message("log", event.message)

            self._push_message(event.kind, event.message)

    def start_session(self, payload):
        tracker_host, tracker_port = resolve_tracker_address(
            payload.get("tracker_host"),
            _coerce_port(payload.get("tracker_port"), TRACKER_PORT),
        )
        peer_port = _coerce_port(payload.get("peer_port"), _find_free_port())

        runtime_root = payload.get("runtime_root") or os.path.join(self.runtime_root, f"peer_{peer_port}")
        shared_folder = payload.get("shared_folder") or os.path.join(runtime_root, SHARED_FOLDER)
        download_folder = payload.get("download_folder") or os.path.join(runtime_root, DOWNLOAD_FOLDER)

        os.makedirs(shared_folder, exist_ok=True)
        os.makedirs(download_folder, exist_ok=True)

        with self._lock:
            if self.session and self.session.is_running:
                self.session.stop()

            self.downloads = {}
            self.local_files = []
            self.network_snapshot = None
            self.search_result = None
            self.started = False
            self.config = {
                "tracker_host": tracker_host,
                "tracker_port": tracker_port,
                "peer_port": peer_port,
                "shared_folder": shared_folder,
                "download_folder": download_folder,
            }

            self.session = PeerSession(
                port=peer_port,
                shared_folder=shared_folder,
                download_folder=download_folder,
                on_event=self._event_handler,
                connect_func=partial(connect_to_tracker, tracker_host=tracker_host, tracker_port=tracker_port),
                register_func=partial(send_register, tracker_host=tracker_host, tracker_port=tracker_port),
                heartbeat_func=partial(send_heartbeat, tracker_host=tracker_host, tracker_port=tracker_port),
                lookup_func=partial(send_lookup, tracker_host=tracker_host, tracker_port=tracker_port),
                list_peers_func=partial(send_list_peers, tracker_host=tracker_host, tracker_port=tracker_port),
                unregister_func=partial(send_unregister, tracker_host=tracker_host, tracker_port=tracker_port),
                download_func=download_file_parallel,
                upload_server_func=start_upload_server,
                sha256_func=calculate_sha256,
            )

        started = self.session.start(allow_offline=True)
        with self._lock:
            self.started = started
            if started:
                self.status = f"Peer ativo na porta {peer_port}"
                self.status_level = "success"
            else:
                self.status = "Nao foi possivel iniciar o peer."
                self.status_level = "error"

        self.refresh()
        return self.snapshot()

    def stop_session(self):
        with self._lock:
            if self.session and self.session.is_running:
                self.session.stop()
            self.started = False
            self.status = "Peer parado."
            self.status_level = "idle"
        return self.snapshot()

    def refresh(self):
        with self._lock:
            session = self.session
        if not session:
            return self.snapshot()

        session.list_local_files()
        if session.is_connected:
            session.list_network_peers()
        return self.snapshot()

    def search(self, query):
        with self._lock:
            session = self.session
        if not session:
            raise RuntimeError("Peer ainda nao iniciado.")

        result = session.search(query)
        with self._lock:
            self.search_result = result
        return self.snapshot()

    def publish(self, filepath):
        with self._lock:
            session = self.session
        if not session:
            raise RuntimeError("Peer ainda nao iniciado.")
        if not filepath:
            raise RuntimeError("Nenhum arquivo informado.")
        ok = session.publish(filepath)
        self.refresh()
        if not ok:
            raise RuntimeError("Falha ao compartilhar o arquivo.")
        return self.snapshot()

    def create_test_iso(self, payload):
        with self._lock:
            session = self.session
            shared_folder = session.shared_folder if session else self.config["shared_folder"]

        filename = os.path.basename((payload.get("filename") or "test.iso").strip())
        if not filename:
            filename = "test.iso"
        if not filename.lower().endswith(".iso"):
            filename = f"{filename}.iso"

        size_mb = _coerce_size_mb(payload.get("size_mb"), 50)
        size_bytes = size_mb * 1024 * 1024
        os.makedirs(shared_folder, exist_ok=True)
        filepath = os.path.abspath(os.path.join(shared_folder, filename))
        shared_root = os.path.abspath(shared_folder)

        if os.path.commonpath([shared_root, filepath]) != shared_root:
            raise RuntimeError("Nome de arquivo invalido.")

        if not os.path.exists(filepath) or os.path.getsize(filepath) != size_bytes:
            with open(filepath, "wb") as file_obj:
                file_obj.truncate(size_bytes)

        self._push_message("success", f"ISO de teste criada: {filepath}")
        self.refresh()
        return self.snapshot()

    def download(self, filename):
        with self._lock:
            session = self.session
        if not session:
            raise RuntimeError("Peer ainda nao iniciado.")

        def worker():
            session.download(filename)
            self.refresh()

        threading.Thread(target=worker, daemon=True).start()
        return self.snapshot()

    def _serialize_search_result(self):
        with self._lock:
            result = self.search_result
        if not result:
            return None
        return {
            "file_info": asdict(result.file_info),
            "peers": [asdict(peer) for peer in result.peers],
        }

    def _serialize_local_files(self):
        with self._lock:
            files = list(self.local_files)
        return [asdict(item) for item in files]

    def _serialize_network_snapshot(self):
        with self._lock:
            snapshot = self.network_snapshot
        if not snapshot:
            return {"peer_count": 0, "published_file_count": 0, "peers": []}
        return {
            "peer_count": snapshot.peer_count,
            "published_file_count": snapshot.published_file_count,
            "peers": [asdict(peer) for peer in snapshot.peers],
        }

    def snapshot(self):
        with self._lock:
            status = self.status
            status_level = self.status_level
            started = self.started
            config = dict(self.config)
            downloads = list(self.downloads.values())
            messages = list(self.messages)
            session = self.session

        return {
            "started": started,
            "status": status,
            "status_level": status_level,
            "config": config,
            "session": {
                "is_running": bool(session and session.is_running),
                "is_connected": bool(session and session.is_connected),
                "offline_mode": bool(session and session.offline_mode),
            },
            "local_files": self._serialize_local_files(),
            "network": self._serialize_network_snapshot(),
            "search_result": self._serialize_search_result(),
            "downloads": downloads,
            "messages": messages,
        }


APP_STATE = DesktopAppState()


class DesktopApiHandler(BaseHTTPRequestHandler):
    server_version = "P2PIsoDistribDesktopAPI/1.0"

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._json_response({"ok": True})
            return
        if parsed.path == "/api/state":
            self._json_response(APP_STATE.snapshot())
            return
        self._json_response({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)
        payload = self._read_json_body()
        try:
            if parsed.path == "/api/session/start":
                self._json_response(APP_STATE.start_session(payload))
                return
            if parsed.path == "/api/session/stop":
                self._json_response(APP_STATE.stop_session())
                return
            if parsed.path == "/api/session/refresh":
                self._json_response(APP_STATE.refresh())
                return
            if parsed.path == "/api/search":
                self._json_response(APP_STATE.search((payload.get("query") or "").strip()))
                return
            if parsed.path == "/api/publish":
                self._json_response(APP_STATE.publish(payload.get("path")))
                return
            if parsed.path == "/api/create-test-iso":
                self._json_response(APP_STATE.create_test_iso(payload))
                return
            if parsed.path == "/api/download":
                self._json_response(APP_STATE.download((payload.get("filename") or "").strip()))
                return
        except RuntimeError as exc:
            self._json_response({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._json_response({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format, *args):
        logger.info("%s - %s", self.address_string(), format % args)

    def _read_json_body(self):
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0:
            return {}
        raw = self.rfile.read(content_length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json_response(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    setup_logging(log_file=API_LOG_FILE)
    host = os.environ.get("DESKTOP_API_HOST", "127.0.0.1")
    port = int(os.environ.get("DESKTOP_API_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), DesktopApiHandler)
    logger.info("[DesktopAPI] Running on %s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        APP_STATE.stop_session()
        server.server_close()


if __name__ == "__main__":
    main()
