import os
import queue
import socket
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from src.app.events import AppEvent
from src.app.models import DownloadProgress, SearchResult
from src.app.peer_session import PeerSession
from src.common.protocol import SHARED_FOLDER
from src.peer.client import format_chunks, format_size


class BitTorrentStyleGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("P2P-IsoDistrib")
        self.geometry("900x600")
        self.minsize(700, 450)

        self.session: PeerSession | None = None
        self.events: queue.Queue[AppEvent] = queue.Queue()
        self._downloads: dict[str, dict] = {}

        self._build_ui()
        self.after(100, self._process_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(500, self._auto_start)

    def _find_free_port(self) -> int:
        with socket.socket() as s:
            s.bind(('', 0))
            return s.getsockname()[1]

    def _auto_start(self):
        self._start_peer()

    def _start_peer(self):
        if self.session and self.session.is_running:
            return

        port = self._find_free_port()
        self.session = PeerSession(port=port, on_event=self._queue_event)

        def worker():
            started = self.session.start(allow_offline=True)
            if started:
                self.status_var.set(f"Conectado | Porta {port}")
                self._refresh_local()
            else:
                self.status_var.set("Offline – Tracker indisponível")

        threading.Thread(target=worker, daemon=True).start()

    def _search(self):
        if not self.session or not self.session.is_running:
            messagebox.showinfo("Buscar", "Peer não está pronto. Aguarde...")
            return

        query = self.search_var.get().strip()
        if not query:
            messagebox.showinfo("Buscar", "Digite um nome de arquivo.")
            return

        def worker():
            result = self.session.search(query)
            self._queue_event(AppEvent("search_result", "Busca concluída", result))

        threading.Thread(target=worker, daemon=True).start()

    def _publish_file(self):
        path = filedialog.askopenfilename(
            title="Escolher ISO para publicar",
            filetypes=[("Arquivos ISO", "*.iso"), ("Todos", "*.*")]
        )
        if not path or not self.session:
            return

        popup = tk.Toplevel(self)
        popup.title("Publicando...")
        popup.geometry("300x80")
        popup.resizable(False, False)
        ttk.Label(popup, text="Calculando SHA256 e registrando...").pack(pady=10)
        progress = ttk.Progressbar(popup, mode='indeterminate')
        progress.pack(fill='x', padx=20, pady=5)
        progress.start()

        def worker():
            try:
                self.session.publish(path)
            finally:
                popup.destroy()
                self._refresh_local()

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_local(self):
        if self.session:
            self.session.list_local_files()

    def _build_ui(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="P2P-IsoDistrib", font=("", 14, "bold")).pack(side="left")
        self.status_var = tk.StringVar(value="Iniciando...")
        ttk.Label(top, textvariable=self.status_var, foreground="gray").pack(side="right")

        search_frame = ttk.Frame(self, padding=(10, 0))
        search_frame.pack(fill="x")
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        search_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        search_entry.bind("<Return>", lambda e: self._search())
        ttk.Button(search_frame, text="Buscar", command=self._search).pack(side="left")
        ttk.Button(search_frame, text="Atualizar Locais", command=self._refresh_local).pack(side="left", padx=(5, 0))

        main_area = ttk.Frame(self, padding=10)
        main_area.pack(fill="both", expand=True)

        result_frame = ttk.LabelFrame(main_area, text="Resultados da Busca", padding=5)
        result_frame.pack(fill="both", expand=True, pady=(0, 10))

        columns = ("name", "size", "sha256", "peers", "action")
        self.result_tree = ttk.Treeview(result_frame, columns=columns, show="headings", height=8)
        self.result_tree.heading("name", text="Arquivo")
        self.result_tree.heading("size", text="Tamanho")
        self.result_tree.heading("sha256", text="SHA256")
        self.result_tree.heading("peers", text="Peers")
        self.result_tree.heading("action", text="")
        self.result_tree.column("name", width=220)
        self.result_tree.column("size", width=90, anchor="e")
        self.result_tree.column("sha256", width=180)
        self.result_tree.column("peers", width=60, anchor="center")
        self.result_tree.column("action", width=80, anchor="center")
        self.result_tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(result_frame, orient="vertical", command=self.result_tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.result_tree.configure(yscrollcommand=scrollbar.set)
        self.result_tree.bind("<Double-1>", self._on_result_double_click)

        dl_frame = ttk.LabelFrame(main_area, text="Downloads", padding=5)
        dl_frame.pack(fill="x")
        self.dl_canvas = tk.Canvas(dl_frame, height=80, highlightthickness=0)
        self.dl_canvas.pack(fill="x")
        self.dl_text = self.dl_canvas.create_text(10, 40, anchor="w", text="Nenhum download ativo", fill="gray")
        self.progress_var = tk.IntVar(value=0)
        self.progress_bar = ttk.Progressbar(dl_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill="x", pady=(5, 0))

        bottom = ttk.Frame(self, padding=10)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Publicar arquivo...", command=self._publish_file).pack(side="left")
        ttk.Button(bottom, text="Configurações", command=self._show_config).pack(side="right")

    def _show_config(self):
        win = tk.Toplevel(self)
        win.title("Configurações")
        win.geometry("300x150")
        win.resizable(False, False)
        ttk.Label(win, text="Porta do peer:").pack(pady=(10, 0))
        port_var = tk.IntVar(value=6000)
        ttk.Entry(win, textvariable=port_var, width=10).pack()
        def salvar():
            messagebox.showinfo("Configurações", "Reinicie o peer para aplicar.")
            win.destroy()
        ttk.Button(win, text="Salvar", command=salvar).pack(pady=10)

    def _on_result_double_click(self, event):
        selected = self.result_tree.selection()
        if not selected:
            return
        item = self.result_tree.item(selected[0])
        filename = item["values"][0]
        self._start_download(filename)

    def _start_download(self, filename):
        if not self.session or not self.session.is_running:
            return
        self._downloads[filename] = {"status": "Iniciando..."}
        self._update_download_display()
        def worker():
            self.session.download(filename)
        threading.Thread(target=worker, daemon=True).start()

    def _update_download_display(self):
        self.dl_canvas.delete("all")
        y = 20
        for fname, info in list(self._downloads.items())[-3:]:
            status = info.get("status", "Baixando")
            pct = info.get("percent", 0)
            self.dl_canvas.create_text(10, y, anchor="w", text=f"{fname}  [{pct}%]  {status}")
            y += 20
        if not self._downloads:
            self.dl_canvas.create_text(10, 40, anchor="w", text="Nenhum download ativo", fill="gray")

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
        if event.kind == "search_result":
            self._show_results(event.payload)
        elif event.kind == "download_progress":
            self._update_download_progress(event.payload)
        elif event.kind == "download_complete":
            self.status_var.set("Download concluído")
            self.progress_var.set(100)
        elif event.kind == "published":
            self.status_var.set(f"Publicado: {event.message}")

    def _show_results(self, result: SearchResult | None):
        for item in self.result_tree.get_children():
            self.result_tree.delete(item)
        if not result or not result.peers:
            self.result_tree.insert("", "end", values=("Nenhum resultado", "", "", "", ""))
            return
        for peer in result.peers:
            self.result_tree.insert("", "end", values=(
                result.file_info.name,
                format_size(result.file_info.size),
                result.file_info.sha256[:16] + "...",
                len(result.peers),
                "⬇ Baixar"
            ))

    def _update_download_progress(self, progress: DownloadProgress):
        if progress.status == "complete":
            self.progress_var.set(100)
            self.status_var.set(f"{progress.filename} – Concluído")
        elif progress.status == "assembling":
            self.progress_var.set(99)
            self.status_var.set(f"{progress.filename} – Montando...")
        elif progress.status == "verifying":
            self.progress_var.set(99)
            self.status_var.set(f"{progress.filename} – Verificando...")
        else:
            percent = progress.percent
            if percent >= 100:
                percent = 99
            self.progress_var.set(percent)
            self.status_var.set(f"{progress.filename} – {percent}%")

        if progress.filename not in self._downloads:
            self._downloads[progress.filename] = {}
        self._downloads[progress.filename].update({
            "percent": progress.percent,
            "status": progress.status,
        })
        self._update_download_display()

    def _on_close(self):
        if self.session and self.session.is_running:
            self.session.stop()
        self.destroy()


def main():
    app = BitTorrentStyleGUI()
    app.mainloop()