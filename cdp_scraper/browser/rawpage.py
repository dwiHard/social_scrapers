"""Page CDP mentah: meniru subset API Playwright `Page` yang dipakai cdp_scraper.

Cocok untuk browser yang CDP-nya terbatas (mis. Qt WebEngine / Anoa) dan menolak
`Browser.*` / `Target.*` yang dipanggil Playwright. Hanya memakai domain level-halaman:
Page, Runtime, Network, Input, Emulation, Inspector.
"""
import asyncio
import base64
import json
import time
from types import SimpleNamespace

from ..logs import get_logger
from .ws import ConnectionClosed, WebSocket


class CDPProtocolError(RuntimeError):
    """Server CDP membalas dengan error untuk sebuah method."""

    def __init__(self, method, error):
        self.method = method
        self.code = error.get("code") if isinstance(error, dict) else None
        message = error.get("message") if isinstance(error, dict) else str(error)
        super().__init__(f"{method}: {message}")


class CDPConnection:
    """Satu websocket CDP: kirim command (id -> future) dan sebar event ke listener."""

    def __init__(self, ws, log=None):
        self.ws = ws
        self.log = log or get_logger()
        self._next_id = 0
        self._pending = {}
        self._listeners = {}
        self._task = None
        self.closed = False

    @classmethod
    async def open(cls, ws_url, headers=None, timeout=10.0, log=None):
        ws = await WebSocket.connect(ws_url, headers=headers, timeout=timeout)
        conn = cls(ws, log)
        conn._task = asyncio.ensure_future(conn._reader())
        return conn

    def on(self, event, handler):
        self._listeners.setdefault(event, []).append(handler)

    def off(self, event, handler):
        try:
            self._listeners.get(event, []).remove(handler)
        except ValueError:
            pass

    async def _reader(self):
        try:
            while True:
                message = json.loads(await self.ws.recv())
                msg_id = message.get("id")
                if msg_id is not None:
                    future = self._pending.pop(msg_id, None)
                    if future and not future.done():
                        if "error" in message:
                            future.set_exception(CDPProtocolError(future.method, message["error"]))
                        else:
                            future.set_result(message.get("result", {}))
                    continue
                for handler in list(self._listeners.get(message.get("method"), ())):
                    try:
                        handler(message.get("params", {}))
                    except Exception as e:
                        self.log.debug(f"CDP listener {message.get('method')}: {e}")
        except asyncio.CancelledError:
            raise
        except Exception as e:      # koneksi putus / pesan rusak
            self._fail_all(ConnectionClosed(str(e) or e.__class__.__name__))
        else:
            self._fail_all(ConnectionClosed("koneksi ditutup"))

    def _fail_all(self, error):
        self.closed = True
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()
        for handler in list(self._listeners.get("__closed__", ())):
            try:
                handler(error)
            except Exception:
                pass

    async def send(self, method, params=None, timeout=30.0):
        if self.closed:
            raise ConnectionClosed("koneksi CDP sudah ditutup")
        self._next_id += 1
        msg_id = self._next_id
        future = asyncio.get_running_loop().create_future()
        future.method = method
        self._pending[msg_id] = future
        try:
            await self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"CDP {method} tidak dijawab dalam {timeout:g} detik") from None
        finally:
            self._pending.pop(msg_id, None)

    async def close(self):
        self.closed = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except BaseException:
                pass
        await self.ws.close()


class RawResponse:
    """Mirip playwright Response: .url .status .request.method/.resource_type, json()/text()/body()."""

    def __init__(self, page, request_id, url, status, method, resource_type, headers):
        self._page = page
        self._request_id = request_id
        self.url = url
        self.status = status
        self.headers = headers
        self.request = SimpleNamespace(method=method, resource_type=resource_type)

    async def body(self):
        result = await self._page.conn.send("Network.getResponseBody", {"requestId": self._request_id})
        data = result.get("body", "")
        return base64.b64decode(data) if result.get("base64Encoded") else data.encode("utf-8")

    async def text(self):
        return (await self.body()).decode("utf-8", "replace")

    async def json(self):
        return json.loads(await self.text())


