"""Adaptor koneksi: memakai `ConnectionHandler` milik pydoll sebagai lapisan websocket CDP.

Antarmukanya sama dengan `CDPConnection` (send / on / off / close / closed), jadi `RawPage`
(goto, evaluate, locator, capture response, scroll, ...) bisa dipakai apa adanya di atasnya.
Yang dipakai dari pydoll hanya lapisan koneksinya (page-level websocket), bukan Browser/Tab,
sehingga tidak memanggil domain Browser.* / Target.* yang ditolak browser seperti Anoa.
"""
import inspect

from ..logs import get_logger
from .rawpage import CDPProtocolError
from .ws import ConnectionClosed

# Event yang dipakai RawPage; didaftarkan sekali ke pydoll lalu disebar ke listener internal.
EVENTS = (
    "Network.requestWillBeSent", "Network.responseReceived", "Network.loadingFinished",
    "Network.loadingFailed", "Page.frameNavigated", "Page.navigatedWithinDocument",
    "Page.domContentEventFired", "Page.loadEventFired", "Inspector.targetCrashed",
)

INSTALL_HINT = "pydoll belum terpasang. Install: pip install pydoll-python (Python 3.10+)"


def import_connection_handler():
    try:
        from pydoll.connection import ConnectionHandler
        return ConnectionHandler
    except ImportError as first:
        try:
            from pydoll.connection.connection_handler import ConnectionHandler
            return ConnectionHandler
        except ImportError:
            raise ImportError(INSTALL_HINT) from first


async def _maybe_await(value):
    return await value if inspect.isawaitable(value) else value


class PydollConnection:
    def __init__(self, handler, log=None):
        self.handler = handler
        self.log = log or get_logger()
        self._listeners = {}
        self.closed = False

    @classmethod
    async def open(cls, ws_url, log=None, timeout=10.0):
        handler_cls = import_connection_handler()
        handler = handler_cls(ws_address=ws_url)
        conn = cls(handler, log)
        for event in EVENTS:
            await _maybe_await(handler.register_callback(event, conn._make_callback(event)))
        try:      # koneksi pydoll dibuat saat perintah pertama; paksa sekarang agar gagal lebih awal
            await conn.send("Runtime.evaluate", {"expression": "1"}, timeout=timeout)
        except BaseException:
            await conn.close()
            raise
        return conn

    def _make_callback(self, event):
        def callback(message):
            params = message.get("params", {}) if isinstance(message, dict) else {}
            for handler in list(self._listeners.get(event, ())):
                try:
                    handler(params)
                except Exception as e:
                    self.log.debug(f"pydoll listener {event}: {e}")
        return callback

    def on(self, event, handler):
        self._listeners.setdefault(event, []).append(handler)

    def off(self, event, handler):
        try:
            self._listeners.get(event, []).remove(handler)
        except ValueError:
            pass

    def _mark_closed(self, error):
        if self.closed:
            return
        self.closed = True
        for handler in list(self._listeners.get("__closed__", ())):
            try:
                handler(error)
            except Exception:
                pass

    async def send(self, method, params=None, timeout=30.0):
        if self.closed:
            raise ConnectionClosed("koneksi pydoll sudah ditutup")
        command = {"method": method, "params": params or {}}
        try:
            response = await self.handler.execute_command(command, timeout=timeout)
        except Exception as e:
            kind = type(e).__name__
            if "Timeout" in kind or isinstance(e, TimeoutError):
                raise TimeoutError(f"CDP {method} tidak dijawab dalam {timeout:g} detik") from e
            if "Closed" in kind or "ConnectionLost" in kind:
                error = ConnectionClosed(str(e) or kind)
                self._mark_closed(error)
                raise error from e
            if "CommandFailed" in kind:
                raise CDPProtocolError(method, {"message": str(e)}) from e
            raise
        if isinstance(response, dict):
            if response.get("error"):
                raise CDPProtocolError(method, response["error"])
            return response.get("result", {})
        return {}

    async def close(self):
        if self.closed:
            return
        self.closed = True
        closer = getattr(self.handler, "close", None)
        if closer is not None:
            try:
                await _maybe_await(closer())
            except Exception as e:
                self.log.debug(f"pydoll close: {e}")
