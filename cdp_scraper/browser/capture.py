"""Capture response API generik (smart scroll & wait)."""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..errors import PageCrashed
from ..logs import get_logger
from .captcha import CaptchaGuard, detect_captcha, wait_captcha
from .diagnostics import DebugOptions, page_diag, save_debug_shot


_STATIC_TYPES = ("image", "media", "font", "stylesheet")


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
                  poll_interval=0.5, settle=1.0, final_sleep=1.0, body_parser=None, trace=False,
                  log=None, diag=None, debug=None, captcha=None, context=None):
    log = log or get_logger()
    captcha = CaptchaGuard.coerce(captcha)
    diag = {} if diag is None else diag
    debug = debug or DebugOptions()
    matches, match_label = compile_matcher(api_match)
    get_key = key_getter(key_fn)

    items = []
    seen = set()
    state = {"limit_reached": False, "exhausted": False, "crashed": False, "captcha": False}
    cap = {"detected": 0, "pauses": 0}
    notify_tasks = []
    network = {"seen": 0, "matched": 0, "bad_status": 0, "parse_errors": 0, "requests": []}

    def check_crash():
        if state["crashed"]:
            raise PageCrashed("Tab Chrome crash (cek --shm-size / memori container)")

    def on_crash(_):
        state["crashed"] = True
        log.error("Tab crash terdeteksi (Target crashed).")

    def ingest(data_json):
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

    async def handle_resp(res):
        method = res.request.method
        if method == "OPTIONS":
            return
        kind = getattr(res.request, "resource_type", "") or ""
        is_match = bool(matches(res.url)) and kind not in _STATIC_TYPES
        if kind in ("xhr", "fetch") or is_match:
            network["seen"] += 1
            if len(network["requests"]) < 40:
                network["requests"].append({"method": method, "status": res.status, "type": kind,
                                            "matched": is_match, "url": res.url[:140]})
            if trace:
                log.info(f"Trace: {method} {res.status} {kind} {res.url[:140]}")
        if state["limit_reached"] or not is_match:
            return
        if 300 <= res.status < 400:
            return
        network["matched"] += 1
        if res.status != 200:
            network["bad_status"] += 1
            log.warning(f"API: {match_label} status {res.status}: {res.url[:150]}")
            return
        try:
            payloads = [await res.json()] if body_parser is None else list(body_parser(await res.text()))
        except Exception as e:
            network["parse_errors"] += 1
            log.warning(f"API: Gagal parse body ({match_label}): {e}")
            return
        for data_json in payloads:
            ingest(data_json)
            if state["limit_reached"]:
                break

    stopped_by = "max_scrolls"
    scrolls = 0
    stalled = 0
    page.on("response", handle_resp)
    page.on("crash", on_crash)
    try:
        async def emit(kind, where, found, **extra):
            """Kirim event captcha ke hook notify di latar belakang (tidak memperpanjang jeda)."""
            if not captcha.notify:
                return
            event = dict(context or {}, event=kind, where=where, marker=found, pause=cap["pauses"],
                         max_pauses=captcha.max_pauses, wait=captcha.wait, url=page.url, screenshot=None, **extra)
            if kind != "resolved":
                try:
                    event["screenshot"] = await page.screenshot(timeout=5000)
                except Exception as e:
                    log.debug(f"screenshot untuk notifikasi gagal: {e}")

            async def deliver():
                try:
                    outcome = captcha.notify(event)
                    if asyncio.iscoroutine(outcome):
                        await outcome
                except Exception as e:
                    log.warning(f"Hook notify captcha error: {e}")
            notify_tasks.append(asyncio.ensure_future(deliver()))

        async def handle_captcha(where):
            """Jeda bila ada captcha. False = captcha tidak kunjung selesai (menyerah)."""
            found = await detect_captcha(page, captcha) if captcha else None
            while found:
                if cap["pauses"] >= captcha.max_pauses:
                    state["captcha"] = True
                    log.error(f"Captcha masih ada setelah {cap['pauses']}x jeda {captcha.wait:g} detik. Menyerah.")
                    await emit("gave_up", where, found)
                    return False
                cap["pauses"] += 1
                cap["detected"] += 1
                await save_debug_shot(page, "debug_captcha.png", debug=debug, log=log)
                log.warning(f"Captcha terdeteksi ({found}) saat {where}. Jeda {captcha.wait:g} detik "
                            f"(jeda ke-{cap['pauses']}/{captcha.max_pauses}); selesaikan manual bila perlu.")
                await emit("detected", where, found)
                started = time.monotonic()
                found = await wait_captcha(page, captcha, log)
                if not found:
                    await emit("resolved", where, None, elapsed=time.monotonic() - started)
            return True

        async def open_and_prepare():
            while True:
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
                pauses_before = cap["pauses"]
                if not await handle_captcha("pembukaan halaman"):
                    return False
                if cap["pauses"] > pauses_before and not items and captcha.reload_if_empty:
                    log.info("Captcha selesai, belum ada data: membuka ulang halaman.")
                    continue            # terbatas oleh max_pauses (captcha muncul lagi = jeda lagi)
                break
            if prepare_fn:
                await prepare_fn(page)
                check_crash()
            return True

        opened = await open_and_prepare()

        log.info(f"Data awal tertangkap: {len(items)}")

        scroller = scroll_fn or default_scroll
        for i in range(max_scrolls if opened else 0):
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

            if captcha:
                pauses_before = cap["pauses"]
                if not await handle_captcha(f"scroll {scrolls}"):
                    break
                if cap["pauses"] > pauses_before:       # baru saja jeda karena captcha
                    stalled = 0
                    if not items and captcha.reload_if_empty:
                        if not await open_and_prepare():
                            break
                    continue

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
        if state["captcha"]:
            stopped_by = "captcha"
        elif state["limit_reached"]:
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
        if notify_tasks:        # beri waktu alert terkirim sebelum capture selesai
            await asyncio.wait(notify_tasks, timeout=20)
            for task in notify_tasks:
                if not task.done():
                    task.cancel()
        diag["network"] = network
        diag["scrolls"] = scrolls
        if captcha:
            diag["captcha"] = dict(cap, blocked=state["captcha"])
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
