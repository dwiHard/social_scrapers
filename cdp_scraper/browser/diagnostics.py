"""Diagnostik halaman: fingerprint, isi body, screenshot debug."""
import os
from dataclasses import dataclass
from typing import Optional

from ..logs import get_logger
from .state import LAST_DIAG


@dataclass
class DebugOptions:
    enabled: bool = True
    directory: Optional[str] = None


async def page_diag(page, nav_resp, tag, diag=None, log=None):
    log = log or get_logger()
    diag = {} if diag is None else diag
    info = {"tag": tag, "engine": diag.get("engine") or LAST_DIAG.get("engine"), "url": page.url,
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
    diag.update(info)
    LAST_DIAG.update(info)
    log.info(f"Diagnostik: {info}")
    return info


async def save_debug_shot(page, name="debug_last.png", debug=None, log=None):
    log = log or get_logger()
    debug = debug or DebugOptions()
    if not debug.enabled:
        return None
    path = os.path.join(debug.directory or os.getcwd(), name)
    try:
        await page.screenshot(path=path, timeout=5000)
        log.success(f"Diagnostik: Screenshot disimpan: {path}")
        return path
    except Exception as e:
        log.warning(f"Diagnostik: Gagal screenshot: {e}")
        return None
