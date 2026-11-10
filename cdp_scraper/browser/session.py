"""Sesi browser via CDP + lock agar hanya 1 scraping berjalan sekaligus."""
import asyncio
import threading
from contextlib import asynccontextmanager

try:
    from patchright.async_api import async_playwright
    PW_ENGINE = "patchright"
except ImportError:
    from playwright.async_api import async_playwright
    PW_ENGINE = "playwright"

from config import CDP_URL, BROWSER_TIMEZONE, LOCK_WAIT_TIMEOUT, MAX_CONCURRENT_SESSIONS
from logger import log_success, log_info, log_warning, log_debug
from browser.state import LAST_DIAG

_session_slots = threading.BoundedSemaphore(MAX_CONCURRENT_SESSIONS)
_active_lock = threading.Lock()
_active = 0


def is_browser_busy():
    return _active >= MAX_CONCURRENT_SESSIONS


async def _acquire_session_lock(timeout=LOCK_WAIT_TIMEOUT):
    """Lock yang bisa dibatalkan & ada batas tunggu."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not _session_slots.acquire(blocking=False):
        if loop.time() > deadline:
            raise TimeoutError("Browser sedang sibuk, coba lagi nanti")
        await asyncio.sleep(0.5)


@asynccontextmanager
async def playwright_session():
    """Connect ke Chrome yang sudah berjalan via CDP, yield page."""
    global _active
    log_info("Menunggu giliran browser (lock)...")
    await _acquire_session_lock()
    with _active_lock:
        _active += 1
    try:
        async with async_playwright() as p:
            log_info(f"Menghubungkan ke CDP di {CDP_URL} ({PW_ENGINE})...")
            LAST_DIAG["engine"] = f"{PW_ENGINE} (connect_over_cdp)"
            browser = await p.chromium.connect_over_cdp(CDP_URL)

            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await context.new_page()
            await page.bring_to_front()

            client = None
            try:
                try:
                    client = await context.new_cdp_session(page)
                    await client.send("Network.enable")
                    if BROWSER_TIMEZONE:
                        try:
                            await client.send("Emulation.setTimezoneOverride",
                                              {"timezoneId": BROWSER_TIMEZONE})
                        except Exception as e:
                            log_debug(f"timezone override: {e}")
                except Exception as e:
                    log_warning(f"Gagal setup CDP: {e}")

                yield page
            finally:
                if client is not None:
                    try:
                        await asyncio.wait_for(client.detach(), timeout=3.0)
                    except Exception as e:
                        log_debug(f"detach: {e}")
                try:
                    await asyncio.wait_for(page.close(), timeout=3.0)
                except asyncio.TimeoutError:
                    log_warning("Penutupan tab terlalu lama (diabaikan).")
                except Exception as e:
                    log_debug(f"page.close: {e}")
                log_success("Sesi CDP selesai, koneksi diputus.")
    finally:
        with _active_lock:
            _active -= 1
        _session_slots.release()
