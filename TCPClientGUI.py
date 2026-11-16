import os
import queue
import socket
import ssl
import threading
import time
from tkinter import filedialog

import customtkinter as ctk

from protocol import send_msg, recv_msg

APP_DIR = os.path.dirname(os.path.abspath(__file__))
COMMANDS = ["upper", "lower", "reverse", "title", "count"]

ACCENT = "#3B82F6"
ACCENT_HOVER = "#2563EB"
DANGER = "#EF4444"
DANGER_HOVER = "#DC2626"
BUBBLE_IN = ("#E5E7EB", "#2B2F36")
BUBBLE_ERR = ("#FEE2E2", "#4A2326")
TEXT_IN = ("#111827", "#F3F4F6")
TEXT_ERR = ("#991B1B", "#FCA5A5")
MUTED = ("#6B7280", "#9CA3AF")
STATUS_COLORS = {
    "offline": "#9CA3AF",
    "connecting": "#F59E0B",
    "online": "#22C55E",
    "error": "#EF4444",
}


class Connection:

    def __init__(self, events):
        self.events = events
        self.outbox = None            

    @property
    def active(self):
        return self.outbox is not None

    def open(self, host, port, cert, verify_hostname):
        self.outbox = queue.Queue()
        threading.Thread(
            target=self._run,
            args=(self.outbox, host, port, cert, verify_hostname),
            daemon=True,
        ).start()

    def send(self, cmd, data):
        if self.outbox is not None:
            self.outbox.put({"cmd": cmd, "data": data})

    def close(self):
        if self.outbox is not None:
            self.outbox.put(None)     
            self.outbox = None        

    def _run(self, session, host, port, cert, verify_hostname):
        def post(*event):
            self.events.put((session, *event))

        sock = None
        reason, is_error = "Disconnected.", False
        try:
            context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=cert)
            context.check_hostname = verify_hostname
            raw = socket.create_connection((host, port), timeout=10)
            sock = context.wrap_socket(raw, server_hostname=host)
            sock.settimeout(15)
            post("connected", sock.version())
            while True:
                request = session.get()
                if request is None:
                    break
                started = time.perf_counter()
                send_msg(sock, request)
                reply = recv_msg(sock)
                if reply is None:
                    reason, is_error = "The server closed the connection.", True
                    break
                post("reply", request, reply, (time.perf_counter() - started) * 1000)
        except ssl.SSLCertVerificationError as e:
            reason, is_error = f"Certificate check failed: {e.verify_message}", True
        except FileNotFoundError:
            reason, is_error = f"Certificate file not found: {cert}", True
        except ConnectionRefusedError:
            reason, is_error = "Connection refused. Is the server running?", True
        except TimeoutError:
            reason, is_error = "Timed out waiting for the server.", True
        except ssl.SSLError as e:
            reason, is_error = f"TLS error: {e}", True
        except ValueError as e:
            reason, is_error = f"Bad reply from server: {e}", True
        except OSError as e:
            reason, is_error = f"Connection error: {e}", True
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            post("disconnected", reason, is_error)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("TCP Console")
        self.geometry("1000x700")
        self.minsize(840, 580)

        self.events = queue.Queue()
        self.conn = Connection(self.events)
        self.conn_state = "offline"
        self.tls_version = None
        self.empty_label = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()
        self._set_state("offline")
        self._show_empty()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self._poll)

    def _build_sidebar(self):
        side = ctk.CTkFrame(self, width=280, corner_radius=0)
        side.grid(row=0, column=0, sticky="nsew")
        side.pack_propagate(False)

        ctk.CTkLabel(
            side, text="TCP Console", font=ctk.CTkFont(size=24, weight="bold"), anchor="w"
        ).pack(fill="x", padx=20, pady=(26, 0))
        ctk.CTkLabel(
            side, text="Secure message service", text_color=MUTED, anchor="w"
        ).pack(fill="x", padx=20, pady=(0, 18))

        ctk.CTkLabel(
            side, text="SERVER", text_color=MUTED,
            font=ctk.CTkFont(size=11, weight="bold"), anchor="w",
        ).pack(fill="x", padx=20, pady=(4, 0))

        self.host = self._field(side, "Host", "localhost")
        self.port = self._field(side, "Port", "12000")

        ctk.CTkLabel(
            side, text="Certificate", text_color=MUTED,
            font=ctk.CTkFont(size=12), anchor="w",
        ).pack(fill="x", padx=20, pady=(10, 0))
        cert_row = ctk.CTkFrame(side, fg_color="transparent")
        cert_row.pack(fill="x", padx=20, pady=(4, 0))
        self.cert = ctk.CTkEntry(cert_row, height=34)
        self.cert.insert(0, os.path.join(APP_DIR, "server.crt"))
        self.cert.pack(side="left", fill="x", expand=True)
        self.browse = ctk.CTkButton(
            cert_row, text="…", width=36, height=34,
            fg_color=("#D1D5DB", "#3A3F47"), hover_color=("#9CA3AF", "#4B5563"),
            text_color=TEXT_IN, command=self._browse_cert,
        )
        self.browse.pack(side="left", padx=(6, 0))

        self.verify = ctk.CTkSwitch(side, text="Verify hostname")
        self.verify.select()
        self.verify.pack(anchor="w", padx=20, pady=(16, 0))

        self.connect_btn = ctk.CTkButton(
            side, text="Connect", height=42, corner_radius=10,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._toggle_connection,
        )
        self.connect_btn.pack(fill="x", padx=20, pady=(20, 0))

        status_row = ctk.CTkFrame(side, fg_color="transparent")
        status_row.pack(fill="x", padx=20, pady=(14, 0))
        self.dot = ctk.CTkLabel(status_row, text="●", font=ctk.CTkFont(size=16))
        self.dot.pack(side="left")
        self.status = ctk.CTkLabel(status_row, text="", anchor="w", wraplength=220)
        self.status.pack(side="left", padx=(6, 0))

        bottom = ctk.CTkFrame(side, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=20, pady=20)
        ctk.CTkButton(
            bottom, text="Clear conversation", height=34, fg_color="transparent",
            border_width=1, border_color=MUTED, text_color=MUTED,
            hover_color=("#E5E7EB", "#2B2F36"), command=self._clear_chat,
        ).pack(fill="x")
        self.theme_switch = ctk.CTkSwitch(
            bottom, text="Dark mode", command=self._toggle_theme
        )
        if ctk.get_appearance_mode() == "Dark":
            self.theme_switch.select()
        self.theme_switch.pack(anchor="w", pady=(14, 0))

    def _field(self, parent, label, value):
        ctk.CTkLabel(
            parent, text=label, text_color=MUTED,
            font=ctk.CTkFont(size=12), anchor="w",
        ).pack(fill="x", padx=20, pady=(10, 0))
        entry = ctk.CTkEntry(parent, height=34)
        entry.insert(0, value)
        entry.pack(fill="x", padx=20, pady=(4, 0))
        return entry

    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(main, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 8))
        ctk.CTkLabel(
            header, text="Conversation", font=ctk.CTkFont(size=20, weight="bold")
        ).pack(side="left")
        self.badge = ctk.CTkLabel(
            header, text="", text_color=MUTED, font=ctk.CTkFont(size=12)
        )
        self.badge.pack(side="right")

        self.chat = ctk.CTkScrollableFrame(main, fg_color="transparent")
        self.chat.grid(row=1, column=0, sticky="nsew", padx=18)

        composer = ctk.CTkFrame(main, corner_radius=16)
        composer.grid(row=2, column=0, sticky="ew", padx=28, pady=(8, 24))
        composer.grid_columnconfigure(0, weight=1)

        self.command = ctk.CTkSegmentedButton(composer, values=COMMANDS)
        self.command.set("upper")
        self.command.grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(14, 8))

        self.entry = ctk.CTkEntry(
            composer, height=42, placeholder_text="Type a message…", border_width=1
        )
        self.entry.grid(row=1, column=0, sticky="ew", padx=(14, 8), pady=(0, 14))
        self.entry.bind("<Return>", lambda _e: self._send())

        self.send_btn = ctk.CTkButton(
            composer, text="Send", width=96, height=42,
            font=ctk.CTkFont(size=14, weight="bold"), command=self._send,
        )
        self.send_btn.grid(row=1, column=1, padx=(0, 14), pady=(0, 14))

    def _show_empty(self):
        self.empty_label = ctk.CTkLabel(
            self.chat,
            text="No messages yet\nConnect to a server, pick a command and send something.",
            text_color=MUTED, justify="center", font=ctk.CTkFont(size=14),
        )
        self.empty_label.pack(pady=120)

    def _drop_empty(self):
        if self.empty_label is not None:
            self.empty_label.destroy()
            self.empty_label = None

    def _scroll_down(self):
        self.after(30, lambda: self.chat._parent_canvas.yview_moveto(1.0))

    def _add_bubble(self, text, outgoing, meta="", error=False):
        self._drop_empty()
        row = ctk.CTkFrame(self.chat, fg_color="transparent")
        row.pack(fill="x", pady=4)
        anchor = "e" if outgoing else "w"
        if outgoing:
            fg, txt = ACCENT, "white"
        elif error:
            fg, txt = BUBBLE_ERR, TEXT_ERR
        else:
            fg, txt = BUBBLE_IN, TEXT_IN
        bubble = ctk.CTkFrame(row, corner_radius=16, fg_color=fg)
        bubble.pack(anchor=anchor, padx=10)
        ctk.CTkLabel(
            bubble, text=text, text_color=txt, wraplength=440, justify="left",
            anchor="w", font=ctk.CTkFont(size=14),
        ).pack(padx=14, pady=10)
        if meta:
            ctk.CTkLabel(
                row, text=meta, text_color=MUTED, font=ctk.CTkFont(size=11)
            ).pack(anchor=anchor, padx=14)
        self._scroll_down()

    def _add_notice(self, text, error=False):
        self._drop_empty()
        ctk.CTkLabel(
            self.chat, text=text, font=ctk.CTkFont(size=12),
            text_color=TEXT_ERR if error else MUTED, wraplength=500,
        ).pack(pady=8)
        self._scroll_down()

    def _clear_chat(self):
        for child in self.chat.winfo_children():
            child.destroy()
        self.empty_label = None
        self._show_empty()

    def _set_state(self, state, tls_version=None):
        self.conn_state = state
        self.tls_version = tls_version if state == "online" else None
        names = {
            "offline": "Not connected",
            "connecting": "Connecting…",
            "online": "Connected",
            "error": "Connection failed",
        }
        self.dot.configure(text_color=STATUS_COLORS[state])
        self.status.configure(text=names[state])
        self.badge.configure(
            text=f"Encrypted · {self.tls_version}" if self.tls_version else "Not encrypted"
        )

        locked = state in ("connecting", "online")
        field_state = "disabled" if locked else "normal"
        for widget in (self.host, self.port, self.cert, self.browse, self.verify):
            widget.configure(state=field_state)

        online = state == "online"
        self.entry.configure(state="normal" if online else "disabled")
        self.send_btn.configure(state="normal" if online else "disabled")

        if online:
            self.connect_btn.configure(
                text="Disconnect", fg_color=DANGER, hover_color=DANGER_HOVER, state="normal"
            )
            self.entry.focus()
        elif state == "connecting":
            self.connect_btn.configure(
                text="Connecting…", fg_color=ACCENT, hover_color=ACCENT_HOVER, state="disabled"
            )
        else:
            self.connect_btn.configure(
                text="Connect", fg_color=ACCENT, hover_color=ACCENT_HOVER, state="normal"
            )

    def _toggle_connection(self):
        if self.conn_state == "online":
            self.conn.close()
            self._set_state("offline")
            self._add_notice("Disconnected")
            return
        if self.conn_state == "connecting":
            return

        host = self.host.get().strip()
        cert = self.cert.get().strip()
        try:
            port = int(self.port.get())
        except ValueError:
            self._add_notice("Port must be a number.", error=True)
            return
        if not host:
            self._add_notice("Please enter a host.", error=True)
            return

        self._set_state("connecting")
        self.conn.open(host, port, cert, bool(self.verify.get()))

    def _send(self):
        if self.conn_state != "online":
            return
        text = self.entry.get()
        if not text.strip():
            return
        cmd = self.command.get()
        self.conn.send(cmd, text)
        self.entry.delete(0, "end")
        self._add_bubble(text, outgoing=True, meta=f"/{cmd}")

    def _browse_cert(self):
        path = filedialog.askopenfilename(
            title="Select server certificate",
            filetypes=[("Certificate", "*.crt *.pem"), ("All files", "*.*")],
        )
        if path:
            self.cert.delete(0, "end")
            self.cert.insert(0, path)

    def _toggle_theme(self):
        ctk.set_appearance_mode("dark" if self.theme_switch.get() else "light")

    def _on_close(self):
        self.conn.close()
        self.destroy()

    def _poll(self):
        try:
            while True:
                session, kind, *args = self.events.get_nowait()
                if session is not self.conn.outbox:
                    continue          
                self._handle(kind, *args)
        except queue.Empty:
            pass
        self.after(50, self._poll)

    def _handle(self, kind, *args):
        if kind == "connected":
            version = args[0]
            self._set_state("online", version)
            self._add_notice(f"Secure connection established ({version})")
        elif kind == "reply":
            _request, reply, ms = args
            if not isinstance(reply, dict):
                reply = {"status": "error", "message": str(reply)}
            meta = f"{ms:.0f} ms round trip"
            if reply.get("status") == "ok":
                self._add_bubble(self._format_result(reply.get("result")), False, meta)
            else:
                self._add_bubble(
                    reply.get("message", "Unknown error"), False, meta, error=True
                )
        elif kind == "disconnected":
            reason, is_error = args
            self.conn.outbox = None
            self._set_state("error" if is_error else "offline")
            self._add_notice(reason, error=is_error)

    @staticmethod
    def _format_result(result):
        if isinstance(result, dict):
            return f"{result.get('characters', '?')} characters · {result.get('words', '?')} words"
        return str(result)


if __name__ == "__main__":
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    App().mainloop()