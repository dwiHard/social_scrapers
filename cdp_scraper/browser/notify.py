"""Notifikasi Telegram (aiogram 3.x) untuk kejadian captcha.

  pip install aiogram          # opsional; hanya dibutuhkan bila notifier dipakai

  notifier = TelegramNotifier.from_env()          # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (+ TELEGRAM_THREAD_ID)
  captcha = TIKTOK_CAPTCHA.with_notify(notifier.captcha_event)      # None-safe: lihat `notify_hook`

Kegagalan mengirim (jaringan, token salah, aiogram belum terpasang) hanya dicatat di log dan
tidak pernah menghentikan scraping.
"""
import asyncio
import os
import time

from .logs import get_logger


class TelegramNotifier:
    def __init__(self, token, chat_id, *, thread_id=None, send_screenshot=True, hint=None,
                 events=("detected", "resolved", "gave_up"), timeout=15.0, min_interval=0.0, log=None):
        if not token or not chat_id:
            raise ValueError("token dan chat_id Telegram wajib diisi")
        self.token = token
        self.chat_id = chat_id
        self.thread_id = int(thread_id) if thread_id not in (None, "") else None
        self.send_screenshot = send_screenshot
        self.hint = hint
        self.events = tuple(events)
        self.timeout = timeout
        self.min_interval = min_interval
        self.log = log or get_logger()
        self._last_detected = None

    @classmethod
    def from_env(cls, prefix="", environ=None, **kwargs):
        """Buat dari env: {prefix}TELEGRAM_BOT_TOKEN, {prefix}TELEGRAM_CHAT_ID, {prefix}TELEGRAM_THREAD_ID,
        {prefix}TELEGRAM_HINT. Mengembalikan None bila token/chat_id tidak diisi."""
        env = os.environ if environ is None else environ
        token, chat_id = env.get(f"{prefix}TELEGRAM_BOT_TOKEN"), env.get(f"{prefix}TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            return None
        kwargs.setdefault("thread_id", env.get(f"{prefix}TELEGRAM_THREAD_ID"))
        kwargs.setdefault("hint", env.get(f"{prefix}TELEGRAM_HINT"))
        return cls(token, chat_id, **kwargs)

    # ---- format pesan ----------------------------------------------------------------------

    def format(self, event):
        kind = event.get("event")
        where = " / ".join(str(event[k]) for k in ("platform", "endpoint") if event.get(k))
        label = event.get("label")
        lines = {
            "detected": ["⚠️ Captcha terdeteksi"],
            "resolved": ["✅ Captcha selesai, scraping dilanjutkan"],
            "gave_up": ["❌ Captcha tidak selesai, scraping dihentikan"],
        }.get(kind, [f"ℹ️ Captcha: {kind}"])
        if where:
            lines.append(f"Target: {where}" + (f" ({label})" if label else ""))
        if event.get("url"):
            lines.append(f"Halaman: {event['url']}")
        if kind == "detected":
            lines.append(f"Penanda: {event.get('marker')}")
            lines.append(f"Jeda {event.get('pause')}/{event.get('max_pauses')}: {event.get('wait'):g} detik")
            if self.hint:
                lines.append(self.hint)
        elif kind == "resolved":
            lines.append(f"Setelah jeda {event.get('pause')} ({event.get('elapsed', 0):.0f} detik)")
        elif kind == "gave_up":
            lines.append(f"Masih ada setelah {event.get('pause')}x jeda {event.get('wait'):g} detik")
            if self.hint:
                lines.append(self.hint)
        return "\n".join(lines)

    # ---- kirim -----------------------------------------------------------------------------

    def _mask(self, text):
        return str(text).replace(self.token, "***")

    async def send(self, text, photo=None):
        """Kirim pesan (dengan foto bila ada). True bila berhasil; tidak pernah melempar exception."""
        try:
            from aiogram import Bot
        except ImportError:
            self.log.warning("Notifikasi Telegram dilewati: aiogram belum terpasang (pip install aiogram)")
            return False
        extra = {"message_thread_id": self.thread_id} if self.thread_id is not None else {}
        try:
            async def deliver():
                async with Bot(token=self.token) as bot:
                    if photo:
                        from aiogram.types import BufferedInputFile
                        try:
                            await bot.send_photo(chat_id=self.chat_id, caption=text[:1024], **extra,
                                                 photo=BufferedInputFile(photo, filename="captcha.png"))
                            return
                        except Exception as e:      # gagal kirim foto: tetap kirim teks
                            self.log.debug(f"send_photo gagal ({self._mask(e)}), kirim teks saja")
                    await bot.send_message(chat_id=self.chat_id, text=text[:4096], **extra)
            await asyncio.wait_for(deliver(), self.timeout)
            return True
        except Exception as e:
            self.log.warning(f"Notifikasi Telegram gagal: {self._mask(e) or e.__class__.__name__}")
            return False

    async def captcha_event(self, event):
        """Hook untuk `CaptchaGuard(notify=...)`."""
        kind = event.get("event")
        if kind not in self.events:
            return False
        if kind == "detected" and self.min_interval:
            now = time.monotonic()
            if self._last_detected is not None and now - self._last_detected < self.min_interval:
                return False
            self._last_detected = now
        photo = event.get("screenshot") if self.send_screenshot and kind != "resolved" else None
        return await self.send(self.format(event), photo)


def notify_hook(notifier):
    """`notifier.captcha_event` atau None bila notifier None (praktis untuk from_env())."""
    return notifier.captcha_event if notifier is not None else None