_KEYS = {
    "PageDown": (34, "PageDown"), "PageUp": (33, "PageUp"), "End": (35, "End"), "Home": (36, "Home"),
    "ArrowDown": (40, "ArrowDown"), "ArrowUp": (38, "ArrowUp"), "Enter": (13, "Enter"),
    "Escape": (27, "Escape"), "Tab": (9, "Tab"), "Space": (32, "Space"), " ": (32, "Space"),
}
_KEY_SCROLL_FALLBACK = {
    "PageDown": "window.scrollBy(0, window.innerHeight * 0.9)", "ArrowDown": "window.scrollBy(0, 120)",
    "PageUp": "window.scrollBy(0, -window.innerHeight * 0.9)", "ArrowUp": "window.scrollBy(0, -120)",
    "End": "window.scrollTo(0, document.documentElement.scrollHeight)", "Home": "window.scrollTo(0, 0)",
    "Space": "window.scrollBy(0, window.innerHeight * 0.9)", " ": "window.scrollBy(0, window.innerHeight * 0.9)",
}


class _Keyboard:
    def __init__(self, page):
        self._page = page

    async def press(self, key):
        page = self._page
        code, name = _KEYS.get(key, (0, key))
        params = {"key": " " if key == "Space" else key, "code": name if key in _KEYS else key,
                  "windowsVirtualKeyCode": code, "nativeVirtualKeyCode": code}
        if len(key) == 1 or key == "Space":
            params["text"] = " " if key == "Space" else key
        try:
            await page.conn.send("Input.dispatchKeyEvent", {**params, "type": "keyDown" if "text" in params else "rawKeyDown"})
            await page.conn.send("Input.dispatchKeyEvent", {**params, "type": "keyUp"})
        except CDPProtocolError:
            script = _KEY_SCROLL_FALLBACK.get(key)     # browser tanpa domain Input: scroll lewat JS
            if script is None:
                raise
            await page.evaluate(f"() => {{ {script} }}")


class _Mouse:
    def __init__(self, page):
        self._page = page
        self._pos = (0.0, 0.0)

    async def move(self, x, y):
        self._pos = (x, y)
        try:
            await self._page.conn.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        except CDPProtocolError:
            pass

    async def wheel(self, delta_x, delta_y):
        x, y = self._pos
        try:
            await self._page.conn.send("Input.dispatchMouseEvent", {
                "type": "mouseWheel", "x": x, "y": y, "deltaX": delta_x, "deltaY": delta_y})
        except CDPProtocolError:
            await self._page.evaluate("(d) => window.scrollBy(d[0], d[1])", [delta_x, delta_y])


_EVAL_WRAPPER = """(async () => {{
    const __f = ({expression});
    return typeof __f === 'function' ? await __f({arg}) : await __f;
}})()"""


