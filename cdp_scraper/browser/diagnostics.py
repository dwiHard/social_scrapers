"""Diagnostik halaman: fingerprint, isi body, screenshot debug."""
import os

from config import BASE_DIR
from logger import log_success, log_info, log_warning
from browser.state import LAST_DIAG


async def page_diag(page, nav_resp, tag):
    """Kumpulkan & log kondisi halaman: status navigasi, fingerprint, isi halaman."""
    info = {"tag": tag, "engine": LAST_DIAG.get("engine"), "url": page.url,
            "nav_status": nav_resp.status if nav_resp else None}
    try:
        info["title"] = await page.title()
    except Exception:
        pass
    try:
        info.update(await page.evaluate("""() => ({
            webdriver: navigator.webdriver,
            ua: navigator.userAgent,
            languages: navigator.languages,
            plugins: navigator.plugins.length,
            has_window_chrome: !!window.chrome
        })"""))
    except Exception as e:
        info["eval_error"] = str(e)
    try:
        info["body_snippet"] = (await page.inner_text("body", timeout=3000))[:200].replace("\n", " ")
    except Exception:
        pass
    LAST_DIAG.update(info)
    log_info(f"Diagnostik: {info}")
    return info


async def save_debug_shot(page, name="debug_last.png"):
    path = os.path.join(BASE_DIR, name)
    try:
        await page.screenshot(path=path, timeout=5000)
        log_success(f"Diagnostik: Screenshot disimpan: {path}")
    except Exception as e:
        log_warning(f"Diagnostik: Gagal screenshot: {e}")
