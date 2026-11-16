import logging
import os
import socket
import ssl
import threading
from logging.handlers import RotatingFileHandler

from protocol import send_msg, recv_msg

LOG_FILE = "server.log"
HANDSHAKE_TIMEOUT = 10   
MAX_CLIENTS = 100

COMMANDS = {
    "upper":   lambda s: s.upper(),
    "lower":   lambda s: s.lower(),
    "reverse": lambda s: s[::-1],
    "title":   lambda s: s.title(),
    "count":   lambda s: {"characters": len(s), "words": len(s.split())},
}

log = logging.getLogger("tcpserver")


def setup_logging(console=True):
    if log.handlers:
        return log
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    log.addHandler(file_handler)
    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        log.addHandler(stream)
    log.setLevel(logging.INFO)
    log.propagate = False
    return log


def error(message):
    return {"status": "error", "message": message}


def process(request):
    if not isinstance(request, dict):
        return error("request must be a JSON object")
    cmd = request.get("cmd")
    data = request.get("data")
    if not isinstance(cmd, str) or cmd not in COMMANDS:
        return error(f"unknown command {cmd!r}; available: {', '.join(COMMANDS)}")
    if not isinstance(data, str):
        return error("'data' must be a string")
    return {"status": "ok", "result": COMMANDS[cmd](data)}


def log_request(who, request, response):
    if isinstance(request, dict):
        cmd, data = request.get("cmd"), request.get("data")
    else:
        cmd, data = None, request
    if isinstance(data, str) and len(data) > 40:
        preview = repr(data[:40]) + "..."
    else:
        preview = repr(data)
    level = logging.INFO if response["status"] == "ok" else logging.WARNING
    log.log(level, "%s cmd=%s status=%s data=%s", who, cmd, response["status"], preview)


class ChatServer:

    def __init__(self, host, port, certfile, keyfile, on_event=None):
        self.host = host
        self.port = port
        self.certfile = certfile
        self.keyfile = keyfile
        self._emit = on_event or (lambda *args: None)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._clients = {}        
        self._thread = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=self.certfile, keyfile=self.keyfile)

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name != "nt":    
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.host, self.port))
            listener.listen()
            listener.settimeout(0.5) 
        except OSError:
            listener.close()
            raise

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._accept_loop, args=(listener, context), daemon=True
        )
        self._thread.start()
        log.info("TLS server ready on %s:%d", self.host or "0.0.0.0", self.port)

    def stop(self):
        if not self.running:
            return
        self._stop.set()
        with self._lock:
            records = list(self._clients.values())
        for rec in records:
            rec["closing"] = True
            self._force_close(rec["conn"])
        self._thread.join(timeout=5)
        log.info("Server stopped")

    def kick(self, who):
        with self._lock:
            rec = self._clients.get(who)
        if rec is None:
            return False
        rec["closing"] = True
        log.info("%s disconnected by the operator", who)
        self._force_close(rec["conn"])
        return True

    @staticmethod
    def _force_close(conn):
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            conn.close()
        except OSError:
            pass

    def _accept_loop(self, listener, context):
        try:
            while not self._stop.is_set():
                try:
                    raw, addr = listener.accept()
                except socket.timeout:
                    continue
                except OSError as e:
                    if not self._stop.is_set():
                        log.error("Accepting connections failed: %s", e)
                    break
                threading.Thread(
                    target=self._handle_client, args=(raw, addr, context), daemon=True
                ).start()
        finally:
            listener.close()

    def _handle_client(self, raw, addr, context):
        who = f"{addr[0]}:{addr[1]}"

        with self._lock:
            full = len(self._clients) >= MAX_CLIENTS
        if full:
            log.warning("%s rejected: server is full (%d clients)", who, MAX_CLIENTS)
            raw.close()
            return

        try:
            raw.settimeout(HANDSHAKE_TIMEOUT)
            conn = context.wrap_socket(raw, server_side=True)
            conn.settimeout(None)
        except (ssl.SSLError, OSError) as e:
            log.warning("%s TLS handshake failed: %s", who, e)
            raw.close()
            return

        rec = {"conn": conn, "closing": False, "requests": 0}
        with self._lock:
            self._clients[who] = rec
        if self._stop.is_set():      
            rec["closing"] = True
            self._force_close(conn)

        def closing():
            return rec["closing"] or self._stop.is_set()

        tls = conn.version()
        log.info("%s connected (%s, %s)", who, tls, conn.cipher()[0])
        self._emit("client_connected", who, tls, conn.cipher()[0])
        try:
            with conn:
                while True:
                    try:
                        request = recv_msg(conn)
                    except ValueError as e:      
                        if not closing():
                            log.warning("%s bad message: %s", who, e)
                            send_msg(conn, error(f"bad message: {e}"))
                        break
                    if request is None:         
                        break
                    response = process(request)
                    rec["requests"] += 1
                    cmd = request.get("cmd") if isinstance(request, dict) else None
                    log_request(who, request, response)
                    self._emit("request", who, cmd, response["status"], rec["requests"])
                    send_msg(conn, response)
        except OSError as e:
            if not closing():
                log.error("%s connection error: %s", who, e)
        finally:
            with self._lock:
                self._clients.pop(who, None)
            log.info("%s disconnected after %d request(s)", who, rec["requests"])
            self._emit("client_disconnected", who, rec["requests"])