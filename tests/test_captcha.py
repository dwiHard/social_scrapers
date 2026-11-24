"""Tes deteksi captcha + jeda (Chrome asli + situs lokal; dilewati bila Chrome tidak ada)."""
import asyncio
import json
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cdp_scraper import (CaptchaGuard, CDPConfig, CDPSessionManager, Endpoint, Platform, Scraper,
                         detect_captcha)

CHROME = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")

CAPTCHA_BOX = '<div id="captcha_container" style="width:300px;height:100px">Drag the slider to fit the puzzle</div>'

PAGES = {
    # captcha tampil 1,5 detik pada kunjungan pertama saja (seperti captcha yang sudah diselesaikan lalu reload)
    "/solved": """<html><body>%s<script>
        const k = 'seen' + location.search; const first = !sessionStorage.getItem(k); sessionStorage.setItem(k, '1');
        const box = document.getElementById('captcha_container');
        async function feed() { await fetch('/api/feed'); }
        if (first) { setTimeout(() => { box.remove(); }, 1500); } else { box.remove(); feed(); }
        </script></body></html>""" % CAPTCHA_BOX,
    "/stuck": "<html><body>%s</body></html>" % CAPTCHA_BOX,
    "/text": "<html><body><p>Please Verify to continue</p></body></html>",
    "/hidden": "<html><body><div id='captcha_container' style='display:none'>x</div><p>aman</p></body></html>",
}


class _Site(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/feed"):
            body = json.dumps({"items": [{"id": i + 1} for i in range(5)]}).encode()
            ctype = "application/json"
        else:
            body = PAGES.get(self.path.split("?")[0], "<html></html>").encode()
            ctype = "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run(coro):
    return asyncio.run(coro)


@unittest.skipUnless(CHROME, "Chrome tidak terpasang")
class CaptchaTests(unittest.TestCase):
    runs = 0

    @classmethod
    def setUpClass(cls):
        cls.site = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
        threading.Thread(target=cls.site.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.site.server_address[1]}"
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
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

    def manager(self):
        return CDPSessionManager(CDPConfig(cdp_url=f"http://127.0.0.1:{self.port}", transport="raw",
                                           debug_screenshots=False))

    def scrape(self, path, guard):
        platform = Platform("t", captcha=guard, endpoints=[Endpoint(
            "f", url=self.base + path, api_match="/api/feed", parser=lambda d: d["items"], key="id",
            initial_sleep=0.2, max_wait=1.0, max_scrolls=3, stall_limit=2, limit=5)])
        CaptchaTests.runs += 1
        platform.endpoints["f"].url += f"?run={CaptchaTests.runs}"
        started = time.monotonic()
        result = run(Scraper(platform, manager=self.manager()).run("f"))
        return result, time.monotonic() - started

    def test_detect_by_selector_text_and_ignores_hidden(self):
        guard = CaptchaGuard(selectors=("#captcha_container",), texts=("verify to continue",))

        async def check(path):
            async with self.manager().session() as page:
                await page.goto(self.base + path)
                return await detect_captcha(page, guard)
        self.assertIn("#captcha_container", run(check("/stuck")))
        self.assertIn("verify to continue", run(check("/text")))
        self.assertIsNone(run(check("/hidden")))

    def test_pause_then_resume_early_and_reload(self):
        guard = CaptchaGuard(selectors=("#captcha_container",), wait=20, poll=0.3, max_pauses=2)
        result, elapsed = self.scrape("/solved", guard)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.count, 5)
        self.assertEqual(result.diagnostics["captcha"]["pauses"], 1)
        self.assertFalse(result.diagnostics["captcha"]["blocked"])
        self.assertLess(elapsed, 15)              # lanjut begitu captcha hilang, tidak menunggu penuh 20 detik

    def test_gives_up_after_max_pauses(self):
        guard = CaptchaGuard(selectors=("#captcha_container",), wait=0.8, poll=0.2, max_pauses=2)
        result, elapsed = self.scrape("/stuck", guard)
        self.assertEqual(result.stopped_by, "captcha")
        self.assertEqual(result.status, "error")
        self.assertIn("Captcha", result.error)
        self.assertEqual(result.diagnostics["captcha"]["pauses"], 2)
        self.assertTrue(result.diagnostics["captcha"]["blocked"])
        self.assertGreaterEqual(elapsed, 1.5)     # 2 x 0,8 detik jeda benar-benar dijalankan

    def test_strict_pause_without_early_resume(self):
        guard = CaptchaGuard(selectors=("#captcha_container",), wait=3.0, poll=0.3, max_pauses=1,
                             early_resume=False)
        result, elapsed = self.scrape("/solved", guard)
        self.assertEqual(result.count, 5)
        self.assertGreaterEqual(elapsed, 3.0)     # jeda penuh walau captcha sudah hilang di detik ke-1,5

    def test_no_captcha_no_overhead_and_dict_config(self):
        platform = Platform("t", captcha={"selectors": ["#captcha_container"], "wait": 5})
        self.assertIsInstance(platform.captcha, CaptchaGuard)
        result, elapsed = self.scrape("/hidden", CaptchaGuard(selectors=("#captcha_container",), wait=30))
        self.assertEqual(result.diagnostics["captcha"]["pauses"], 0)
        self.assertLess(elapsed, 10)


if __name__ == "__main__":
    unittest.main()
