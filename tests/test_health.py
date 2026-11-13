import asyncio
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from cdp_scraper import CDPConfig, CDPSessionManager, Scraper, check_cdp
from cdp_scraper.health import http_base
from tests.fakes import FakeContext, fake_engine, run

VERSION = {"Browser": "Chrome/140.0.7339.0", "Protocol-Version": "1.3",
           "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/abc"}
PAGES = [{"type": "page", "id": "1"}, {"type": "page", "id": "2"}, {"type": "service_worker", "id": "3"}]


class FakeCDPServer:
    """Server HTTP kecil yang meniru endpoint /json/version dan /json/list milik Chrome."""

    def __init__(self, mode="ok"):
        outer = self
        self.mode = mode

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if outer.mode == "slow":
                    time.sleep(1.2)
                if outer.mode == "host":
                    body = b"Host header is specified and is not an IP address or localhost."
                    self.send_response(500)
                elif outer.mode == "html":
                    body = b"<html>bukan chrome</html>"
                    self.send_response(200)
                elif outer.mode == "list_json":
                    body = b"[1, 2]"
                    self.send_response(200)
                else:
                    payload = PAGES if self.path.startswith("/json/list") else VERSION
                    body = json.dumps(payload).encode()
                    self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def closed_port_url():
    server = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    url = f"http://127.0.0.1:{server.server_port}"
    server.server_close()
    return url


class CheckCdpTests(unittest.TestCase):
    def test_connected(self):
        server = FakeCDPServer()
        try:
            result = check_cdp(server.url, tabs=True)
        finally:
            server.close()
        self.assertTrue(result["connected"])
        self.assertEqual((result["browser"], result["protocol_version"], result["tabs"]), ("Chrome/140.0.7339.0", "1.3", 2))
        self.assertIsNone(result["error"])
        self.assertGreaterEqual(result["latency_ms"], 0)
        self.assertNotIn("webSocketDebuggerUrl", json.dumps(result))

    def test_connection_refused(self):
        result = check_cdp(closed_port_url(), timeout=1)
        self.assertFalse(result["connected"])
        self.assertIn("refused", result["error"].lower())
        self.assertIsNone(result["browser"])
        self.assertIsNone(result["latency_ms"])

    def test_timeout(self):
        server = FakeCDPServer("slow")
        try:
            started = time.time()
            result = check_cdp(server.url, timeout=0.3)
            elapsed = time.time() - started
        finally:
            server.close()
        self.assertFalse(result["connected"])
        self.assertIn("timeout", result["error"])
        self.assertLess(elapsed, 1.0)

    def test_bad_responses(self):
        for mode, expected in (("host", "HTTP 500: Host header"), ("html", "bukan JSON"), ("list_json", "bukan JSON")):
            server = FakeCDPServer(mode)
            try:
                result = check_cdp(server.url)
            finally:
                server.close()
            self.assertFalse(result["connected"], mode)
            self.assertIn(expected, result["error"], mode)

    def test_url_forms(self):
        self.assertEqual(http_base("http://localhost:9222"), "http://localhost:9222")
        self.assertEqual(http_base("ws://localhost:9222/devtools/browser/x"), "http://localhost:9222")
        self.assertEqual(http_base("wss://host:9333/abc"), "https://host:9333")
        self.assertEqual(http_base("localhost:9222"), "http://localhost:9222")


class ManagerHealthTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeCDPServer()
        self.addCleanup(self.server.close)

    def manager(self, url=None, **kwargs):
        engine = kwargs.pop("engine", None) or fake_engine(FakeContext([]))
        return CDPSessionManager(CDPConfig(cdp_url=url or self.server.url, max_sessions=2, **kwargs), engine_factory=engine)

    def test_health_reports_connection_and_sessions(self):
        manager = self.manager()
        report = run(manager.health(tabs=True))
        self.assertTrue(report["connected"])
        self.assertEqual(report["sessions"], {"active": 0, "max": 2, "busy": False})
        self.assertEqual(report["engine"], "custom")
        self.assertEqual(report["tabs"], 2)
        self.assertNotIn("deep", report)

    def test_health_counts_active_sessions(self):
        manager = self.manager()

        async def main():
            async with manager.session():
                inside = await manager.health()
                async with manager.session():
                    full = await manager.health()
            return inside, full, await manager.health()

        inside, full, after = run(main())
        self.assertEqual((inside["sessions"]["active"], inside["sessions"]["busy"]), (1, False))
        self.assertEqual((full["sessions"]["active"], full["sessions"]["busy"]), (2, True))
        self.assertEqual(after["sessions"]["active"], 0)

    def test_health_when_cdp_down(self):
        report = run(self.manager(url=closed_port_url()).health(timeout=1))
        self.assertFalse(report["connected"])
        self.assertIn("refused", report["error"].lower())
        self.assertEqual(report["sessions"]["max"], 2)

    def test_health_sync_matches(self):
        report = self.manager().health_sync()
        self.assertTrue(report["connected"])
        self.assertEqual(report["sessions"]["active"], 0)

    def test_deep_check_ok_and_no_tab_opened(self):
        ctx = FakeContext([])
        manager = self.manager(engine=fake_engine(ctx))
        report = run(manager.health(deep=True))
        self.assertTrue(report["connected"])
        self.assertEqual(report["deep"], {"connected": True, "contexts": 1, "error": None})
        self.assertEqual(ctx.pages_made, [])

    def test_deep_check_failure_marks_disconnected(self):
        class _PW:
            class chromium:
                @staticmethod
                async def connect_over_cdp(url):
                    raise RuntimeError("browser menolak koneksi")

        class _Engine:
            async def __aenter__(self):
                return _PW

            async def __aexit__(self, *a):
                return False

        report = run(self.manager(engine=lambda: _Engine()).health(deep=True))
        self.assertFalse(report["connected"])
        self.assertEqual(report["deep"]["error"], "browser menolak koneksi")
        self.assertEqual(report["error"], "browser menolak koneksi")

    def test_deep_check_timeout(self):
        class _PW:
            class chromium:
                @staticmethod
                async def connect_over_cdp(url):
                    await asyncio.sleep(5)

        class _Engine:
            async def __aenter__(self):
                return _PW

            async def __aexit__(self, *a):
                return False

        report = run(self.manager(engine=lambda: _Engine()).health(deep=True, timeout=0.2))
        self.assertFalse(report["connected"])
        self.assertIn("timeout", report["deep"]["error"])

    def test_deep_skipped_when_http_down(self):
        report = run(self.manager(url=closed_port_url()).health(deep=True, timeout=1))
        self.assertFalse(report["connected"])
        self.assertNotIn("deep", report)

    def test_scraper_health_delegates(self):
        from cdp_scraper import Endpoint, Platform
        platform = Platform("hp", endpoints=[Endpoint("x", url="https://s.test", api_match="a", parser=lambda d: [])])
        report = run(Scraper(platform, manager=self.manager()).health())
        self.assertTrue(report["connected"])


if __name__ == "__main__":
    unittest.main()