class RawPage:
    """Satu tab yang dikendalikan lewat CDP mentah (satu websocket level-halaman)."""

    RESPONSE_WAIT = 15.0      # tunggu loadingFinished sebelum body dibaca

    def __init__(self, conn, log=None, target_id=None, owns_target=False, closer=None):
        self.conn = conn
        self.log = log or get_logger()
        self.target_id = target_id
        self.keyboard = _Keyboard(self)
        self.mouse = _Mouse(self)
        self.viewport_size = None
        self._url = "about:blank"
        self._handlers = {"response": [], "crash": []}
        self._requests = {}
        self._finished = {}
        self._tasks = set()
        self._waiters = set()
        self._main_frame = None
        self._doc_status = None
        self._owns_target = owns_target
        self._closer = closer
        self.crashed = False
        self.closed = False
        for event, method in (("Network.requestWillBeSent", self._on_request),
                              ("Network.responseReceived", self._on_response),
                              ("Network.loadingFinished", self._on_finished),
                              ("Network.loadingFailed", self._on_failed),
                              ("Page.frameNavigated", self._on_frame),
                              ("Page.navigatedWithinDocument", self._on_same_doc),
                              ("Inspector.targetCrashed", self._on_crash),
                              ("__closed__", self._on_closed)):
            conn.on(event, method)

    # ---- setup -------------------------------------------------------------------------

    async def setup(self, timezone=None, bring_to_front=True):
        """Aktifkan domain yang dibutuhkan. Domain yang tidak didukung hanya jadi peringatan."""
        for method, required in (("Page.enable", True), ("Runtime.enable", True),
                                 ("Network.enable", False), ("Inspector.enable", False)):
            try:
                await self.conn.send(method)
            except CDPProtocolError as e:
                if required:
                    raise
                self.log.debug(f"{method} tidak didukung: {e}")
        if timezone:
            try:
                await self.conn.send("Emulation.setTimezoneOverride", {"timezoneId": timezone})
            except CDPProtocolError as e:
                self.log.debug(f"timezone override: {e}")
        if bring_to_front:
            await self.bring_to_front()
        try:
            tree = await self.conn.send("Page.getFrameTree")
            self._main_frame = tree.get("frameTree", {}).get("frame", {}).get("id")
        except CDPProtocolError as e:
            self.log.debug(f"getFrameTree: {e}")
        info = await self.evaluate("() => ({url: location.href, w: innerWidth, h: innerHeight})") or {}
        self._url = info.get("url") or self._url
        self.viewport_size = {"width": info.get("w") or 1280, "height": info.get("h") or 800}
        return self

    # ---- events ------------------------------------------------------------------------

    def on(self, event, handler):
        self._handlers.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        try:
            self._handlers[event].remove(handler)
        except (KeyError, ValueError):
            pass

    def _spawn(self, coro):
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _on_request(self, params):
        if len(self._requests) > 2000:
            self._requests.clear()
        self._requests[params["requestId"]] = params.get("request", {}).get("method", "GET")

    def _on_response(self, params):
        response, request_id = params.get("response", {}), params.get("requestId")
        rtype = (params.get("type") or "").lower()
        if rtype == "document" and (self._main_frame is None or params.get("frameId") == self._main_frame):
            self._doc_status = response.get("status")
        if not self._handlers["response"]:
            return
        self._finished[request_id] = asyncio.get_running_loop().create_future()
        self._spawn(self._dispatch_response(request_id, response, rtype))

    async def _dispatch_response(self, request_id, response, rtype):
        future = self._finished.get(request_id)
        try:
            await asyncio.wait_for(asyncio.shield(future), self.RESPONSE_WAIT)
        except Exception:
            pass
        finally:
            self._finished.pop(request_id, None)
        method = self._requests.pop(request_id, "GET")
        res = RawResponse(self, request_id, response.get("url", ""), int(response.get("status", 0)),
                          method, rtype, response.get("headers", {}))
        for handler in list(self._handlers["response"]):
            try:
                outcome = handler(res)
                if asyncio.iscoroutine(outcome):
                    await outcome
            except Exception as e:
                self.log.debug(f"response handler: {e}")

    def _on_finished(self, params):
        future = self._finished.get(params.get("requestId"))
        if future and not future.done():
            future.set_result(True)

    def _on_failed(self, params):
        future = self._finished.get(params.get("requestId"))
        if future and not future.done():
            future.set_result(False)

    def _on_frame(self, params):
        frame = params.get("frame", {})
        if not frame.get("parentId"):
            self._main_frame = frame.get("id")
            self._url = frame.get("url") or self._url

    def _on_same_doc(self, params):
        self._url = params.get("url") or self._url

    def _on_crash(self, _params):
        self.crashed = True
        self._fail_waiters(RuntimeError("Page crashed (Target crashed)"))
        for handler in list(self._handlers["crash"]):
            try:
                handler(self)
            except Exception:
                pass

    def _on_closed(self, error):
        self._fail_waiters(error)

    def _fail_waiters(self, error):
        for future in list(self._waiters):
            if not future.done():
                future.set_exception(error)

    # ---- API ala Playwright ------------------------------------------------------------

    @property
    def url(self):
        return self._url

    async def goto(self, url, wait_until="domcontentloaded", timeout=30000, **_ignored):
        loop = asyncio.get_running_loop()
        events = {"domcontentloaded": "Page.domContentEventFired", "load": "Page.loadEventFired",
                  "networkidle": "Page.loadEventFired", "commit": None}
        event = events.get(wait_until, "Page.domContentEventFired")
        waiter = loop.create_future()
        self._waiters.add(waiter)
        handler = (lambda _p: waiter.done() or waiter.set_result(True))
        if event:
            self.conn.on(event, handler)
        self._doc_status = None
        try:
            result = await self.conn.send("Page.navigate", {"url": url}, timeout=timeout / 1000)
            if result.get("errorText"):
                raise RuntimeError(f"{result['errorText']} at {url}")
            if event:
                try:
                    await asyncio.wait_for(waiter, timeout / 1000)
                except asyncio.TimeoutError:
                    raise TimeoutError(f"Timeout {timeout}ms saat membuka {url} ({wait_until})") from None
            await asyncio.sleep(0.05)            # beri waktu Network.responseReceived tiba
            return SimpleNamespace(status=self._doc_status, url=self._url, ok=bool(
                self._doc_status and self._doc_status < 400))
        finally:
            self._waiters.discard(waiter)
            if event:
                self.conn.off(event, handler)

    async def evaluate(self, expression, arg=None):
        """Seperti Playwright: ekspresi biasa atau fungsi `(a) => ...` yang dipanggil dengan arg."""
        source = _EVAL_WRAPPER.format(expression=expression,
                                      arg="undefined" if arg is None else json.dumps(arg))
        result = await self.conn.send("Runtime.evaluate", {
            "expression": source, "returnByValue": True, "awaitPromise": True})
        if result.get("exceptionDetails"):
            details = result["exceptionDetails"]
            text = (details.get("exception") or {}).get("description") or details.get("text") or "evaluate error"
            raise RuntimeError(text)
        return result.get("result", {}).get("value")

    async def title(self):
        return await self.evaluate("() => document.title")

    async def inner_text(self, selector, timeout=30000):
        deadline = time.monotonic() + timeout / 1000
        while True:
            text = await self.evaluate("(s) => { const e = document.querySelector(s); return e ? e.innerText : null; }",
                                       selector)
            if text is not None:
                return text
            if time.monotonic() > deadline:
                raise TimeoutError(f"Elemen '{selector}' tidak ditemukan")
            await asyncio.sleep(0.1)

    async def wait_for_selector(self, selector, state="attached", timeout=30000):
        script = {"attached": "(s) => !!document.querySelector(s)",
                  "detached": "(s) => !document.querySelector(s)",
                  "visible": "(s) => { const e = document.querySelector(s); "
                             "return !!e && !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }",
                  "hidden": "(s) => { const e = document.querySelector(s); "
                            "return !e || !(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }"
                  }.get(state, "(s) => !!document.querySelector(s)")
        deadline = time.monotonic() + timeout / 1000
        while not await self.evaluate(script, selector):
            if time.monotonic() > deadline:
                raise TimeoutError(f"Timeout {timeout}ms menunggu '{selector}' ({state})")
            await asyncio.sleep(0.1)

    async def screenshot(self, path=None, timeout=30000, **_ignored):
        result = await self.conn.send("Page.captureScreenshot", {"format": "png"}, timeout=timeout / 1000)
        data = base64.b64decode(result["data"])
        if path:
            with open(path, "wb") as handle:
                handle.write(data)
        return data

    async def bring_to_front(self):
        try:
            await self.conn.send("Page.bringToFront")
        except CDPProtocolError as e:
            self.log.debug(f"bringToFront: {e}")

    async def close(self):
        if self.closed:
            return
        self.closed = True
        for task in list(self._tasks):
            task.cancel()
        if self._owns_target and self._closer:
            try:
                await self._closer()
            except Exception as e:
                self.log.debug(f"tutup target: {e}")
        await self.conn.close()
