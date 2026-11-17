"""Tes transport raw CDP: unit (tanpa browser) + integrasi ke Chrome asli (dilewati bila tidak ada)."""
import asyncio
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cdp_scraper import (CDPConfig, CDPSessionManager, Endpoint, Platform, RawCDPTransport,
                         Scraper, create_transport, list_transports, register_transport)
from cdp_scraper.browser.transports import (AutoTransport, PlaywrightTransport, _pick_target,
                                            auth_headers)
from cdp_scraper.browser.ws import ConnectionClosed, WebSocket
from cdp_scraper.errors import BrowserBusy

CHROME = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")


def run(coro):
    return asyncio.run(coro)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ConfigTests(unittest.TestCase):
    def test_defaults_keep_old_behaviour(self):
        cfg = CDPConfig()
        self.assertEqual((cfg.transport, cfg.target, cfg.auth_token, cfg.rewrite_ws_host),
                         ("playwright", "first", None, True))
        self.assertIsInstance(create_transport(cfg), PlaywrightTransport)

    def test_token_not_in_repr(self):
        self.assertNotIn("secret", repr(CDPConfig(auth_token="secret")))

    def test_from_env(self):
        env = {"X_CDP_URL": "http://anoa:9225", "X_CDP_TRANSPORT": "raw", "X_CDP_AUTH_TOKEN": "tok",
               "X_CDP_TARGET": "new"}
        cfg = CDPConfig.from_env("X_", env)
        self.assertEqual((cfg.cdp_url, cfg.transport, cfg.auth_token, cfg.target),
                         ("http://anoa:9225", "raw", "tok", "new"))
        self.assertEqual(auth_headers(cfg), {"Authorization": "Bearer tok"})
        self.assertEqual(CDPConfig.from_env(environ={}).transport, "playwright")

    def test_transport_selection_and_aliases(self):
        for name in ("raw", "websocket", "cdp", "ws"):
            self.assertIsInstance(create_transport(CDPConfig(transport=name)), RawCDPTransport)
        self.assertIsInstance(create_transport(CDPConfig(transport="auto")), AutoTransport)
        with self.assertRaises(ValueError):
            create_transport(CDPConfig(transport="ngawur"))

    def test_custom_transport(self):
        seen = {}

        class Mine(RawCDPTransport):
            name = "mine"

        register_transport("mine", lambda cfg: seen.setdefault("t", Mine(cfg)))
        self.assertIn("mine", list_transports())
        manager = CDPSessionManager(CDPConfig(transport="mine"))
        self.assertIs(manager.transport, seen["t"])

    def test_engine_labels(self):
        self.assertEqual(CDPSessionManager(CDPConfig(transport="raw")).engine, "raw-cdp")
        self.assertIsNone(CDPSessionManager(CDPConfig()).engine)

    def test_pick_target(self):
        targets = [{"type": "service_worker", "id": "s", "webSocketDebuggerUrl": "ws://x/s"},
                   {"type": "page", "id": "a", "url": "https://a.test", "title": "A", "webSocketDebuggerUrl": "ws://x/a"},
                   {"type": "page", "id": "b", "url": "https://b.test", "title": "B", "webSocketDebuggerUrl": "ws://x/b"}]
        self.assertEqual(_pick_target(targets, "first")["id"], "a")
        self.assertEqual(_pick_target(targets, "b.test")["id"], "b")
        self.assertEqual(_pick_target(targets, "b")["id"], "b")
        with self.assertRaises(LookupError):
            _pick_target(targets, "zzz")
        with self.assertRaises(LookupError):
            _pick_target([], "first")


class AutoFallbackTests(unittest.TestCase):
    def test_should_fallback(self):
        yes = RuntimeError("BrowserType.connect_over_cdp: Protocol error (Browser.setDownloadBehavior): "
                           "Browser context management is not supported.")
        self.assertTrue(AutoTransport._should_fallback(yes))
        self.assertTrue(AutoTransport._should_fallback(ImportError("no playwright")))
        self.assertFalse(AutoTransport._should_fallback(ConnectionRefusedError("Connection refused")))


