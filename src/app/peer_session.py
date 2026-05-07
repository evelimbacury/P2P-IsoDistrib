import inspect
import os
import socket
import threading
from typing import Any, Callable, Optional

from src.app.events import AppEvent, EventHandler
from src.app.models import DownloadProgress, LocalFile, NetworkSnapshot, SearchResult
from src.common.protocol import (
    DOWNLOAD_FOLDER,
    HEARTBEAT_INTERVAL,
    PEER_BASE_PORT,
    SHARED_FOLDER,
)
from src.peer.file_manager import (
    download_file_parallel,
    register_published_file,
    start_upload_server,
)
from src.peer.network import (
    calculate_sha256,
    connect_to_tracker,
    send_heartbeat,
    send_list_peers,
    send_lookup,
    send_register,
    send_unregister,
)


class PeerSession:
    """Coordena o ciclo de vida de um peer para qualquer interface."""

    def __init__(
        self,
        port: int = PEER_BASE_PORT,
        tracker_sock: Optional[socket.socket] = None,
        upload_server_sock: Optional[socket.socket] = None,
        shared_folder: str = SHARED_FOLDER,
        download_folder: str = DOWNLOAD_FOLDER,
        on_event: Optional[EventHandler] = None,
        connect_func: Callable[[], Optional[socket.socket]] = connect_to_tracker,
        register_func: Callable[..., bool] = send_register,
        heartbeat_func: Callable[..., bool] = send_heartbeat,
        lookup_func: Callable[..., Optional[dict[str, Any]]] = send_lookup,
        list_peers_func: Callable[..., Optional[dict[str, Any]]] = send_list_peers,
        unregister_func: Callable[..., bool] = send_unregister,
        download_func: Callable[..., Optional[str]] = download_file_parallel,
        upload_server_func: Callable[..., socket.socket] = start_upload_server,
        sha256_func: Callable[[str], str] = calculate_sha256,
    ):
        self.port = port
        self.tracker_sock = tracker_sock
        self.upload_server_sock = upload_server_sock
        self.shared_folder = shared_folder
        self.download_folder = download_folder
        self.offline_mode = tracker_sock is None
        self.shutdown_event = threading.Event()
        self.heartbeat_thread: Optional[threading.Thread] = None
        self._listeners: list[EventHandler] = []
        self._published_paths: set[str] = set()

        self.connect_func = connect_func
        self.register_func = register_func
        self.heartbeat_func = heartbeat_func
        self.lookup_func = lookup_func
        self.list_peers_func = list_peers_func
        self.unregister_func = unregister_func
        self.download_func = download_func
        self.upload_server_func = upload_server_func
        self.sha256_func = sha256_func

        if on_event:
            self.add_listener(on_event)

    @property
    def is_running(self) -> bool:
        return not self.shutdown_event.is_set() and self.upload_server_sock is not None

    @property
    def is_connected(self) -> bool:
        return self.tracker_sock is not None and not self.offline_mode

    def add_listener(self, listener: EventHandler) -> None:
        self._listeners.append(listener)

    def emit(self, kind: str, message: str, payload: Any = None) -> None:
        event = AppEvent(kind=kind, message=message, payload=payload)
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:
                pass

    def start(self, allow_offline: bool = False) -> bool:
        os.makedirs(self.shared_folder, exist_ok=True)
        os.makedirs(self.download_folder, exist_ok=True)

        if self.upload_server_sock is None:
            try:
                self.upload_server_sock = self._call_upload_server()
                self.emit("status", f"Upload server listening on port {self.port}")
            except OSError as exc:
                self.emit("error", f"Could not start upload server on port {self.port}: {exc}")
                return False

        if self.tracker_sock is None:
            self.tracker_sock = self.connect_func()

        if self.tracker_sock is None:
            if not allow_offline:
                self.emit("error", "Cannot connect to tracker")
                self.stop(unregister=False)
                return False
            self.offline_mode = True
            self.emit("warning", "Tracker unavailable; peer started in offline mode")
        else:
            self.offline_mode = False
            self.emit("status", "Connected to tracker")

        self.start_heartbeat()
        return True

    def start_heartbeat(self) -> None:
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            return
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
        )
        self.heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        failures = 0
        current_sock = self.tracker_sock

        while not self.shutdown_event.is_set():
            if self.offline_mode:
                self.shutdown_event.wait(HEARTBEAT_INTERVAL)
                continue

            if current_sock is None:
                current_sock = self.connect_func()
                self.tracker_sock = current_sock
                if current_sock is None:
                    failures += 1
                    if failures == 3:
                        self.emit("warning", "Tracker unreachable")
                    self.shutdown_event.wait(HEARTBEAT_INTERVAL / 2)
                    continue

            if self.heartbeat_func(current_sock, self.port):
                failures = 0
                self.tracker_sock = current_sock
            else:
                failures += 1
                try:
                    current_sock.close()
                except OSError:
                    pass
                current_sock = None
                self.tracker_sock = None

            if failures == 3:
                self.emit("warning", "Tracker unreachable")

            self.shutdown_event.wait(HEARTBEAT_INTERVAL)

    def stop(self, unregister: bool = True) -> None:
        self.shutdown_event.set()

        if unregister and self.tracker_sock is not None and not self.offline_mode:
            try:
                self.unregister_func(self.tracker_sock, self.port)
            except (BrokenPipeError, OSError):
                pass

        if self.tracker_sock is not None:
            try:
                self.tracker_sock.close()
            except OSError:
                pass
            self.tracker_sock = None

        if self.upload_server_sock is not None:
            try:
                self.upload_server_sock.close()
            except OSError:
                pass
            self.upload_server_sock = None

        self.emit("status", "Peer stopped")

    def publish(self, filepath: str) -> bool:
        if self.tracker_sock is None or self.offline_mode:
            self.emit("error", "Cannot publish: not connected to tracker")
            return False
        ok = bool(self.register_func(self.tracker_sock, self.port, filepath))
        if ok:
            self._published_paths.add(os.path.abspath(filepath))
            register_published_file(filepath)
            self.emit("published", f"Published {os.path.basename(filepath)}", filepath)
        else:
            self.emit("error", f"Failed to publish {filepath}")
        return ok

    def search(self, query: str) -> Optional[SearchResult]:
        if self.tracker_sock is None or self.offline_mode:
            self.emit("error", "Cannot search: not connected to tracker")
            return None

        query = query.strip()
        if not query:
            self.emit("error", "Search query is empty")
            return None

        if query.startswith("sha256:"):
            response = self.lookup_func(self.tracker_sock, sha256=query.split(":", 1)[1])
        else:
            response = self.lookup_func(self.tracker_sock, filename=query)

        if not response:
            self.emit("search", f"No results for '{query}'")
            return None

        result = SearchResult.from_tracker_response(response)
        self.emit(
            "search",
            f"Found {result.file_info.name} with {len(result.peers)} peer(s)",
            result,
        )
        return result

    def download(self, query: str) -> Optional[str]:
        if self.tracker_sock is None or self.offline_mode:
            self.emit("error", "Cannot download: not connected to tracker")
            return None

        result = self.search(query)
        if result is None:
            return None

        if not result.peers:
            self.emit("warning", f"No peers available for {query}")
            return None

        file_info = result.file_info.to_dict()
        peers = [peer.to_dict() for peer in result.peers]

        path = self._call_download(file_info, peers)
        if path:
            self._published_paths.add(os.path.abspath(path))
            self.emit("download_complete", f"Download saved to {path}", path)
            self.register_func(self.tracker_sock, self.port, path)
            register_published_file(path)
            return path

        self.emit("error", f"Failed to download {file_info.get('name', query)}")
        return None

    def list_local_files(self) -> list[LocalFile]:
        files = self.scan_local_files(self.shared_folder, self.sha256_func)
        known_paths = {os.path.abspath(local_file.path) for local_file in files}
        for filepath in sorted(self._published_paths):
            if filepath in known_paths or not os.path.isfile(filepath):
                continue
            if not filepath.lower().endswith(".iso"):
                continue
            files.append(
                LocalFile(
                    name=os.path.basename(filepath),
                    path=filepath,
                    size=os.path.getsize(filepath),
                    sha256=self.sha256_func(filepath),
                )
            )
        files.sort(key=lambda item: item.name.lower())
        self.emit("local_files", f"{len(files)} local file(s)", files)
        return files

    def list_network_peers(self) -> Optional[NetworkSnapshot]:
        if self.tracker_sock is None or self.offline_mode:
            self.emit("error", "Cannot list peers: not connected to tracker")
            return None

        response = self.list_peers_func(self.tracker_sock)
        if not response:
            self.emit("warning", "Tracker did not return the peer list")
            return None

        snapshot = NetworkSnapshot.from_tracker_response(response)
        self.emit("network_peers", f"{snapshot.peer_count} peer(s) connected", snapshot)
        return snapshot

    @staticmethod
    def scan_local_files(
        shared_folder: str = SHARED_FOLDER,
        sha256_func: Callable[[str], str] = calculate_sha256,
    ) -> list[LocalFile]:
        if callable(shared_folder):
            sha256_func = shared_folder
            shared_folder = SHARED_FOLDER

        os.makedirs(shared_folder, exist_ok=True)
        files: list[LocalFile] = []

        for filename in sorted(os.listdir(shared_folder)):
            filepath = os.path.join(shared_folder, filename)
            if not filename.lower().endswith(".iso") or not os.path.isfile(filepath):
                continue
            files.append(
                LocalFile(
                    name=filename,
                    path=filepath,
                    size=os.path.getsize(filepath),
                    sha256=sha256_func(filepath),
                )
            )

        return files

    def _call_download(
        self,
        file_info: dict[str, Any],
        peers: list[dict[str, Any]],
    ) -> Optional[str]:
        kwargs = {
            "on_progress": self._on_download_progress,
            "on_log": self._on_download_log,
            "download_folder": self.download_folder,
        }
        if self._callable_accepts_kwargs(self.download_func, kwargs):
            return self.download_func(file_info, peers, **kwargs)
        return self.download_func(file_info, peers)

    def _call_upload_server(self) -> socket.socket:
        kwargs = {
            "on_log": self._on_download_log,
            "shared_folder": self.shared_folder,
            "download_folder": self.download_folder,
        }
        if self._callable_accepts_kwargs(self.upload_server_func, kwargs):
            return self.upload_server_func(self.port, **kwargs)
        return self.upload_server_func(self.port)

    def _on_download_log(self, message: str) -> None:
        self.emit("download_log", message)

    def _on_download_progress(self, data: dict[str, Any]) -> None:
        progress = DownloadProgress.from_dict(data)
        self.emit("download_progress", "Download progress updated", progress)

    @staticmethod
    def _callable_accepts_kwargs(
        func: Callable[..., Any],
        kwargs: dict[str, Any],
    ) -> bool:
        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError):
            return True

        params = signature.parameters.values()
        if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params):
            return True

        return all(name in signature.parameters for name in kwargs)
