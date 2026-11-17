"""Klien WebSocket minimal (RFC 6455) berbasis asyncio, hanya stdlib.

Dipakai transport `raw` supaya tidak butuh dependensi tambahan (websockets/aiohttp).
Cukup untuk CDP: teks, ping/pong, close, fragmentasi, ws:// dan wss://.
"""
import asyncio
import base64
import hashlib
import os
import ssl
import struct
import urllib.parse

_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class ConnectionClosed(ConnectionError):
    """Koneksi websocket ditutup (oleh server maupun lokal)."""


class WebSocket:
    def __init__(self, reader, writer):
        self._reader = reader
        self._writer = writer
        self._send_lock = asyncio.Lock()
        self.closed = False
        self.close_code = None

    @classmethod
    async def connect(cls, url, headers=None, timeout=10.0, max_size=None):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("ws", "wss"):
            raise ValueError(f"URL websocket harus ws:// atau wss://, bukan '{url}'")
        secure = parts.scheme == "wss"
        host = parts.hostname
        port = parts.port or (443 if secure else 80)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")

        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ssl.create_default_context() if secure else None,
                                    limit=2 ** 16),
            timeout)
        key = base64.b64encode(os.urandom(16))
        request_headers = {
            "Host": parts.netloc.rsplit("@", 1)[-1],
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Sec-WebSocket-Key": key.decode(),
            "Sec-WebSocket-Version": "13",
        }
        request_headers.update(headers or {})   # tidak mengirim Origin: Chrome menolak origin asing
        head = f"GET {path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in request_headers.items()) + "\r\n"
        try:
            writer.write(head.encode("latin-1"))
            await writer.drain()
            raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout)
        except Exception:
            writer.close()
            raise
        lines = raw.decode("latin-1").split("\r\n")
        status = lines[0]
        reply = {}
        for line in lines[1:]:
            if ":" in line:
                name, _, value = line.partition(":")
                reply[name.strip().lower()] = value.strip()
        if " 101 " not in status + " ":
            writer.close()
            raise ConnectionError(f"Handshake websocket ditolak: {status.strip()}")
        expected = base64.b64encode(hashlib.sha1(key + _GUID).digest()).decode()
        if reply.get("sec-websocket-accept") != expected:
            writer.close()
            raise ConnectionError("Handshake websocket tidak valid (Sec-WebSocket-Accept)")
        ws = cls(reader, writer)
        ws.max_size = max_size
        return ws

    max_size = None

    async def _write_frame(self, opcode, payload=b""):
        if self.closed and opcode != 0x8:
            raise ConnectionClosed("websocket sudah ditutup")
        length = len(payload)
        header = bytearray([0x80 | opcode])
        if length < 126:
            header.append(0x80 | length)
        elif length < 1 << 16:
            header.append(0x80 | 126)
            header += struct.pack("!H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack("!Q", length)
        mask = os.urandom(4)
        header += mask
        if length:
            masked = (int.from_bytes(payload, "big") ^ int.from_bytes((mask * (length // 4 + 1))[:length], "big")
                      ).to_bytes(length, "big")
        else:
            masked = b""
        async with self._send_lock:
            try:
                self._writer.write(bytes(header) + masked)
                await self._writer.drain()
            except (ConnectionError, OSError) as e:
                self.closed = True
                raise ConnectionClosed(str(e)) from e

    async def send(self, text):
        await self._write_frame(0x1, text.encode("utf-8") if isinstance(text, str) else bytes(text))

    async def _read_frame(self):
        try:
            b1, b2 = await self._reader.readexactly(2)
            opcode, fin = b1 & 0x0F, bool(b1 & 0x80)
            length = b2 & 0x7F
            if length == 126:
                (length,) = struct.unpack("!H", await self._reader.readexactly(2))
            elif length == 127:
                (length,) = struct.unpack("!Q", await self._reader.readexactly(8))
            if self.max_size and length > self.max_size:
                raise ConnectionClosed(f"frame terlalu besar ({length} byte)")
            mask = await self._reader.readexactly(4) if b2 & 0x80 else None
            payload = await self._reader.readexactly(length) if length else b""
        except (asyncio.IncompleteReadError, ConnectionError, OSError) as e:
            self.closed = True
            raise ConnectionClosed(f"koneksi terputus: {e.__class__.__name__}") from e
        if mask and payload:
            payload = (int.from_bytes(payload, "big") ^ int.from_bytes((mask * (length // 4 + 1))[:length], "big")
                       ).to_bytes(length, "big")
        return fin, opcode, payload

    async def recv(self):
        """Terima satu pesan utuh (str untuk teks, bytes untuk biner)."""
        chunks, first_opcode = [], None
        while True:
            fin, opcode, payload = await self._read_frame()
            if opcode == 0x8:                      # close
                self.close_code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 1005
                self.closed = True
                try:
                    await self._write_frame(0x8, payload[:2])
                except ConnectionClosed:
                    pass
                self._writer.close()
                raise ConnectionClosed(f"websocket ditutup server (code={self.close_code})")
            if opcode == 0x9:                      # ping -> pong
                await self._write_frame(0xA, payload)
                continue
            if opcode == 0xA:                      # pong
                continue
            if opcode in (0x1, 0x2):
                first_opcode = opcode
                chunks = [payload]
            elif opcode == 0x0:
                chunks.append(payload)
            if fin and first_opcode is not None:
                data = b"".join(chunks)
                return data.decode("utf-8") if first_opcode == 0x1 else data

    async def close(self, code=1000):
        if not self.closed:
            try:
                await self._write_frame(0x8, struct.pack("!H", code))
            except ConnectionClosed:
                pass
        self.closed = True
        try:
            self._writer.close()
            await asyncio.wait_for(self._writer.wait_closed(), 2)
        except Exception:
            pass
