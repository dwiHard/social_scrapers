"""Capture response API generik (smart scroll & wait)."""
import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..errors import PageCrashed
from ..logs import get_logger
from .diagnostics import DebugOptions, page_diag, save_debug_shot


def compile_matcher(match):
    """api_match bisa: substring (str), regex terkompilasi, atau callable(url) -> bool."""
    if hasattr(match, "search"):
        return (lambda url: bool(match.search(url))), match.pattern
    if callable(match):
        return match, getattr(match, "__name__", "callable")
    text = str(match)
    return (lambda url: text in url), text


def key_getter(key):
    if callable(key):
        return key
    return lambda item: item.get(key) if isinstance(item, dict) else None


async def default_scroll(page):
    await page.keyboard.press("PageDown")


@dataclass
class CaptureResult:
    items: List[Any] = field(default_factory=list)
    stopped_by: str = "max_scrolls"
    scrolls: int = 0
    diagnostics: Dict[str, Any] = field(default_factory=dict)


async def capture(page, url, api_match, extract_fn, key_fn, limit,
                  max_scrolls=8, max_wait=8.0, stall_limit=3,
                  initial_sleep=5, scroll_fn=None, prepare_fn=None, end_fn=None,
                  nav_timeout_ms=60000, wait_until="domcontentloaded",
                  poll_interval=0.5, settle=1.0, final_sleep=1.0,
                  log=None, diag=None, debug=None):
    log = log or get_logger()
    diag = {} if diag is None else diag
    debug = debug or DebugOptions()
    matches, match_label = compile_matcher(api_match)
    get_key = key_getter(key_fn)

    items = []
    seen = set()
    state = {"limit_reached": False, "exhausted": False, "crashed": False}

    def check_crash():
        if state["crashed"]:
            raise PageCrashed("Tab Chrome crash (cek --shm-size / memori container)")

    def on_crash(_):
        state["crashed"] = True
        log.error("Tab crash terdeteksi (Target crashed).")

    async def handle_resp(res):
        if state["limit_reached"] or res.request.method == "OPTIONS":
            return
        if not matches(res.url):
            return
        if res.status != 200:
            log.warning(f"API: {match_label} status {res.status}: {res.url[:150]}")
            return
        try:
            data_json = await res.json()
        except Exception as e:
            log.warning(f"API: Gagal parse JSON ({match_label}): {e}")
            return
        try:
            if isinstance(data_json, dict):
                log.info(f"API: {match_label} keys={list(data_json.keys())[:8]}")
            for item in extract_fn(data_json):
                k = get_key(item)
                if not k or k in seen:
                    continue
                seen.add(k)
                items.append(item)
                if len(items) >= limit:
                    state["limit_reached"] = True
                    break
            if end_fn and end_fn(data_json):
                state["exhausted"] = True
                log.info("API: Server menandai data sudah habis.")
            log.info(f"API: Total tertangkap: {len(items)}")
        except Exception as e:
            log.warning(f"API: Gagal ekstrak data: {e}")

    stopped_by = "max_scrolls"
    scrolls = 0
    stalled = 0
    page.on("response", handle_resp)
    page.on("crash", on_crash)
    try:
        log.info(f"Membuka link: {url}")
        try:
            nav_resp = await page.goto(url, wait_until=wait_until, timeout=nav_timeout_ms)
        except Exception as e:
            if "crash" in str(e).lower():
                state["crashed"] = True
            raise
        check_crash()
        await asyncio.sleep(initial_sleep)
        check_crash()
        await page_diag(page, nav_resp, "after_goto", diag=diag, log=log)
        check_crash()

        if prepare_fn:
            await prepare_fn(page)
            check_crash()

        log.info(f"Data awal tertangkap: {len(items)}")

        scroller = scroll_fn or default_scroll
        for i in range(max_scrolls):
            check_crash()
            if state["limit_reached"]:
                log.info("Limit tercapai, berhenti scroll.")
                break
            if state["exhausted"]:
                log.info("Tidak ada data lagi, berhenti scroll.")
                break

            before = len(items)
            scrolls = i + 1
            log.info(f"Scroll {scrolls}/{max_scrolls}...")
            try:
                await scroller(page)
            except Exception as e:
                if "crash" in str(e).lower():
                    state["crashed"] = True
                    check_crash()
                log.warning(f"Scroll gagal: {e}")

            waited = 0.0
            while (len(items) == before and waited < max_wait
                   and not state["limit_reached"] and not state["exhausted"]
                   and not state["crashed"]):
                await asyncio.sleep(poll_interval)
                waited += poll_interval
            check_crash()

            if len(items) == before:
                if state["exhausted"]:
                    break
                log.warning("Data baru tidak terdeteksi (mungkin mentok/lambat).")
                stalled += 1
            else:
                stalled = 0
                if state["exhausted"]:
                    break
                await asyncio.sleep(settle)

            if stalled >= stall_limit:
                log.info(f"{stall_limit}x scroll tanpa data baru. Berhenti.")
                break

        await asyncio.sleep(final_sleep)
        if state["limit_reached"]:
            stopped_by = "limit"
        elif state["exhausted"]:
            stopped_by = "exhausted"
        elif stalled >= stall_limit:
            stopped_by = "stalled"

        if not items:
            await page_diag(page, None, "no_items", diag=diag, log=log)
            await save_debug_shot(page, "debug_last.png", debug=debug, log=log)
        elif stalled >= stall_limit:
            await page_diag(page, None, "stalled", diag=diag, log=log)
            await save_debug_shot(page, "debug_stalled.png", debug=debug, log=log)
    finally:
        try:
            page.remove_listener("response", handle_resp)
            page.remove_listener("crash", on_crash)
        except Exception:
            pass

    log.success(f"Capture {match_label} selesai: {len(items)} data")
    return CaptureResult(items=items, stopped_by=stopped_by, scrolls=scrolls, diagnostics=diag)


async def capture_api(page, url, api_match, extract_fn, key_fn, limit, **kwargs):
    """Versi ringkas: hanya mengembalikan list item (kompatibel 0.1.x)."""
    return (await capture(page, url, api_match, extract_fn, key_fn, limit, **kwargs)).items
