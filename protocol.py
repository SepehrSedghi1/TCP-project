import json
import struct

HEADER = struct.Struct("!I")      
MAX_MSG_SIZE = 1_000_000          


def recv_exact(sock, n, allow_clean_eof=False):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            if allow_clean_eof and not buf:
                return None       
            raise ConnectionError("connection closed mid-message")
        buf.extend(chunk)
    return bytes(buf)


def send_msg(sock, obj):
    payload = json.dumps(obj).encode("utf-8")
    sock.sendall(HEADER.pack(len(payload)) + payload)


def recv_msg(sock):
    header = recv_exact(sock, HEADER.size, allow_clean_eof=True)
    if header is None:
        return None
    (length,) = HEADER.unpack(header)
    if length > MAX_MSG_SIZE:
        raise ValueError(f"message too large ({length} bytes)")
    payload = recv_exact(sock, length)
    return json.loads(payload.decode("utf-8"))   