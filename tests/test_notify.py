"""Tes notifikasi Telegram: unit (aiogram tiruan) + integrasi captcha di Chrome asli."""
import asyncio
import sys
import time
import unittest

from cdp_scraper import CaptchaGuard, TelegramNotifier, notify_hook
from tests import fake_aiogram
from tests.fake_aiogram import Bot
from tests.test_captcha import CAPTCHA_BOX, CHROME, CaptchaTests, PAGES, run  # noqa: F401

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20


def event(kind="detected", **kw):
    base = dict(event=kind, where="pembukaan halaman", marker="selector #captcha_container", pause=1,
                max_pauses=3, wait=60.0, url="https://www.tiktok.com/@u/video/1", screenshot=PNG,
                platform="tiktok", endpoint="comments", label="123", elapsed=12.0)
    base.update(kw)
    return base


class UnitTests(unittest.TestCase):
    def setUp(self):
        self.uninstall = fake_aiogram.install()
        self.notifier = TelegramNotifier("123:SECRET", "-100500", thread_id="7", hint="Buka noVNC :6900")

    def tearDown(self):
        self.uninstall()

    def test_from_env(self):
        self.assertIsNone(TelegramNotifier.from_env(environ={}))
        self.assertIsNone(notify_hook(None))
        n = TelegramNotifier.from_env(environ={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1",
                                               "TELEGRAM_THREAD_ID": "9", "TELEGRAM_HINT": "h"})
        self.assertEqual((n.token, n.chat_id, n.thread_id, n.hint), ("t", "1", 9, "h"))
        self.assertEqual(notify_hook(n), n.captcha_event)
        with self.assertRaises(ValueError):
            TelegramNotifier("", "1")

    def test_detected_sends_photo_with_caption_and_thread(self):
        self.assertTrue(run(self.notifier.captcha_event(event())))
        method, kw = Bot.sent[0]
        self.assertEqual(method, "send_photo")
        self.assertEqual((kw["chat_id"], kw["message_thread_id"]), ("-100500", 7))
        self.assertEqual(kw["photo"].file, PNG)
        for text in ("Captcha terdeteksi", "tiktok / comments", "(123)", "Jeda 1/3: 60 detik", "Buka noVNC :6900"):
            self.assertIn(text, kw["caption"])
        self.assertEqual(Bot.sessions_closed, 1)          # `async with Bot` menutup sesi

    def test_resolved_and_gave_up_messages(self):
        run(self.notifier.captcha_event(event("resolved")))
        run(self.notifier.captcha_event(event("gave_up", pause=3)))
        self.assertEqual(Bot.sent[0][0], "send_message")      # resolved: tanpa foto
        self.assertIn("Captcha selesai", Bot.sent[0][1]["text"])
        self.assertEqual(Bot.sent[1][0], "send_photo")
        self.assertIn("Masih ada setelah 3x jeda 60 detik", Bot.sent[1][1]["caption"])

    def test_photo_failure_falls_back_to_text(self):
        Bot.fail_photo = True
        self.assertTrue(run(self.notifier.captcha_event(event())))
        self.assertEqual(Bot.sent[0][0], "send_message")

    def test_never_raises_and_masks_token(self):
        Bot.fail_all = RuntimeError("gagal https://api.telegram.org/bot123:SECRET/sendMessage")
        logs = []

        class Log:
            def warning(self, m): logs.append(m)
            def debug(self, m): logs.append(m)
        self.notifier.log = Log()
        self.assertFalse(run(self.notifier.captcha_event(event())))
        self.assertTrue(logs)
        self.assertTrue(all("SECRET" not in m for m in logs))

    def test_last_error_tracks_failures(self):
        self.assertIsNone(self.notifier.last_error)
        Bot.fail_all = RuntimeError("Unauthorized")
        self.assertFalse(run(self.notifier.captcha_event(event())))
        self.assertEqual(self.notifier.last_error, "RuntimeError: Unauthorized")
        Bot.fail_all = None
        self.assertTrue(run(self.notifier.captcha_event(event())))
        self.assertIsNone(self.notifier.last_error)

    def test_timeout_is_bounded(self):
        Bot.delay = 5
        self.notifier.timeout = 0.3
        started = time.monotonic()
        self.assertFalse(run(self.notifier.captcha_event(event())))
        self.assertLess(time.monotonic() - started, 2)

    def test_events_filter_and_min_interval(self):
        n = TelegramNotifier("t", "1", events=("detected",), min_interval=60)
        self.assertFalse(run(n.captcha_event(event("resolved"))))
        self.assertTrue(run(n.captcha_event(event())))
        self.assertFalse(run(n.captcha_event(event())))       # terlalu dekat dengan alert sebelumnya
        self.assertEqual(len(Bot.sent), 1)

    def test_without_screenshot_option(self):
        n = TelegramNotifier("t", "1", send_screenshot=False)
        run(n.captcha_event(event()))
        self.assertEqual(Bot.sent[0][0], "send_message")

    def test_log_attached_as_document_after_photo(self):
        text = "Waktu: x\n--- log ---\n[WARNING] Captcha terdeteksi"
        self.assertTrue(run(self.notifier.captcha_event(event(debug_text=text))))
        self.assertEqual([m for m, _ in Bot.sent], ["send_photo", "send_document"])
        kw = Bot.sent[1][1]
        self.assertEqual((kw["chat_id"], kw["message_thread_id"]), ("-100500", 7))
        self.assertEqual(kw["document"].file, text.encode())
        self.assertTrue(kw["document"].filename.startswith("captcha_detected_") and kw["document"].filename.endswith(".txt"))
        self.assertEqual(Bot.sessions_closed, 1)               # satu sesi untuk foto + log

    def test_log_attached_on_give_up_but_not_on_resolved(self):
        run(self.notifier.captcha_event(event("resolved", debug_text="x")))
        run(self.notifier.captcha_event(event("gave_up", debug_text="y")))
        self.assertEqual([m for m, _ in Bot.sent], ["send_message", "send_photo", "send_document"])

    def test_log_disabled_or_missing(self):
        n = TelegramNotifier("t", "1", send_log=False)
        run(n.captcha_event(event(debug_text="x")))
        run(self.notifier.captcha_event(event()))               # tanpa debug_text
        self.assertNotIn("send_document", [m for m, _ in Bot.sent])
        self.assertFalse(TelegramNotifier.from_env(environ={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1",
                                                            "TELEGRAM_SEND_LOG": "false"}).send_log)

    def test_log_sent_even_when_photo_fails(self):
        Bot.fail_photo = True
        run(self.notifier.captcha_event(event(debug_text="x")))
        self.assertEqual([m for m, _ in Bot.sent], ["send_message", "send_document"])

    def test_document_failure_does_not_fail_alert(self):
        Bot.fail_document = True
        self.assertTrue(run(self.notifier.captcha_event(event(debug_text="x"))))
        self.assertEqual([m for m, _ in Bot.sent], ["send_photo"])
        self.assertIn("log debug gagal", self.notifier.last_error)

    def test_missing_aiogram_is_not_fatal(self):
        self.uninstall()
        saved = sys.modules.get("aiogram")
        sys.modules["aiogram"] = None
        try:
            self.assertFalse(run(self.notifier.captcha_event(event())))
        finally:
            sys.modules.pop("aiogram", None)
            if saved is not None:
                sys.modules["aiogram"] = saved
            self.uninstall = fake_aiogram.install()


