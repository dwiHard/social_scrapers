"""Deteksi captcha + jeda otomatis (beri waktu menyelesaikannya manual, mis. lewat VNC)."""
import asyncio
import dataclasses
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple

_DETECT_JS = """(o) => {
    const vis = (e) => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length)
                       && getComputedStyle(e).visibility !== 'hidden';
    for (const s of o.sels) {
        let els;
        try { els = document.querySelectorAll(s); } catch (e) { continue; }
        for (const e of els) if (vis(e)) return 'selector ' + s;
    }
    if (o.texts.length) {
        const body = ((document.body && document.body.innerText) || '').toLowerCase();
        for (const t of o.texts) if (body.includes(t.toLowerCase())) return 'teks "' + t + '"';
    }
    return null;
}"""


@dataclass(frozen=True)
class CaptchaGuard:
    """Aturan deteksi captcha.

    selectors: selector CSS elemen captcha (dihitung hanya bila terlihat).
    texts: potongan teks halaman yang menandakan captcha (tidak peka huruf besar/kecil).
    wait: lama jeda (detik) setiap kali captcha terdeteksi. Default 60.
    max_pauses: berapa kali jeda sebelum menyerah (stopped_by='captcha').
    poll: selama jeda, cek ulang tiap sekian detik.
    early_resume: lanjut lebih awal begitu captcha hilang (mis. sudah diselesaikan). False = selalu jeda penuh.
    reload_if_empty: setelah captcha selesai dan belum ada data sama sekali, buka ulang halaman.
    notify: hook `fn(event: dict)` (sync/async) dipanggil saat 'detected' / 'resolved' / 'gave_up' (mis. alert Telegram,
            lihat notify.TelegramNotifier). Error di hook hanya dicatat, tidak menghentikan scraping.
    """

    selectors: Tuple[str, ...] = ()
    texts: Tuple[str, ...] = ()
    wait: float = 60.0
    max_pauses: int = 3
    poll: float = 2.0
    early_resume: bool = True
    reload_if_empty: bool = True
    notify: Optional[Callable[[dict], Any]] = None

    def with_notify(self, notify):
        """Salinan guard dengan hook notifikasi (sync/async, menerima dict event). None = tanpa notifikasi."""
        return dataclasses.replace(self, notify=notify)

    @classmethod
    def coerce(cls, value):
        if value is None or isinstance(value, cls):
            return value
        if isinstance(value, dict):
            return cls(**value)
        raise TypeError("captcha harus CaptchaGuard atau dict")


async def detect_captcha(page, guard) -> Optional[str]:
    """Kembalikan deskripsi penanda captcha yang terlihat, atau None."""
    try:
        return await page.evaluate(_DETECT_JS, {"sels": list(guard.selectors), "texts": list(guard.texts)})
    except Exception:
        return None


async def wait_captcha(page, guard, log):
    """Jeda `guard.wait` detik (berhenti lebih awal bila captcha hilang dan early_resume).
    Kembalikan penanda captcha yang masih ada setelah jeda, atau None bila sudah hilang."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + guard.wait
    next_log = loop.time() + 15
    while loop.time() < deadline:
        await asyncio.sleep(min(guard.poll, max(0.0, deadline - loop.time())))
        if guard.early_resume and not await detect_captcha(page, guard):
            log.success("Captcha hilang, melanjutkan.")
            return None
        if loop.time() >= next_log and loop.time() < deadline:
            log.info(f"Menunggu captcha diselesaikan... sisa {deadline - loop.time():.0f} detik")
            next_log = loop.time() + 15
    return await detect_captcha(page, guard)
