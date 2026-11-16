import ssl
import time

from server_core import ChatServer, setup_logging

HOST = "0.0.0.0"       
PORT = 12000
CERT_FILE = "server.crt"
KEY_FILE = "server.key"


def main():
    log = setup_logging(console=True)
    server = ChatServer(HOST, PORT, CERT_FILE, KEY_FILE)
    try:
        server.start()
    except FileNotFoundError as e:
        log.error("File not found: %s (run gen_cert.py first?)", e.filename)
        return
    except ssl.SSLError as e:
        log.error("Certificate or key problem: %s", e)
        return
    except OSError as e:
        log.error("Could not listen on port %d: %s", PORT, e)
        return

    try:
        while server.running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print()
    server.stop()


if __name__ == "__main__":
    main()