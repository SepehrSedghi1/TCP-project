import os
import queue
import socket
import ssl
import time
from logging.handlers import QueueHandler
from tkinter import filedialog

import customtkinter as ctk

from ServerCore import ChatServer, setup_logging, log

APP_DIR = os.path.dirname(os.path.abspath(__file__))

ACCENT = "#3B82F6"
ACCENT_HOVER = "#2563EB"
DANGER = "#EF4444"
DANGER_HOVER = "#DC2626"
OK = "#22C55E"
IDLE = "#9CA3AF"
ROW_BG = ("#F3F4F6", "#23272E")
ERR_BG = ("#FEE2E2", "#4A2326")
TEXT = ("#111827", "#F3F4F6")
MUTED = ("#6B7280", "#9CA3AF")
SECONDARY = ("#D1D5DB", "#3A3F47")
SECONDARY_HOVER = ("#9CA3AF", "#4B5563")
LOG_WARNING = "#D97706"
LOG_ERROR = "#EF4444"
MAX_LOG_LINES = 1500


def lan_ip():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return "unknown"
    finally:
        probe.close()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("TCP Console Server")
        self.geometry("1120x760")
        self.minsize(960, 640)

        self.events = queue.Queue()
        self.log_queue = queue.Queue()
        self.log_handler = QueueHandler(self.log_queue)
        setup_logging(console=False)
        log.addHandler(self.log_handler)

        self.srv = None
        self.running = False
        self.started_at = None
        self.total_requests = 0
        self.rows = {}                
        self.empty_clients = None
        self.locked_widgets = []       
        self.my_ip = lan_ip()
        self.listen_text = ""

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()
        self._show_server_state(False)
        self._show_empty_clients()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self._poll_events)
        self.after(1000, self._tick_clock)

    def _build_sidebar(self):
        side = ctk.CTkFrame(self, width=300, corner_radius=0)
        side.grid(row=0, column=0, sticky="nsew")
        side.pack_propagate(False)

        ctk.CTkLabel(
            side, text="TCP Console", font=ctk.CTkFont(size=24, weight="bold"), anchor="w"
        ).pack(fill="x", padx=20, pady=(26, 0))
        ctk.CTkLabel(
            side, text="Server dashboard", text_color=MUTED, anchor="w"
        ).pack(fill="x", padx=20, pady=(0, 14))

        self.host = self._field(side, "Listen on", "0.0.0.0")
        self.port = self._field(side, "Port", "12000")
        self.cert_path = self._path_field(
            side, "Certificate", "server.crt", "Select certificate",
            [("Certificate", "*.crt *.pem"), ("All files", "*.*")],
        )
        self.key_path = self._path_field(
            side, "Private key", "server.key", "Select private key",
            [("Key", "*.key *.pem"), ("All files", "*.*")],
        )
        self.locked_widgets += [self.host, self.port]

        self.start_btn = ctk.CTkButton(
            side, text="Start server", height=42, corner_radius=10,
            font=ctk.CTkFont(size=14, weight="bold"), command=self._toggle_server,
        )
        self.start_btn.pack(fill="x", padx=20, pady=(20, 0))

        status_row = ctk.CTkFrame(side, fg_color="transparent")
        status_row.pack(fill="x", padx=20, pady=(14, 0))
        self.dot = ctk.CTkLabel(status_row, text="●", font=ctk.CTkFont(size=16))
        self.dot.pack(side="left", anchor="n")
        self.status = ctk.CTkLabel(status_row, text="", anchor="w", justify="left", wraplength=230)
        self.status.pack(side="left", padx=(6, 0))

        card = ctk.CTkFrame(side, corner_radius=12, fg_color=ROW_BG)
        card.pack(fill="x", padx=20, pady=(22, 0))
        ctk.CTkLabel(
            card, text="Clients on your network connect to", text_color=MUTED,
            font=ctk.CTkFont(size=12), anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 0))
        addr_row = ctk.CTkFrame(card, fg_color="transparent")
        addr_row.pack(fill="x", padx=14, pady=(2, 12))
        ctk.CTkLabel(
            addr_row, text=self.my_ip, font=ctk.CTkFont(size=16, weight="bold")
        ).pack(side="left")
        ctk.CTkButton(
            addr_row, text="Copy", width=56, height=26, fg_color=SECONDARY,
            hover_color=SECONDARY_HOVER, text_color=TEXT, command=self._copy_address,
        ).pack(side="right")

        bottom = ctk.CTkFrame(side, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=20, pady=20)
        ctk.CTkButton(
            bottom, text="Clear log", height=34, fg_color="transparent",
            border_width=1, border_color=MUTED, text_color=MUTED,
            hover_color=ROW_BG, command=self._clear_log,
        ).pack(fill="x")
        self.theme_switch = ctk.CTkSwitch(bottom, text="Dark mode", command=self._toggle_theme)
        if ctk.get_appearance_mode() == "Dark":
            self.theme_switch.select()
        self.theme_switch.pack(anchor="w", pady=(14, 0))

    def _field(self, parent, label, value):
        ctk.CTkLabel(
            parent, text=label, text_color=MUTED, font=ctk.CTkFont(size=12), anchor="w"
        ).pack(fill="x", padx=20, pady=(10, 0))
        entry = ctk.CTkEntry(parent, height=34)
        entry.insert(0, value)
        entry.pack(fill="x", padx=20, pady=(4, 0))
        return entry

    def _path_field(self, parent, label, filename, title, filetypes):
        ctk.CTkLabel(
            parent, text=label, text_color=MUTED, font=ctk.CTkFont(size=12), anchor="w"
        ).pack(fill="x", padx=20, pady=(10, 0))
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(4, 0))
        entry = ctk.CTkEntry(row, height=34)
        entry.insert(0, os.path.join(APP_DIR, filename))
        entry.pack(side="left", fill="x", expand=True)
        browse = ctk.CTkButton(
            row, text="…", width=36, height=34, fg_color=SECONDARY,
            hover_color=SECONDARY_HOVER, text_color=TEXT,
            command=lambda: self._browse(entry, title, filetypes),
        )
        browse.pack(side="left", padx=(6, 0))
        self.locked_widgets += [entry, browse]
        return entry

    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(3, weight=1)

        header = ctk.CTkFrame(main, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 10))
        ctk.CTkLabel(
            header, text="Server activity", font=ctk.CTkFont(size=20, weight="bold")
        ).pack(side="left")
        self.badge = ctk.CTkLabel(header, text="", text_color=MUTED, font=ctk.CTkFont(size=12))
        self.badge.pack(side="right")

        stats = ctk.CTkFrame(main, fg_color="transparent")
        stats.grid(row=1, column=0, sticky="ew", padx=28)
        for column in range(3):
            stats.grid_columnconfigure(column, weight=1, uniform="stat")
        self.stat_clients = self._stat_card(stats, 0, "Connected clients")
        self.stat_requests = self._stat_card(stats, 1, "Requests handled")
        self.stat_uptime = self._stat_card(stats, 2, "Uptime")

        clients = ctk.CTkFrame(main, corner_radius=14)
        clients.grid(row=2, column=0, sticky="ew", padx=28, pady=(14, 0))
        ctk.CTkLabel(
            clients, text="Connected clients", font=ctk.CTkFont(size=14, weight="bold"), anchor="w"
        ).pack(fill="x", padx=16, pady=(12, 4))
        self.clients_box = ctk.CTkScrollableFrame(clients, height=170, fg_color="transparent")
        self.clients_box.pack(fill="x", padx=8, pady=(0, 10))

        logs = ctk.CTkFrame(main, corner_radius=14)
        logs.grid(row=3, column=0, sticky="nsew", padx=28, pady=(14, 24))
        logs.grid_columnconfigure(0, weight=1)
        logs.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            logs, text="Live log", font=ctk.CTkFont(size=14, weight="bold"), anchor="w"
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(12, 4))
        self.log_box = ctk.CTkTextbox(
            logs, font=ctk.CTkFont(family="Consolas", size=12), wrap="none",
            fg_color="transparent",
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 10))
        self.log_box.tag_config("WARNING", foreground=LOG_WARNING)
        self.log_box.tag_config("ERROR", foreground=LOG_ERROR)
        self.log_box.configure(state="disabled")

    def _stat_card(self, parent, column, label):
        card = ctk.CTkFrame(parent, corner_radius=14)
        card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 8, 0))
        value = ctk.CTkLabel(card, text="0", font=ctk.CTkFont(size=28, weight="bold"), anchor="w")
        value.pack(anchor="w", padx=18, pady=(14, 0))
        ctk.CTkLabel(
            card, text=label, text_color=MUTED, font=ctk.CTkFont(size=12), anchor="w"
        ).pack(anchor="w", padx=18, pady=(0, 14))
        return value

    def _show_empty_clients(self):
        self.empty_clients = ctk.CTkLabel(
            self.clients_box, text="No clients connected", text_color=MUTED,
            font=ctk.CTkFont(size=13),
        )
        self.empty_clients.pack(pady=40)

    def _drop_empty_clients(self):
        if self.empty_clients is not None:
            self.empty_clients.destroy()
            self.empty_clients = None

    def _add_client_row(self, who, tls):
        if who in self.rows:
            return
        self._drop_empty_clients()
        row = ctk.CTkFrame(self.clients_box, corner_radius=10, fg_color=ROW_BG)
        row.pack(fill="x", pady=3, padx=2)
        row.grid_columnconfigure(0, weight=1)

        text = ctk.CTkFrame(row, fg_color="transparent")
        text.grid(row=0, column=0, sticky="w", padx=14, pady=8)
        ctk.CTkLabel(
            text, text=who, font=ctk.CTkFont(size=14, weight="bold"), anchor="w"
        ).pack(anchor="w")
        detail = ctk.CTkLabel(
            text, text=f"{tls}, 0 requests", text_color=MUTED,
            font=ctk.CTkFont(size=12), anchor="w",
        )
        detail.pack(anchor="w")

        ctk.CTkButton(
            row, text="Disconnect", width=100, height=30, fg_color="transparent",
            border_width=1, border_color=DANGER, text_color=DANGER, hover_color=ERR_BG,
            command=lambda w=who: self._kick_client(w),
        ).grid(row=0, column=1, padx=14)
        self.rows[who] = {"row": row, "detail": detail, "tls": tls}

    def _remove_client_row(self, who):
        widgets = self.rows.pop(who, None)
        if widgets is not None:
            widgets["row"].destroy()
        if not self.rows and self.empty_clients is None:
            self._show_empty_clients()

    def _kick_client(self, who):
        if self.srv is not None:
            self.srv.kick(who)

    def _append_log(self, record):
        stamp = time.strftime("%H:%M:%S", time.localtime(record.created))
        line = f"{stamp}  {record.levelname:<7} {record.getMessage()}\n"
        tag = record.levelname if record.levelname in ("WARNING", "ERROR") else None
        box = self.log_box
        box.configure(state="normal")
        box.insert("end", line, tag)
        if int(box.index("end-1c").split(".")[0]) > MAX_LOG_LINES:
            box.delete("1.0", "301.0")
        box.configure(state="disabled")
        box._textbox.see("end")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")


    def _show_server_state(self, running, message="", error=False):
        self.running = running
        for widget in self.locked_widgets:
            widget.configure(state="disabled" if running else "normal")

        if running:
            self.start_btn.configure(
                text="Stop server", fg_color=DANGER, hover_color=DANGER_HOVER, state="normal"
            )
            self.dot.configure(text_color=OK)
            self.status.configure(text=message or "Listening for connections", text_color=TEXT)
            self.badge.configure(text=f"Listening on {self.listen_text}")
        else:
            self.start_btn.configure(
                text="Start server", fg_color=ACCENT, hover_color=ACCENT_HOVER, state="normal"
            )
            self.dot.configure(text_color=DANGER if error else IDLE)
            self.status.configure(
                text=message or "Server is stopped",
                text_color=("#991B1B", "#FCA5A5") if error else TEXT,
            )
            self.badge.configure(text="Stopped")
        self._refresh_stats()

    def _refresh_stats(self):
        self.stat_clients.configure(text=str(len(self.rows)))
        self.stat_requests.configure(text=str(self.total_requests))
        if self.running and self.started_at is not None:
            hours, rest = divmod(int(time.time() - self.started_at), 3600)
            minutes, seconds = divmod(rest, 60)
            self.stat_uptime.configure(text=f"{hours}:{minutes:02d}:{seconds:02d}")
        else:
            self.stat_uptime.configure(text="0:00:00")


    def _toggle_server(self):
        if self.running:
            self._stop_server()
        else:
            self._start_server()

    def _start_server(self):
        host = self.host.get().strip() or "0.0.0.0"
        try:
            port = int(self.port.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            self._show_server_state(False, "Port must be a number from 1 to 65535.", error=True)
            return

        srv = ChatServer(
            host, port, self.cert_path.get().strip(), self.key_path.get().strip(),
            on_event=lambda *args: self.events.put(args),
        )
        try:
            srv.start()
        except FileNotFoundError as e:
            self._show_server_state(False, f"File not found: {e.filename}", error=True)
            return
        except ssl.SSLError as e:
            self._show_server_state(
                False, f"Certificate and key do not work together: {e}", error=True
            )
            return
        except OSError as e:
            self._show_server_state(
                False, f"Cannot listen on port {port}: {e.strerror or e}", error=True
            )
            return

        self.srv = srv
        self.started_at = time.time()
        self.total_requests = 0
        self.listen_text = f"{host}:{port}"
        self._show_server_state(True)

    def _stop_server(self):
        self.start_btn.configure(state="disabled", text="Stopping…")
        self.update_idletasks()
        self.srv.stop()
        self.srv = None
        self._show_server_state(False)

    def _copy_address(self):
        self.clipboard_clear()
        self.clipboard_append(self.my_ip)

    def _browse(self, entry, title, filetypes):
        path = filedialog.askopenfilename(title=title, filetypes=filetypes)
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)

    def _toggle_theme(self):
        ctk.set_appearance_mode("dark" if self.theme_switch.get() else "light")

    def _on_close(self):
        if self.srv is not None:
            self.srv.stop()
        log.removeHandler(self.log_handler)
        self.destroy()

    def _poll_events(self):
        try:
            for _ in range(200):              
                try:
                    kind, *args = self.events.get_nowait()
                except queue.Empty:
                    break
                self._handle_event(kind, *args)
            for _ in range(200):
                try:
                    self._append_log(self.log_queue.get_nowait())
                except queue.Empty:
                    break
        finally:
            self.after(50, self._poll_events)

    def _handle_event(self, kind, *args):
        if kind == "client_connected":
            who, tls, _cipher = args
            self._add_client_row(who, tls)
        elif kind == "request":
            who, _cmd, _status, count = args
            self.total_requests += 1
            widgets = self.rows.get(who)
            if widgets is not None:
                noun = "request" if count == 1 else "requests"
                widgets["detail"].configure(text=f"{widgets['tls']}, {count} {noun}")
        elif kind == "client_disconnected":
            self._remove_client_row(args[0])
        self._refresh_stats()

    def _tick_clock(self):
        try:
            if self.running and self.srv is not None and not self.srv.running:
                self.srv = None
                self._show_server_state(
                    False, "The server stopped unexpectedly. See the log.", error=True
                )
            self._refresh_stats()
        finally:
            self.after(1000, self._tick_clock)


if __name__ == "__main__":
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    App().mainloop()