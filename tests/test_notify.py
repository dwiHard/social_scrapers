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
        kinds = self.kinds()
        self.assertEqual([m for m, _ in kinds], ["send_photo", "send_message"])
        self.assertIn("Captcha terdeteksi", kinds[0][1])
        self.assertIn("t / f", kinds[0][1])                     # platform "t", endpoint "f" dari runner
        self.assertTrue(Bot.sent[0][1]["photo"].file.startswith(b"\x89PNG"))    # screenshot Chrome asli
        self.assertIn("Captcha selesai", kinds[1][1])

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
