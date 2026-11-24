"""pydoll TIRUAN untuk tes: meniru kontrak ConnectionHandler yang terdokumentasi, di atas websocket asli.

- ConnectionHandler(ws_address=...): koneksi dibuka malas saat perintah pertama.
- execute_command(dict, timeout) -> {"id": n, "result": {...}}; error CDP -> CommandFailed.
- register_callback(event, callback, temporary=False) -> int; callback sync atau async, menerima
  {"method": ..., "params": ...}.
Ini BUKAN pydoll asli: hanya memverifikasi adaptor kita terhadap kontrak tersebut.
"""
import asyncio
import json
import sys
import types

from cdp_scraper.browser.ws import ConnectionClosed, WebSocket


class PydollError(Exception):
    pass


class CommandFailed(PydollError):
    pass


class CommandExecutionTimeout(PydollError):
    pass


class WebSocketConnectionClosed(PydollError):
    pass


class ConnectionHandler:
    instances = []
    async_register = False
    raise_on_execute = None

    def __init__(self, connection_port=None, page_id=None, ws_address=None):
        self.ws_address = ws_address
        self._ws = None
        self._next_id = 0
        self._pending = {}
        self._callbacks = {}
        self._cb_id = 0
        self._reader = None
        self.closed = False
        ConnectionHandler.instances.append(self)

    def register_callback(self, event_name, callback, temporary=False):
        self._cb_id += 1
        self._callbacks.setdefault(event_name, []).append((self._cb_id, callback))
        if ConnectionHandler.async_register:
            async def done():
                return self._cb_id
            return done()
        return self._cb_id

    async def _ensure(self):
        if self._ws is None:
            self._ws = await WebSocket.connect(self.ws_address, timeout=10)
            self._reader = asyncio.ensure_future(self._read())

    async def _read(self):
        try:
            while True:
                message = json.loads(await self._ws.recv())
                if "id" in message:
                    future = self._pending.pop(message["id"], None)
                    if future and not future.done():
                        future.set_result(message)
                    continue
                for _id, callback in list(self._callbacks.get(message.get("method"), ())):
                    outcome = callback(message)
                    if asyncio.iscoroutine(outcome):
                        await outcome
        except ConnectionClosed:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(WebSocketConnectionClosed("closed"))

    async def execute_command(self, command, timeout=60):
        if ConnectionHandler.raise_on_execute:
            raise ConnectionHandler.raise_on_execute
        await self._ensure()
        self._next_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[self._next_id] = future
        await self._ws.send(json.dumps({"id": self._next_id, **command}))
        try:
            response = await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            raise CommandExecutionTimeout("timeout") from None
        if "error" in response:
            raise CommandFailed(response["error"].get("message", "error"))
        return {"id": response["id"], "result": response.get("result", {})}

    async def close(self):
        self.closed = True
        if self._reader:
            self._reader.cancel()
        if self._ws:
            await self._ws.close()


def install():
    """Pasang modul `pydoll` palsu di sys.modules. Kembalikan fungsi untuk melepasnya."""
    saved = {name: sys.modules.get(name) for name in ("pydoll", "pydoll.connection")}
    package = types.ModuleType("pydoll")
    connection = types.ModuleType("pydoll.connection")
    connection.ConnectionHandler = ConnectionHandler
    package.connection = connection
    sys.modules["pydoll"], sys.modules["pydoll.connection"] = package, connection
    ConnectionHandler.instances.clear()
    ConnectionHandler.async_register = False
    ConnectionHandler.raise_on_execute = None

    def uninstall():
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    return uninstall
