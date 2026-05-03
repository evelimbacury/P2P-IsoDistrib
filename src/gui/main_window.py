import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from src.app.events import AppEvent
from src.app.models import DownloadProgress, SearchResult
from src.app.peer_session import PeerSession
from src.common.protocol import PEER_BASE_PORT, SHARED_FOLDER
from src.peer.client import format_chunks, format_size


class P2PGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("P2P-IsoDistrib")
        self.geometry("980x640")
        self.minsize(860, 560)

        self.session: PeerSession | None = None
        self.events: queue.Queue[AppEvent] = queue.Queue()
        self.latest_search: SearchResult | None = None

        self._build_ui()
        self.after(100, self._process_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(self)
        notebook.grid(row=0, column=0, sticky="nsew")

        self.connection_tab = ttk.Frame(notebook, padding=12)
        self.local_tab = ttk.Frame(notebook, padding=12)
        self.search_tab = ttk.Frame(notebook, padding=12)
        self.downloads_tab = ttk.Frame(notebook, padding=12)
        self.logs_tab = ttk.Frame(notebook, padding=12)

        notebook.add(self.connection_tab, text="Conexão")
        notebook.add(self.local_tab, text="Arquivos Locais")
        notebook.add(self.search_tab, text="Buscar")
        notebook.add(self.downloads_tab, text="Downloads")
        notebook.add(self.logs_tab, text="Logs")

        self._build_connection_tab()
        self._build_local_tab()
        self._build_search_tab()
        self._build_downloads_tab()
        self._build_logs_tab()

    def _build_connection_tab(self):
        tab = self.connection_tab
        tab.columnconfigure(1, weight=1)

        ttk.Label(tab, text="Porta do peer").grid(row=0, column=0, sticky="w")
        self.port_var = tk.IntVar(value=PEER_BASE_PORT)
        ttk.Spinbox(tab, from_=1, to=65535, textvariable=self.port_var, width=12).grid(
            row=0, column=1, sticky="w", padx=(10, 0)
        )

        self.allow_offline_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            tab,
            text="Permitir iniciar sem tracker",
            variable=self.allow_offline_var,
        ).grid(row=1, column=1, sticky="w", padx=(10, 0), pady=(8, 0))

        ttk.Label(tab, text="Tracker").grid(row=2, column=0, sticky="w", pady=(18, 0))
        self.tracker_status_var = tk.StringVar(value="Parado")
        ttk.Label(tab, textvariable=self.tracker_status_var).grid(
            row=2, column=1, sticky="w", padx=(10, 0), pady=(18, 0)
        )

        ttk.Label(tab, text="Upload server").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.upload_status_var = tk.StringVar(value="Parado")
        ttk.Label(tab, textvariable=self.upload_status_var).grid(
            row=3, column=1, sticky="w", padx=(10, 0), pady=(8, 0)
        )

        actions = ttk.Frame(tab)
        actions.grid(row=4, column=0, columnspan=2, sticky="w", pady=(22, 0))
        self.start_button = ttk.Button(actions, text="Iniciar", command=self._start_peer)
        self.start_button.grid(row=0, column=0)
        self.stop_button = ttk.Button(actions, text="Parar", command=self._stop_peer, state="disabled")
        self.stop_button.grid(row=0, column=1, padx=(8, 0))

    def _build_local_tab(self):
        tab = self.local_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        actions = ttk.Frame(tab)
        actions.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(actions, text="Atualizar", command=self._refresh_local_files).grid(row=0, column=0)
        ttk.Button(actions, text="Publicar selecionado", command=self._publish_selected_local).grid(
            row=0, column=1, padx=(8, 0)
        )
        ttk.Button(actions, text="Escolher ISO...", command=self._publish_file_dialog).grid(
            row=0, column=2, padx=(8, 0)
        )

        columns = ("name", "size", "sha256")
        self.local_tree = ttk.Treeview(tab, columns=columns, show="headings", height=14)
        self.local_tree.heading("name", text="Arquivo")
        self.local_tree.heading("size", text="Tamanho")
        self.local_tree.heading("sha256", text="SHA256")
        self.local_tree.column("name", width=250)
        self.local_tree.column("size", width=100, anchor="e")
        self.local_tree.column("sha256", width=520)
        self.local_tree.grid(row=1, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.local_tree.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.local_tree.configure(yscrollcommand=scrollbar.set)

    def _build_search_tab(self):
        tab = self.search_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

        search_bar = ttk.Frame(tab)
        search_bar.grid(row=0, column=0, sticky="ew")
        search_bar.columnconfigure(0, weight=1)

        self.search_var = tk.StringVar()
        entry = ttk.Entry(search_bar, textvariable=self.search_var)
        entry.grid(row=0, column=0, sticky="ew")
        entry.bind("<Return>", lambda _event: self._search())
        ttk.Button(search_bar, text="Buscar", command=self._search).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(search_bar, text="Baixar resultado", command=self._download_latest_search).grid(
            row=0, column=2, padx=(8, 0)
        )

        self.search_summary_var = tk.StringVar(value="Nenhuma busca realizada")
        ttk.Label(tab, textvariable=self.search_summary_var).grid(row=1, column=0, sticky="w", pady=(8, 8))

        columns = ("file", "size", "sha256", "peer", "chunks")
        self.search_tree = ttk.Treeview(tab, columns=columns, show="headings")
        headings = {
            "file": "Arquivo",
            "size": "Tamanho",
            "sha256": "SHA256",
            "peer": "Peer",
            "chunks": "Chunks",
        }
        for column, label in headings.items():
            self.search_tree.heading(column, text=label)
        self.search_tree.column("file", width=180)
        self.search_tree.column("size", width=90, anchor="e")
        self.search_tree.column("sha256", width=280)
        self.search_tree.column("peer", width=130)
        self.search_tree.column("chunks", width=220)
        self.search_tree.grid(row=2, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.search_tree.yview)
        scrollbar.grid(row=2, column=1, sticky="ns")
        self.search_tree.configure(yscrollcommand=scrollbar.set)

    def _build_downloads_tab(self):
        tab = self.downloads_tab
        tab.columnconfigure(1, weight=1)

        ttk.Label(tab, text="Arquivo").grid(row=0, column=0, sticky="w")
        self.download_file_var = tk.StringVar(value="-")
        ttk.Label(tab, textvariable=self.download_file_var).grid(row=0, column=1, sticky="w", padx=(10, 0))

        ttk.Label(tab, text="Status").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.download_status_var = tk.StringVar(value="Aguardando")
        ttk.Label(tab, textvariable=self.download_status_var).grid(
            row=1, column=1, sticky="w", padx=(10, 0), pady=(8, 0)
        )

        ttk.Label(tab, text="Chunks").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.download_chunks_var = tk.StringVar(value="0/0")
        ttk.Label(tab, textvariable=self.download_chunks_var).grid(
            row=2, column=1, sticky="w", padx=(10, 0), pady=(8, 0)
        )

        ttk.Label(tab, text="Velocidade").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.download_speed_var = tk.StringVar(value="0 B/s")
        ttk.Label(tab, textvariable=self.download_speed_var).grid(
            row=3, column=1, sticky="w", padx=(10, 0), pady=(8, 0)
        )

        self.progress_var = tk.IntVar(value=0)
        self.progress_bar = ttk.Progressbar(tab, variable=self.progress_var, maximum=100)
        self.progress_bar.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(18, 0))

    def _build_logs_tab(self):
        tab = self.logs_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        self.log_text = tk.Text(tab, height=18, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        ttk.Button(tab, text="Limpar", command=self._clear_logs).grid(row=1, column=0, sticky="w", pady=(8, 0))

    def _start_peer(self):
        if self.session and self.session.is_running:
            return

        self.start_button.configure(state="disabled")
        port = int(self.port_var.get())
        allow_offline = bool(self.allow_offline_var.get())
        self.session = PeerSession(port=port, on_event=self._queue_event)

        def worker():
            started = self.session.start(allow_offline=allow_offline)
            self._queue_event(AppEvent("gui_started", "Peer start finished", started))
            if started:
                self._refresh_local_files()

        threading.Thread(target=worker, daemon=True).start()

    def _stop_peer(self):
        if not self.session:
            return

        def worker():
            self.session.stop()
            self._queue_event(AppEvent("gui_stopped", "Peer stopped"))

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_local_files(self):
        def worker():
            if self.session:
                files = self.session.list_local_files()
            else:
                files = PeerSession.scan_local_files()
            self._queue_event(AppEvent("local_files", "Local files refreshed", files))

        threading.Thread(target=worker, daemon=True).start()

    def _publish_selected_local(self):
        selected = self.local_tree.selection()
        if not selected:
            messagebox.showinfo("Publicar", "Selecione um arquivo local.")
            return
        path = self.local_tree.item(selected[0], "tags")[0]
        self._publish_path(path)

    def _publish_file_dialog(self):
        path = filedialog.askopenfilename(
            title="Escolher ISO",
            filetypes=[("Arquivos ISO", "*.iso"), ("Todos os arquivos", "*.*")],
        )
        if path:
            self._publish_path(path)

    def _publish_path(self, path):
        if not self._require_session():
            return

        if not self._is_inside_shared_folder(path):
            message = (
                f"{path} está fora de {SHARED_FOLDER}/. "
                "Ele será servido por esta instância enquanto ela estiver aberta."
            )
            messagebox.showwarning("Arquivo fora da pasta compartilhada", message)
            self._append_log(f"[Warning] {message}")

        def worker():
            self.session.publish(path)
            self._refresh_local_files()

        threading.Thread(target=worker, daemon=True).start()

    def _is_inside_shared_folder(self, path):
        shared_root = os.path.abspath(SHARED_FOLDER)
        candidate = os.path.abspath(path)
        try:
            return os.path.commonpath([shared_root, candidate]) == shared_root
        except ValueError:
            return False

    def _search(self):
        if not self._require_session():
            return
        query_text = self.search_var.get().strip()
        if not query_text:
            messagebox.showinfo("Buscar", "Digite um nome de arquivo ou sha256:<hash>.")
            return

        def worker():
            result = self.session.search(query_text)
            self._queue_event(AppEvent("search_result", "Search finished", result))

        threading.Thread(target=worker, daemon=True).start()

    def _download_latest_search(self):
        if not self._require_session():
            return
        if not self.latest_search:
            messagebox.showinfo("Downloads", "Faça uma busca antes de baixar.")
            return

        filename = self.latest_search.file_info.name
        self.download_file_var.set(filename)
        self.download_status_var.set("Iniciando")
        self.progress_var.set(0)

        def worker():
            self.session.download(filename)

        threading.Thread(target=worker, daemon=True).start()

    def _require_session(self):
        if not self.session or not self.session.is_running:
            messagebox.showinfo("Peer", "Inicie o peer primeiro.")
            return False
        return True

    def _queue_event(self, event):
        self.events.put(event)

    def _process_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        self.after(100, self._process_events)

    def _handle_event(self, event: AppEvent):
        if event.kind in {"status", "warning", "error", "published", "download_log", "search"}:
            self._append_log(event.message)

        if event.kind == "status":
            self._refresh_connection_status()
        elif event.kind == "error":
            self._refresh_connection_status()
        elif event.kind == "gui_started":
            self._refresh_connection_status()
            self.start_button.configure(state="disabled" if event.payload else "normal")
            self.stop_button.configure(state="normal" if event.payload else "disabled")
        elif event.kind == "gui_stopped":
            self._refresh_connection_status()
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
        elif event.kind == "local_files":
            self._render_local_files(event.payload)
        elif event.kind == "search_result":
            self._render_search_result(event.payload)
        elif event.kind == "download_progress":
            self._render_download_progress(event.payload)
        elif event.kind == "download_complete":
            self._append_log(event.message)
            self.download_status_var.set("Concluído")
            self.progress_var.set(100)
            self._refresh_local_files()

    def _refresh_connection_status(self):
        if not self.session or not self.session.is_running:
            self.tracker_status_var.set("Parado")
            self.upload_status_var.set("Parado")
            return

        self.upload_status_var.set(f"Ativo na porta {self.session.port}")
        if self.session.offline_mode:
            self.tracker_status_var.set("Offline")
        elif self.session.is_connected:
            self.tracker_status_var.set("Conectado")
        else:
            self.tracker_status_var.set("Reconectando")

    def _render_local_files(self, files):
        for item in self.local_tree.get_children():
            self.local_tree.delete(item)
        for local_file in files:
            self.local_tree.insert(
                "",
                "end",
                values=(local_file.name, format_size(local_file.size), local_file.sha256),
                tags=(local_file.path,),
            )

    def _render_search_result(self, result):
        self.latest_search = result
        for item in self.search_tree.get_children():
            self.search_tree.delete(item)

        if not result:
            self.search_summary_var.set("Nenhum resultado encontrado")
            return

        self.search_summary_var.set(
            f"{result.file_info.name} - {format_size(result.file_info.size)} - {len(result.peers)} peer(s)"
        )
        for peer in result.peers:
            self.search_tree.insert(
                "",
                "end",
                values=(
                    result.file_info.name,
                    format_size(result.file_info.size),
                    result.file_info.sha256,
                    f"{peer.ip}:{peer.port}",
                    format_chunks(peer.chunks_available or []),
                ),
            )

    def _render_download_progress(self, progress: DownloadProgress):
        self.download_file_var.set(progress.filename or "-")
        self.download_status_var.set(progress.status)
        self.download_chunks_var.set(f"{progress.completed_chunks}/{progress.total_chunks}")
        self.download_speed_var.set(f"{format_size(progress.speed_bytes_per_second)}/s")
        self.progress_var.set(progress.percent)

    def _append_log(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_logs(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _on_close(self):
        if self.session and self.session.is_running:
            self.session.stop()
        self.destroy()


def main():
    app = P2PGui()
    app.mainloop()
