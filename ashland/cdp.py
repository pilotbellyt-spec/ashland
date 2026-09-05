from __future__ import annotations
import base64
import itertools
import json
import os
import queue
import socket
import struct
import threading
import urllib.request
from contextlib import suppress


FIN = 0x80
MASKED = 0x80
OP_TEXT, OP_CLOSE, OP_PING, OP_PONG = 0x1, 0x8, 0x9, 0xA
LEN_16BIT, LEN_64BIT = 126, 127


class CDPError(Exception):
    pass


class CDP:
    def __init__(self, host: str = "127.0.0.1", port: int = 9222):
        self.host, self.port = host, port
        self.alive = False
        self.on_event = None
        self._sock: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._ids = itertools.count(1)
        self._waiters: dict[int, threading.Event] = {}
        self._replies: dict[int, dict] = {}
        self._events: queue.Queue = queue.Queue()

    def connect(self) -> dict:
        url = f"http://{self.host}:{self.port}/json/version"
        with urllib.request.urlopen(url, timeout=3) as r:
            info = json.loads(r.read())
        path = info["webSocketDebuggerUrl"].split(f"{self.host}:{self.port}", 1)[1]
        sock = socket.create_connection((self.host, self.port), timeout=5)
        sock.sendall(
            f"GET {path} HTTP/1.1\r\nHost: {self.host}:{self.port}\r\n"
            f"Origin: http://{self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {base64.b64encode(os.urandom(16)).decode()}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n".encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = sock.recv(1024)
            if not chunk:
                break
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise CDPError(f"websocket upgrade refused: {head.decode(errors='replace')[:120]}")
        sock.settimeout(None)
        self._sock, self.alive = sock, True
        for loop in (self._read_loop, self._event_loop):
            threading.Thread(target=loop, daemon=True).start()
        return info

    def send(self, method: str, params: dict | None = None, timeout: float = 10.0,
             session_id: str | None = None) -> dict:
        if not self.alive:
            raise CDPError("not connected")
        mid = next(self._ids)
        msg = {"id": mid, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        done = self._waiters[mid] = threading.Event()
        self._frame(json.dumps(msg).encode())
        done.wait(timeout)
        self._waiters.pop(mid, None)
        reply = self._replies.pop(mid, None)
        if reply is None:
            raise CDPError("connection lost" if not self.alive else f"timeout on {method}")
        if "error" in reply:
            raise CDPError(f"{method}: {reply['error']}")
        return reply.get("result", {})

    def close(self) -> None:
        self.alive = False
        if self._sock:
            with suppress(OSError):
                self._sock.close()

    def _frame(self, payload: bytes, opcode: int = OP_TEXT) -> None:
        n, head = len(payload), bytearray([FIN | opcode])
        if n < LEN_16BIT:
            head.append(MASKED | n)
        elif n < 65536:
            head += bytes([MASKED | LEN_16BIT]) + struct.pack(">H", n)
        else:
            head += bytes([MASKED | LEN_64BIT]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        head += mask
        body = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        with self._send_lock:
            self._sock.sendall(bytes(head) + body)

    def _recv(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise CDPError("socket closed")
            buf += chunk
        return buf

    def _read_loop(self) -> None:
        msg = b""
        try:
            while self.alive:
                b0, b1 = self._recv(2)
                length = b1 & 0x7F  # server frames are never masked
                if length == LEN_16BIT:
                    length = struct.unpack(">H", self._recv(2))[0]
                elif length == LEN_64BIT:
                    length = struct.unpack(">Q", self._recv(8))[0]
                payload = self._recv(length) if length else b""
                opcode = b0 & 0x0F
                if opcode == OP_CLOSE:
                    break
                if opcode == OP_PING:
                    self._frame(payload, opcode=OP_PONG)
                    continue
                if opcode == OP_PONG:
                    continue
                msg += payload
                if b0 & FIN:
                    self._deliver(json.loads(msg))
                    msg = b""
        except (OSError, CDPError, ValueError):
            pass
        finally:
            self.alive = False
            for waiter in list(self._waiters.values()):
                waiter.set()

    def _deliver(self, data: dict) -> None:
        mid = data.get("id")
        if mid in self._waiters:
            self._replies[mid] = data
            self._waiters[mid].set()
        elif "method" in data:
            self._events.put(data)

    def _event_loop(self) -> None:
        while self.alive:
            try:
                msg = self._events.get(timeout=0.5)
            except queue.Empty:
                continue
            if not self.on_event:
                continue
            try:
                self.on_event(msg)
            except Exception as e:
                print(f"ashland: event handler failed: {type(e).__name__}: {e}", flush=True)