@unittest.skipUnless(CHROME, "Chrome tidak terpasang")
class CaptchaAlertIntegration(CaptchaTests):
    """Memakai Chrome + situs lokal dari tes captcha; alert lewat TelegramNotifier + aiogram tiruan."""

    def setUp(self):
        self.uninstall = fake_aiogram.install()
        self.notifier = TelegramNotifier("t", "1")

    def tearDown(self):
        self.uninstall()

    def guard(self, **kw):
        kw.setdefault("selectors", ("#captcha_container",))
        return CaptchaGuard(**kw).with_notify(self.notifier.captcha_event)

    def kinds(self):
        return [(m, kw.get("caption") or kw.get("text")) for m, kw in Bot.sent]

    def test_alert_on_detect_and_resolve(self):
        result, _ = self.scrape("/solved", self.guard(wait=20, poll=0.3, max_pauses=2))
        self.assertEqual(result.count, 5)
        kinds = [k for k in self.kinds() if k[0] != "send_document"]
        self.assertEqual([m for m, _ in kinds], ["send_photo", "send_message"])
        self.assertIn("Captcha terdeteksi", kinds[0][1])
        self.assertIn("t / f", kinds[0][1])                     # platform "t", endpoint "f" dari runner
        self.assertTrue(Bot.sent[0][1]["photo"].file.startswith(b"\x89PNG"))    # screenshot Chrome asli
        self.assertIn("Captcha selesai", kinds[1][1])

    def test_alert_includes_debug_log_document(self):
        self.scrape("/solved", self.guard(wait=20, poll=0.3, max_pauses=2))
        docs = [kw for m, kw in Bot.sent if m == "send_document"]
        self.assertEqual(len(docs), 1)                           # hanya "detected"; "resolved" tanpa log
        body = docs[0]["document"].file.decode()
        for text in ("Kejadian  : detected", "Target    : t / f", "--- log", "Captcha terdeteksi", "/solved"):
            self.assertIn(text, body)

    def test_alert_on_give_up(self):
        result, _ = self.scrape("/stuck", self.guard(wait=0.6, poll=0.2, max_pauses=2))
        self.assertEqual(result.stopped_by, "captcha")
        texts = [t for _, t in self.kinds()]
        self.assertEqual(sum("Captcha terdeteksi" in t for t in texts), 2)
        self.assertEqual(sum("tidak selesai" in t for t in texts), 1)

    def test_slow_telegram_does_not_extend_pause(self):
        Bot.delay = 2.0                       # kirim lambat; jeda 1,2 detik x2 tidak boleh ikut menunggu
        result, elapsed = self.scrape("/stuck", self.guard(wait=0.6, poll=0.2, max_pauses=2))
        self.assertEqual(result.stopped_by, "captcha")
        self.assertGreaterEqual(len(Bot.sent), 3)               # semua alert tetap terkirim sebelum selesai

    def test_failing_hook_does_not_break_scrape(self):
        def broken(_event):
            raise RuntimeError("hook rusak")
        result, _ = self.scrape("/solved", CaptchaGuard(selectors=("#captcha_container",), wait=20, poll=0.3,
                                                         max_pauses=2, notify=broken))
        self.assertEqual(result.count, 5)

    def test_inactive_alert_is_visible_in_log(self):
        from cdp_scraper import Endpoint, Platform, Scraper
        from cdp_scraper.logs import JobLogger
        import logging

        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())
        base = logging.getLogger("cdp_scraper_test_inactive")
        base.setLevel(logging.DEBUG)
        base.addHandler(Capture())
        platform = Platform("t", captcha=CaptchaGuard(selectors=("#captcha_container",), wait=0.5, poll=0.2,
                                                      max_pauses=1), endpoints=[Endpoint(
            "f", url=self.base + "/stuck?run=inactive", api_match="/api/feed", parser=lambda d: d["items"],
            key="id", initial_sleep=0.2, max_wait=1.0, max_scrolls=2, stall_limit=1, limit=5)])
        run(Scraper(platform, manager=self.manager(), log=JobLogger(base=base)).run("f"))
        self.assertTrue(any("Alert captcha tidak aktif" in m for m in records), records)

    def test_unconfigured_notifier_means_no_notify(self):
        guard = CaptchaGuard(selectors=("#captcha_container",), wait=20, poll=0.3, max_pauses=2).with_notify(
            notify_hook(TelegramNotifier.from_env(environ={})))
        self.assertIsNone(guard.notify)
        result, _ = self.scrape("/solved", guard)
        self.assertEqual(result.count, 5)
        self.assertEqual(Bot.sent, [])


# agar tes bawaan CaptchaTests tidak ikut terduplikasi di modul ini
for _name in [n for n in dir(CaptchaAlertIntegration) if n.startswith("test_") and n in (
        "test_detect_by_selector_text_and_ignores_hidden", "test_pause_then_resume_early_and_reload",
        "test_gives_up_after_max_pauses", "test_strict_pause_without_early_resume",
        "test_no_captcha_no_overhead_and_dict_config")]:
    setattr(CaptchaAlertIntegration, _name, None)

if __name__ == "__main__":
    unittest.main()
