"""Tes transport pydoll: adaptor diuji terhadap pydoll TIRUAN (tests/fake_pydoll.py) di atas Chrome asli."""
import asyncio
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from cdp_scraper import (CDPConfig, CDPSessionManager, Endpoint, Platform, PydollTransport, Scraper,
                         create_transport)
from cdp_scraper.browser.rawpage import CDPProtocolError
from cdp_scraper.browser.ws import ConnectionClosed

from tests import fake_pydoll
from tests.test_raw_transport import CHROME, _Site, free_port, run


class UnitTests(unittest.TestCase):
    def test_registered(self):
        transport = create_transport(CDPConfig(transport="pydoll"))
        self.assertIsInstance(transport, PydollTransport)
        self.assertEqual(transport.engine_label, "pydoll (page websocket)")
        with self.assertRaises(ValueError):
            create_transport(CDPConfig(transport="pydoll"), engine_factory=lambda: None)

    def test_not_installed_has_clear_message(self):
        saved = {k: sys.modules.pop(k) for k in list(sys.modules) if k == "pydoll" or k.startswith("pydoll.")}
        sys.modules["pydoll"] = None            # memaksa ImportError
        try:
            from cdp_scraper.browser.pydoll_conn import PydollConnection
            with self.assertRaises(ImportError) as ctx:
                run(PydollConnection.open("ws://127.0.0.1:1/devtools/page/x"))
            self.assertIn("pip install pydoll-python", str(ctx.exception))
        finally:
            sys.modules.pop("pydoll", None)
            sys.modules.update(saved)


@unittest.skipUnless(CHROME, "Chrome tidak terpasang")
class PydollOnChromeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.uninstall = fake_pydoll.install()
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

    @classmethod
    def tearDownClass(cls):
        cls.chrome.terminate()
        cls.chrome.wait(10)
        cls.site.shutdown()
        shutil.rmtree(cls.profile, ignore_errors=True)
        cls.uninstall()

    def setUp(self):
        fake_pydoll.ConnectionHandler.async_register = False
        fake_pydoll.ConnectionHandler.raise_on_execute = None

    def manager(self):
        return CDPSessionManager(CDPConfig(cdp_url=f"http://127.0.0.1:{self.port}", transport="pydoll",
                                           debug_screenshots=False))

    def test_page_api_through_pydoll_connection(self):
        async def main():
            async with self.manager().session() as page:
                resp = await page.goto(self.site_url)
                self.assertEqual(resp.status, 200)
                self.assertEqual(await page.title(), "Uji Raw")
                await page.locator("#btn").first.click(timeout=3000)
                self.assertEqual(await page.title(), "diklik")
                self.assertEqual(await page.evaluate("(a) => a + 1", 41), 42)
        run(main())
        self.assertTrue(fake_pydoll.ConnectionHandler.instances[-1].closed)

    def test_scraper_end_to_end(self):
        platform = Platform("lokal", endpoints=[Endpoint(
            "list", url=self.site_url, api_match="/api/list", parser=lambda d: d["items"], key="id",
            end=lambda d: not d.get("has_more"), initial_sleep=0.5, max_wait=2, limit=25, max_scrolls=6)])
        result = run(Scraper(platform, manager=self.manager()).run("list", limit=25))
        self.assertEqual(result.status, "success")
        self.assertGreaterEqual(result.count, 25)
        self.assertEqual(result.diagnostics["engine"], "pydoll (page websocket)")

    def test_async_register_callback_is_supported(self):
        fake_pydoll.ConnectionHandler.async_register = True
        async def main():
            async with self.manager().session() as page:
                await page.goto(self.site_url)
                return await page.title()
        self.assertEqual(run(main()), "Uji Raw")

    def test_error_mapping(self):
        async def main():
            async with self.manager().session() as page:
                with self.assertRaises(CDPProtocolError):
                    await page.conn.send("Tidak.ada", {})
                fake_pydoll.ConnectionHandler.raise_on_execute = fake_pydoll.CommandExecutionTimeout("x")
                with self.assertRaises(TimeoutError):
                    await page.conn.send("Runtime.evaluate", {"expression": "1"}, timeout=1)
                fake_pydoll.ConnectionHandler.raise_on_execute = fake_pydoll.WebSocketConnectionClosed("x")
                with self.assertRaises(ConnectionClosed):
                    await page.conn.send("Runtime.evaluate", {"expression": "1"})
                with self.assertRaises(ConnectionClosed):          # setelah itu koneksi dianggap tertutup
                    await page.conn.send("Runtime.evaluate", {"expression": "1"})
                fake_pydoll.ConnectionHandler.raise_on_execute = None
        try:
            run(main())
        finally:
            fake_pydoll.ConnectionHandler.raise_on_execute = None

    def test_health_deep(self):
        report = run(self.manager().health(deep=True))
        self.assertTrue(report["connected"], report)
        self.assertEqual(report["engine"], "pydoll")


if __name__ == "__main__":
    unittest.main()
