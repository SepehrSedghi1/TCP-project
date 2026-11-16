import socket
import ssl
import threading

from protocol import send_msg, recv_msg

HOST, PORT = "localhost", 12000
NUM_CLIENTS = 10
MESSAGES_PER_CLIENT = 5

context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile="server.crt")
start_line = threading.Barrier(NUM_CLIENTS)


def worker(i):
    with socket.create_connection((HOST, PORT)) as raw:
        with context.wrap_socket(raw, server_hostname=HOST) as s:
            start_line.wait()
            for j in range(MESSAGES_PER_CLIENT):
                send_msg(s, {"cmd": "upper", "data": f"client {i} message {j}"})
                reply = recv_msg(s)
                print(f"client {i}: {reply['result']}")


threads = [threading.Thread(target=worker, args=(i,)) for i in range(NUM_CLIENTS)]
for t in threads:
    t.start()
for t in threads:
    t.join()
print("Done.")