class WebSocketTests(unittest.TestCase):
    def test_bad_scheme(self):
        with self.assertRaises(ValueError):
            run(WebSocket.connect("http://localhost:1"))

    def test_handshake_rejected(self):
        async def main():
            async def handler(reader, writer):
                await reader.readuntil(b"\r\n\r\n")
                writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                await writer.drain()
                writer.close()
            server = await asyncio.start_server(handler, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            try:
                with self.assertRaises(ConnectionError) as ctx:
                    await WebSocket.connect(f"ws://127.0.0.1:{port}/x", timeout=3)
                self.assertIn("403", str(ctx.exception))
            finally:
                server.close()
        run(main())

    def test_sends_auth_header(self):
        captured = {}

        async def main():
            async def handler(reader, writer):
                captured["head"] = (await reader.readuntil(b"\r\n\r\n")).decode()
                writer.close()
            server = await asyncio.start_server(handler, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            try:
                with self.assertRaises(Exception):
                    await WebSocket.connect(f"ws://127.0.0.1:{port}/p?q=1", headers={"Authorization": "Bearer t"},
                                            timeout=3)
            finally:
                server.close()
        run(main())
        self.assertIn("GET /p?q=1 HTTP/1.1", captured["head"])
        self.assertIn("Authorization: Bearer t", captured["head"])
        self.assertNotIn("Origin", captured["head"])


# ---- integrasi: Chrome asli + situs lokal --------------------------------------------------------

class _Site(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/list"):
            page = int(self.path.split("page=")[1]) if "page=" in self.path else 0
            body = json.dumps({"items": [{"id": page * 10 + i} for i in range(10)],
                               "has_more": 1 if page < 3 else 0}).encode()
            ctype = "application/json"
        else:
            body = b"""<html><head><title>Uji Raw</title></head><body style="height:6000px">
            <script>
              let page = 0, busy = false;
              async function more() { if (busy) return; busy = true;
                await fetch('/api/list?page=' + (page++)); busy = false; }
              more();
              window.addEventListener('scroll', more);
              window.addEventListener('wheel', more);
            </script></body></html>"""
            ctype = "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@unittest.skipUnless(CHROME, "Chrome tidak terpasang")
class RealChromeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
        threading.Thread(target=cls.site.serve_forever, daemon=True).start()
        cls.site_url = f"http://127.0.0.1:{cls.site.server_address[1]}/"
        cls.port = free_port()
        cls.profile = tempfile.mkdtemp()
        cls.chrome = subprocess.Popen(
            [CHROME, "--headless=new", "--no-sandbox", "--disable-gpu", f"--remote-debugging-port={cls.port}",
             "--remote-allow-origins=*", f"--user-data-dir={cls.profile}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/json/version", timeout=1).read()
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("Chrome tidak mau start")
        cls.cdp_url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.chrome.terminate()
        cls.chrome.wait(10)
        cls.site.shutdown()
        shutil.rmtree(cls.profile, ignore_errors=True)

    def manager(self, **kwargs):
        kwargs.setdefault("transport", "raw")
        return CDPSessionManager(CDPConfig(cdp_url=self.cdp_url, debug_screenshots=False, **kwargs))

    def platform(self):
        return Platform("lokal", endpoints=[Endpoint(
            "list", url=self.site_url, api_match="/api/list", parser=lambda d: d["items"], key="id",
            end=lambda d: not d.get("has_more"), initial_sleep=0.5, max_wait=2, limit=25, max_scrolls=6)])

    def test_page_api(self):
        async def main():
            async with self.manager().session() as page:
                await page.goto(self.site_url)
                self.assertEqual(await page.title(), "Uji Raw")
                self.assertEqual(await page.evaluate("(a) => a.x * 2", {"x": 21}), 42)
                self.assertEqual(await page.evaluate("document.title"), "Uji Raw")
                self.assertTrue(page.url.startswith(self.site_url))
                self.assertGreater(page.viewport_size["width"], 0)
                await page.wait_for_selector("body")
                with self.assertRaises(TimeoutError):
                    await page.wait_for_selector("#tidak-ada", timeout=300)
                with self.assertRaises(RuntimeError):
                    await page.evaluate("() => { throw new Error('boom') }")
                shot = os.path.join(tempfile.gettempdir(), "raw_shot.png")
                await page.screenshot(path=shot)
                self.assertGreater(os.path.getsize(shot), 100)
                await page.keyboard.press("PageDown")
                await page.mouse.move(100, 100)
                await page.mouse.wheel(0, 500)
                self.assertGreater(await page.evaluate("() => window.scrollY"), 0)
        run(main())

    def test_goto_status_and_response_events(self):
        async def main():
            seen = []

            async def on_response(res):
                if "/api/list" in res.url:
                    seen.append((res.status, res.request.method, res.request.resource_type, (await res.json())["items"][0]))

            async with self.manager().session() as page:
                page.on("response", on_response)
                resp = await page.goto(self.site_url)
                self.assertEqual(resp.status, 200)
                await asyncio.sleep(0.8)
                page.remove_listener("response", on_response)
            return seen
        seen = run(main())
        self.assertEqual(seen[0][:3], (200, "GET", "fetch"))

    def test_scraper_end_to_end_raw(self):
        result = run(Scraper(self.platform(), manager=self.manager()).run("list", limit=25))
        self.assertEqual(result.status, "success")
        self.assertGreaterEqual(result.count, 25)
        self.assertEqual(result.diagnostics["engine"], "raw-cdp (websocket)")

    def test_direct_websocket_url(self):
        targets = json.loads(urllib.request.urlopen(f"{self.cdp_url}/json").read())
        ws_url = next(t for t in targets if t["type"] == "page")["webSocketDebuggerUrl"]
        manager = CDPSessionManager(CDPConfig(cdp_url=ws_url, transport="websocket", debug_screenshots=False))

        async def main():
            async with manager.session() as page:
                await page.goto(self.site_url)
                return await page.title()
        self.assertEqual(run(main()), "Uji Raw")

    def test_new_tab_is_closed_afterwards(self):
        def tabs():
            return [t for t in json.loads(urllib.request.urlopen(f"{self.cdp_url}/json").read()) if t["type"] == "page"]
        before = len(tabs())

        async def main():
            async with self.manager(target="new").session() as page:
                self.assertEqual(len(tabs()), before + 1)
                await page.goto(self.site_url)
        run(main())
        time.sleep(0.5)
        self.assertEqual(len(tabs()), before)

    def test_shared_tab_is_exclusive(self):
        manager = self.manager(lock_timeout=0.6, max_sessions=2)

        async def main():
            async with manager.session():
                with self.assertRaises(BrowserBusy):
                    async with manager.session():
                        pass
        run(main())

    def test_rewrite_ws_host_fixes_127_in_url(self):
        # URL ws asli Chrome memakai 127.0.0.1:port; dengan cdp_url 'localhost' harus tetap lewat host cdp_url
        from cdp_scraper.browser.transports import resolve_page_target
        from cdp_scraper.logs import get_logger
        cfg = CDPConfig(cdp_url=f"http://localhost:{self.port}", transport="raw")
        ws_url, _id, owns = resolve_page_target(cfg, get_logger())
        self.assertTrue(ws_url.startswith(f"ws://localhost:{self.port}/devtools/page/"))
        self.assertFalse(owns)

    def test_health_deep_raw(self):
        report = run(self.manager().health(deep=True, tabs=True))
        self.assertTrue(report["connected"])
        self.assertTrue(report["deep"]["connected"])
        self.assertEqual(report["engine"], "raw-cdp")

    def test_auto_falls_back_to_raw(self):
        class _PW:
            class chromium:
                @staticmethod
                async def connect_over_cdp(url, **kw):
                    raise RuntimeError("Protocol error (Browser.setDownloadBehavior): "
                                       "Browser context management is not supported.")

        class _Engine:
            async def __aenter__(self):
                return _PW

            async def __aexit__(self, *a):
                return False

        manager = CDPSessionManager(CDPConfig(cdp_url=self.cdp_url, transport="auto", debug_screenshots=False),
                                    engine_factory=lambda: _Engine())

        async def main():
            out = []
            for _ in range(2):          # panggilan kedua langsung ke raw (keputusan di-cache)
                async with manager.session() as page:
                    await page.goto(self.site_url)
                    out.append(await page.title())
            return out
        self.assertEqual(run(main()), ["Uji Raw", "Uji Raw"])
        self.assertEqual(manager.engine, "raw-cdp")

    def test_connection_refused_is_clear(self):
        manager = CDPSessionManager(CDPConfig(cdp_url=f"http://127.0.0.1:{free_port()}", transport="raw"))

        async def main():
            async with manager.session():
                pass
        with self.assertRaises(Exception) as ctx:
            run(main())
        self.assertIn("refused", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
