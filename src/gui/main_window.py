import os
import queue
import socket
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from src.app.events import AppEvent
from src.app.models import DownloadProgress, LocalFile, NetworkSnapshot, SearchResult
from src.app.peer_session import PeerSession
from src.peer.client import format_size


class BitTorrentStyleGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("P2P-IsoDistrib")
        self.geometry("1180x760")
        self.minsize(920, 620)
        self.configure(bg="#eef3f7")

        self.session: PeerSession | None = None
        self.events: queue.Queue[AppEvent] = queue.Queue()
        self._downloads: dict[str, dict] = {}
        self._network_refresh_job = None
        self._last_result: SearchResult | None = None

        self._configure_styles()
        self._build_ui()
        self.after(100, self._process_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(500, self._auto_start)

    def _configure_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        font_ui = "{Segoe UI} 10"
        font_ui_small = "{Segoe UI} 9"
        font_ui_semibold = "{Segoe UI Semibold} 10"
        font_ui_semibold_large = "{Segoe UI Semibold} 18"
        font_ui_semibold_title = "{Segoe UI Semibold} 20"

        self.option_add("*Font", font_ui)
        self.option_add("*TCombobox*Listbox.font", font_ui)

        style.configure("Root.TFrame", background="#eef3f7")
        style.configure("Card.TFrame", background="#ffffff", relief="flat")
        style.configure("Hero.TFrame", background="#12344d")
        style.configure("Section.TLabelframe", background="#ffffff", borderwidth=0)
        style.configure("Section.TLabelframe.Label", background="#ffffff", foreground="#12344d", font=font_ui_semibold)
        style.configure("Title.TLabel", background="#12344d", foreground="#ffffff", font=font_ui_semibold_title)
        style.configure("HeroText.TLabel", background="#12344d", foreground="#d9e7f2", font=font_ui)
        style.configure("HeroPill.TLabel", background="#1d4f73", foreground="#ffffff", font=font_ui_semibold, padding=(12, 7))
        style.configure("CardTitle.TLabel", background="#ffffff", foreground="#12344d", font=font_ui_semibold)
        style.configure("CardValue.TLabel", background="#ffffff", foreground="#0f1720", font=font_ui_semibold_large)
        style.configure("Hint.TLabel", background="#ffffff", foreground="#597081", font=font_ui_small)
        style.configure("Body.TLabel", background="#ffffff", foreground="#1d2a33", font=font_ui)
        style.configure("Primary.TButton", font=font_ui_semibold, padding=(16, 10))
        style.configure("Secondary.TButton", font=font_ui, padding=(12, 9))
        style.configure("Status.TLabel", background="#ffffff", foreground="#12344d", font=font_ui_semibold)
        style.configure("Banner.TLabel", background="#dff3ff", foreground="#12344d", font=font_ui, padding=(12, 10))
        style.configure("TLabelframe", background="#ffffff")
        style.configure("TFrame", background="#eef3f7")
        style.configure("Treeview", rowheight=28, font=font_ui)
        style.configure("Treeview.Heading", font=font_ui_semibold)
        style.map("Treeview", background=[("selected", "#d7ebf9")], foreground=[("selected", "#102534")])
        style.configure("TNotebook", background="#eef3f7", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 10), font=font_ui_semibold)

    def _find_free_port(self) -> int:
        with socket.socket() as sock:
            sock.bind(("", 0))
            return sock.getsockname()[1]

    def _runtime_root(self, port: int) -> str:
        return os.path.abspath(os.path.join(os.getcwd(), "gui_runtime", f"peer_{port}"))

    def _auto_start(self):
        self._start_peer()

    def _start_peer(self):
        if self.session and self.session.is_running:
            return

        port = self._find_free_port()
        runtime_root = self._runtime_root(port)
        shared_folder = os.path.join(runtime_root, "shared_files")
        download_folder = os.path.join(runtime_root, "downloads")

        self.session = PeerSession(
            port=port,
            shared_folder=shared_folder,
            download_folder=download_folder,
            on_event=self._queue_event,
        )

        def worker():
            started = self.session.start(allow_offline=True)
            if started:
                self._queue_event(
                    AppEvent(
                        "status",
                        f"Peer pronto para uso na porta {port}",
                        {
                            "port": port,
                            "shared_folder": shared_folder,
                            "download_folder": download_folder,
                        },
                    )
                )
                self._refresh_local()
                self._refresh_network()
            else:
                self._queue_event(AppEvent("status", "Modo offline: tracker indisponivel"))

        threading.Thread(target=worker, daemon=True).start()

    def _search(self):
        if not self.session or not self.session.is_running:
            messagebox.showinfo("Buscar ISO", "O peer ainda esta iniciando. Aguarde alguns segundos.")
            return

        query = self.search_var.get().strip()
        if not query:
            messagebox.showinfo("Buscar ISO", "Digite o nome da ISO que deseja procurar.")
            return

        self.status_var.set(f"Buscando por '{query}'...")

        def worker():
            result = self.session.search(query)
            self._queue_event(AppEvent("search_result", "Busca concluida", result))
            self._refresh_network()

        threading.Thread(target=worker, daemon=True).start()

    def _publish_file(self):
        initial_dir = self.session.shared_folder if self.session else os.getcwd()
        path = filedialog.askopenfilename(
            title="Escolher ISO para compartilhar",
            initialdir=initial_dir,
            filetypes=[("Arquivos ISO", "*.iso"), ("Todos", "*.*")],
        )
        if not path or not self.session:
            return

        popup = tk.Toplevel(self)
        popup.title("Compartilhando arquivo")
        popup.geometry("360x110")
        popup.resizable(False, False)
        popup.configure(bg="#ffffff")
        ttk.Label(popup, text="Registrando a ISO no tracker...", style="Body.TLabel").pack(pady=(16, 10))
        progress = ttk.Progressbar(popup, mode="indeterminate")
        progress.pack(fill="x", padx=20, pady=5)
        progress.start()

        def worker():
            try:
                self.session.publish(path)
                self._refresh_network()
            finally:
                popup.after(0, popup.destroy)
                self.after(0, self._refresh_local)

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_local(self):
        if not self.session:
            return

        def worker():
            self.session.list_local_files()

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_network(self):
        if not self.session or not self.session.is_running:
            return

        def worker():
            self.session.list_network_peers()

        threading.Thread(target=worker, daemon=True).start()

    def _schedule_network_refresh(self):
        if self._network_refresh_job is not None:
            self.after_cancel(self._network_refresh_job)
        self._network_refresh_job = self.after(5000, self._poll_network)

    def _poll_network(self):
        self._network_refresh_job = None
        self._refresh_network()

    def _build_ui(self):
        root = ttk.Frame(self, style="Root.TFrame", padding=16)
        root.pack(fill="both", expand=True)

        hero = ttk.Frame(root, style="Hero.TFrame", padding=22)
        hero.pack(fill="x")

        left_hero = ttk.Frame(hero, style="Hero.TFrame")
        left_hero.pack(side="left", fill="x", expand=True)
        ttk.Label(left_hero, text="P2P-IsoDistrib", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            left_hero,
            text="Compartilhe e baixe ISOs sem precisar entender detalhes tecnicos da rede.",
            style="HeroText.TLabel",
        ).pack(anchor="w", pady=(6, 0))

        right_hero = ttk.Frame(hero, style="Hero.TFrame")
        right_hero.pack(side="right", anchor="ne")
        self.connection_badge_var = tk.StringVar(value="Iniciando peer")
        ttk.Label(right_hero, textvariable=self.connection_badge_var, style="HeroPill.TLabel").pack(anchor="e")

        banner = ttk.Label(
            root,
            text="1. Compartilhe uma ISO no botao abaixo. 2. Busque pelo nome em outra janela. 3. Dê duplo clique no resultado para baixar.",
            style="Banner.TLabel",
        )
        banner.pack(fill="x", pady=(14, 14))

        metrics = ttk.Frame(root, style="Root.TFrame")
        metrics.pack(fill="x")
        metrics.columnconfigure((0, 1, 2), weight=1)

        self.peer_count_var = tk.StringVar(value="0")
        self.file_count_var = tk.StringVar(value="0")
        self.local_count_var = tk.StringVar(value="0")
        self._create_metric_card(metrics, 0, "Peers conectados", self.peer_count_var, "Quantidade de peers ativos vistos no tracker.")
        self._create_metric_card(metrics, 1, "Arquivos anunciados", self.file_count_var, "Total de anuncios de arquivos feitos na rede.")
        self._create_metric_card(metrics, 2, "Arquivos deste peer", self.local_count_var, "ISOs que esta janela pode disponibilizar.")

        action_row = ttk.Frame(root, style="Root.TFrame")
        action_row.pack(fill="x", pady=(14, 10))
        ttk.Button(action_row, text="Compartilhar uma ISO", command=self._publish_file, style="Primary.TButton").pack(side="left")
        ttk.Button(action_row, text="Atualizar rede", command=self._refresh_network, style="Secondary.TButton").pack(side="left", padx=(10, 0))
        ttk.Button(action_row, text="Atualizar arquivos locais", command=self._refresh_local, style="Secondary.TButton").pack(side="left", padx=(10, 0))
        ttk.Button(action_row, text="Informacoes deste peer", command=self._show_config, style="Secondary.TButton").pack(side="right")

        status_card = ttk.Frame(root, style="Card.TFrame", padding=14)
        status_card.pack(fill="x", pady=(0, 12))
        self.status_var = tk.StringVar(value="Inicializando peer...")
        self.peer_identity_var = tk.StringVar(value="Peer local: inicializando...")
        self.peer_paths_var = tk.StringVar(value="Pastas locais ainda nao definidas.")
        self.network_summary_var = tk.StringVar(value="Rede: aguardando tracker...")
        ttk.Label(status_card, text="Status atual", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(status_card, textvariable=self.status_var, style="Status.TLabel").pack(anchor="w", pady=(6, 2))
        ttk.Label(status_card, textvariable=self.peer_identity_var, style="Body.TLabel").pack(anchor="w")
        ttk.Label(status_card, textvariable=self.network_summary_var, style="Body.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(status_card, textvariable=self.peer_paths_var, style="Hint.TLabel", wraplength=980).pack(anchor="w", pady=(4, 0))

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)

        self.search_tab = ttk.Frame(notebook, padding=14, style="Card.TFrame")
        self.local_tab = ttk.Frame(notebook, padding=14, style="Card.TFrame")
        self.network_tab = ttk.Frame(notebook, padding=14, style="Card.TFrame")
        notebook.add(self.search_tab, text="Buscar e baixar")
        notebook.add(self.local_tab, text="Meus arquivos")
        notebook.add(self.network_tab, text="Rede")

        self._build_search_tab()
        self._build_local_tab()
        self._build_network_tab()

    def _create_metric_card(self, parent, column, title, value_var, hint):
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 10, 0))
        ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(card, textvariable=value_var, style="CardValue.TLabel").pack(anchor="w", pady=(6, 2))
        ttk.Label(card, text=hint, style="Hint.TLabel", wraplength=250).pack(anchor="w")

    def _build_search_tab(self):
        intro = ttk.Frame(self.search_tab, style="Card.TFrame")
        intro.pack(fill="x")
        ttk.Label(intro, text="Encontrar uma ISO na rede", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            intro,
            text="Digite parte do nome do arquivo. Quando o resultado aparecer, dê duplo clique para iniciar o download.",
            style="Hint.TLabel",
            wraplength=860,
        ).pack(anchor="w", pady=(4, 10))

        search_row = ttk.Frame(self.search_tab, style="Card.TFrame")
        search_row.pack(fill="x", pady=(0, 12))
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_row, textvariable=self.search_var, font=("Segoe UI", 11))
        search_entry.pack(side="left", fill="x", expand=True)
        search_entry.bind("<Return>", lambda _event: self._search())
        ttk.Button(search_row, text="Buscar ISO", command=self._search, style="Primary.TButton").pack(side="left", padx=(10, 0))

        result_frame = ttk.LabelFrame(self.search_tab, text="Resultados encontrados", style="Section.TLabelframe", padding=10)
        result_frame.pack(fill="both", expand=True)
        ttk.Label(
            result_frame,
            text="A coluna 'Peers com arquivo' mostra quantas maquinas atualmente anunciam essa ISO.",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(0, 8))

        result_columns = ("name", "size", "sha256", "file_peers", "locations")
        self.result_tree = ttk.Treeview(result_frame, columns=result_columns, show="headings", height=11)
        self.result_tree.heading("name", text="Arquivo")
        self.result_tree.heading("size", text="Tamanho")
        self.result_tree.heading("sha256", text="Identificador")
        self.result_tree.heading("file_peers", text="Peers com arquivo")
        self.result_tree.heading("locations", text="Origem")
        self.result_tree.column("name", width=250)
        self.result_tree.column("size", width=110, anchor="e")
        self.result_tree.column("sha256", width=170)
        self.result_tree.column("file_peers", width=120, anchor="center")
        self.result_tree.column("locations", width=270)
        self.result_tree.pack(side="left", fill="both", expand=True)
        result_scroll = ttk.Scrollbar(result_frame, orient="vertical", command=self.result_tree.yview)
        result_scroll.pack(side="right", fill="y")
        self.result_tree.configure(yscrollcommand=result_scroll.set)
        self.result_tree.bind("<Double-1>", self._on_result_double_click)

        footer = ttk.Frame(self.search_tab, style="Card.TFrame")
        footer.pack(fill="x", pady=(12, 0))
        self.download_summary_var = tk.StringVar(value="Nenhum download ativo no momento.")
        ttk.Label(footer, text="Downloads em andamento", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(footer, textvariable=self.download_summary_var, style="Body.TLabel").pack(anchor="w", pady=(4, 6))
        self.progress_var = tk.IntVar(value=0)
        self.progress_bar = ttk.Progressbar(footer, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill="x")
        self.download_listbox = tk.Listbox(
            footer,
            height=4,
            borderwidth=0,
            highlightthickness=0,
            background="#ffffff",
            foreground="#12344d",
            font=("Segoe UI", 10),
            activestyle="none",
        )
        self.download_listbox.pack(fill="x", pady=(8, 0))
        self._update_download_display()

    def _build_local_tab(self):
        top = ttk.Frame(self.local_tab, style="Card.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="Arquivos que este peer pode disponibilizar", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            top,
            text="Aqui aparecem as ISOs locais e as que este peer baixou e passou a semear automaticamente.",
            style="Hint.TLabel",
            wraplength=860,
        ).pack(anchor="w", pady=(4, 10))

        local_frame = ttk.LabelFrame(self.local_tab, text="Minha biblioteca local", style="Section.TLabelframe", padding=10)
        local_frame.pack(fill="both", expand=True)
        local_columns = ("name", "size", "sha256")
        self.local_tree = ttk.Treeview(local_frame, columns=local_columns, show="headings", height=14)
        self.local_tree.heading("name", text="Arquivo")
        self.local_tree.heading("size", text="Tamanho")
        self.local_tree.heading("sha256", text="Identificador")
        self.local_tree.column("name", width=300)
        self.local_tree.column("size", width=110, anchor="e")
        self.local_tree.column("sha256", width=220)
        self.local_tree.pack(side="left", fill="both", expand=True)
        local_scroll = ttk.Scrollbar(local_frame, orient="vertical", command=self.local_tree.yview)
        local_scroll.pack(side="right", fill="y")
        self.local_tree.configure(yscrollcommand=local_scroll.set)

    def _build_network_tab(self):
        top = ttk.Frame(self.network_tab, style="Card.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="Visao geral da rede", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            top,
            text="Esta aba mostra os peers ativos vistos pelo tracker, mesmo que eles nao tenham a ISO que voce buscou.",
            style="Hint.TLabel",
            wraplength=860,
        ).pack(anchor="w", pady=(4, 10))

        peers_frame = ttk.LabelFrame(self.network_tab, text="Peers ativos", style="Section.TLabelframe", padding=10)
        peers_frame.pack(fill="both", expand=True)
        peer_columns = ("address", "files", "heartbeat")
        self.network_tree = ttk.Treeview(peers_frame, columns=peer_columns, show="headings", height=14)
        self.network_tree.heading("address", text="Peer")
        self.network_tree.heading("files", text="Arquivos publicados")
        self.network_tree.heading("heartbeat", text="Ultimo heartbeat")
        self.network_tree.column("address", width=180)
        self.network_tree.column("files", width=420)
        self.network_tree.column("heartbeat", width=130, anchor="center")
        self.network_tree.pack(side="left", fill="both", expand=True)
        peer_scroll = ttk.Scrollbar(peers_frame, orient="vertical", command=self.network_tree.yview)
        peer_scroll.pack(side="right", fill="y")
        self.network_tree.configure(yscrollcommand=peer_scroll.set)

    def _show_config(self):
        win = tk.Toplevel(self)
        win.title("Informacoes deste peer")
        win.geometry("420x210")
        win.resizable(False, False)
        win.configure(bg="#ffffff")
        card = ttk.Frame(win, style="Card.TFrame", padding=18)
        card.pack(fill="both", expand=True)
        ttk.Label(card, text="Detalhes da instancia atual", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(card, textvariable=self.peer_identity_var, style="Body.TLabel").pack(anchor="w", pady=(10, 4))
        ttk.Label(card, textvariable=self.network_summary_var, style="Body.TLabel", wraplength=370).pack(anchor="w", pady=(0, 4))
        ttk.Label(card, textvariable=self.peer_paths_var, style="Hint.TLabel", wraplength=370).pack(anchor="w", pady=(0, 16))
        ttk.Button(card, text="Fechar", command=win.destroy, style="Secondary.TButton").pack(anchor="e")

    def _on_result_double_click(self, _event):
        selected = self.result_tree.selection()
        if not selected:
            return

        item = self.result_tree.item(selected[0])
        filename = item["values"][0]
        if filename and filename != "Nenhum resultado":
            self._start_download(filename)

    def _start_download(self, filename):
        if not self.session or not self.session.is_running:
            return

        self._downloads[filename] = {"status": "Preparando download...", "percent": 0}
        self._update_download_display()
        self.status_var.set(f"Iniciando download de {filename}...")

        def worker():
            self.session.download(filename)
            self._refresh_network()
            self._refresh_local()

        threading.Thread(target=worker, daemon=True).start()

    def _update_download_display(self):
        if not hasattr(self, "download_listbox"):
            return

        self.download_listbox.delete(0, tk.END)
        if not self._downloads:
            self.download_summary_var.set("Nenhum download ativo no momento.")
            self.download_listbox.insert(tk.END, "Quando um download comecar, ele aparecera aqui.")
            return

        recent = list(self._downloads.items())[-4:]
        active = 0
        for filename, info in recent:
            status = info.get("status", "Baixando")
            percent = info.get("percent", 0)
            if status not in {"complete", "failed"}:
                active += 1
            self.download_listbox.insert(tk.END, f"{filename}  |  {percent}%  |  {status}")

        self.download_summary_var.set(f"{active} download(s) em andamento ou recem-finalizados.")

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
            self.status_var.set("Download concluido e arquivo agora pode ser compartilhado.")
            self.progress_var.set(100)
        elif event.kind == "published":
            self.status_var.set(f"ISO compartilhada com sucesso: {os.path.basename(str(event.payload))}")
        elif event.kind == "local_files":
            self._show_local_files(event.payload or [])
        elif event.kind == "network_peers":
            self._show_network_peers(event.payload)
        elif event.kind == "status":
            self.status_var.set(event.message)
            self.connection_badge_var.set("Peer online")
            if isinstance(event.payload, dict):
                port = event.payload.get("port")
                shared_folder = event.payload.get("shared_folder", "")
                download_folder = event.payload.get("download_folder", "")
                self.peer_identity_var.set(f"Peer local: 127.0.0.1:{port}")
                self.peer_paths_var.set(f"Compartilhados: {shared_folder} | Downloads: {download_folder}")
                self._schedule_network_refresh()
        elif event.kind == "error":
            self.status_var.set(event.message)
        elif event.kind == "warning":
            self.status_var.set(event.message)
            self.connection_badge_var.set("Modo offline")

    def _show_results(self, result: SearchResult | None):
        self._last_result = result
        for item in self.result_tree.get_children():
            self.result_tree.delete(item)

        if not result or not result.peers:
            self.result_tree.insert("", "end", values=("Nenhum resultado", "", "", "", ""))
            self.status_var.set("Nenhuma ISO encontrada para essa busca.")
            return

        locations = ", ".join(f"{peer.ip}:{peer.port}" for peer in result.peers[:3])
        if len(result.peers) > 3:
            locations += f" +{len(result.peers) - 3}"

        self.result_tree.insert(
            "",
            "end",
            values=(
                result.file_info.name,
                format_size(result.file_info.size),
                result.file_info.sha256[:16] + "...",
                len(result.peers),
                locations,
            ),
        )
        self.status_var.set(
            f"Encontrada {result.file_info.name} em {len(result.peers)} peer(s). Dê duplo clique para baixar."
        )

    def _show_local_files(self, files: list[LocalFile]):
        for item in self.local_tree.get_children():
            self.local_tree.delete(item)

        self.local_count_var.set(str(len(files)))

        if not files:
            self.local_tree.insert("", "end", values=("Nenhuma ISO local", "", ""))
            return

        for local_file in files:
            self.local_tree.insert(
                "",
                "end",
                values=(
                    local_file.name,
                    format_size(local_file.size),
                    local_file.sha256[:16] + "...",
                ),
            )

    def _show_network_peers(self, snapshot: NetworkSnapshot | None):
        for item in self.network_tree.get_children():
            self.network_tree.delete(item)

        if not snapshot or not snapshot.peers:
            self.peer_count_var.set("0")
            self.file_count_var.set("0")
            self.network_tree.insert("", "end", values=("Nenhum peer ativo", "", ""))
            self.network_summary_var.set("Rede: 0 peers conectados")
            self._schedule_network_refresh()
            return

        self.peer_count_var.set(str(snapshot.peer_count))
        self.file_count_var.set(str(snapshot.published_file_count))

        for peer in snapshot.peers:
            files_label = ", ".join(peer.files[:2]) if peer.files else "sem arquivos"
            if len(peer.files) > 2:
                files_label += f" +{len(peer.files) - 2}"
            self.network_tree.insert(
                "",
                "end",
                values=(
                    f"{peer.ip}:{peer.port}",
                    files_label,
                    f"{peer.last_heartbeat_age_seconds:.0f}s",
                ),
            )

        self.network_summary_var.set(
            f"Rede: {snapshot.peer_count} peers conectados | {snapshot.published_file_count} anuncio(s) de arquivo"
        )
        self._schedule_network_refresh()

    def _update_download_progress(self, progress: DownloadProgress):
        if progress.status == "complete":
            self.progress_var.set(100)
            self.status_var.set(f"{progress.filename} concluido com sucesso.")
        elif progress.status == "assembling":
            self.progress_var.set(99)
            self.status_var.set(f"Montando {progress.filename}...")
        elif progress.status == "verifying":
            self.progress_var.set(99)
            self.status_var.set(f"Verificando integridade de {progress.filename}...")
        elif progress.status == "failed":
            self.status_var.set(f"Falha ao baixar {progress.filename}.")
        else:
            percent = min(progress.percent, 99)
            self.progress_var.set(percent)
            self.status_var.set(
                f"Baixando {progress.filename}: {percent}% com {progress.active_peers} peer(s) ativos."
            )

        if progress.filename not in self._downloads:
            self._downloads[progress.filename] = {}
        self._downloads[progress.filename].update(
            {
                "percent": progress.percent,
                "status": progress.status,
            }
        )
        self._update_download_display()

    def _on_close(self):
        if self._network_refresh_job is not None:
            self.after_cancel(self._network_refresh_job)
            self._network_refresh_job = None
        if self.session and self.session.is_running:
            self.session.stop()
        self.destroy()


def main():
    app = BitTorrentStyleGUI()
    app.mainloop()
