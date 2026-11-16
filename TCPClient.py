import socket
import ssl

from protocol import send_msg, recv_msg

SERVER_NAME = "localhost"
SERVER_PORT = 12000
CERT_FILE = "server.crt"

HELP = "Type text to uppercase it, or /upper /lower /reverse /title /count <text>. /quit exits."


def parse_input(line):
    if line.startswith("/"):
        cmd, _, data = line[1:].partition(" ")
        return cmd.lower(), data
    return "upper", line


def connect():
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=CERT_FILE)
    raw = socket.create_connection((SERVER_NAME, SERVER_PORT), timeout=10)
    client = context.wrap_socket(raw, server_hostname=SERVER_NAME)
    client.settimeout(None)
    return client


def main():
    try:
        client = connect()
    except ssl.SSLCertVerificationError as e:
        print(f"Certificate check failed: {e.verify_message}")
        return
    except ConnectionRefusedError:
        print("Could not connect: is the server running?")
        return
    except FileNotFoundError:
        print(f"Could not find {CERT_FILE}. Put it next to this script.")
        return

    with client:
        print(f"Connected securely ({client.version()}).", HELP)
        while True:
            line = input("> ")
            if line.strip().lower() == "/quit":
                break
            cmd, data = parse_input(line)
            send_msg(client, {"cmd": cmd, "data": data})
            reply = recv_msg(client)
            if reply is None:
                print("Server closed the connection.")
                break
            if reply["status"] == "ok":
                print("From Server:", reply["result"])
            else:
                print("Error:", reply["message"])


if __name__ == "__main__":
    main()