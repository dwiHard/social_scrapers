"""Capture response API generik (smart scroll & wait)."""
import asyncio

from errors import PageCrashed
from logger import log_success, log_info, log_warning, log_error
from browser.diagnostics import page_diag, save_debug_shot


async def default_scroll(page):
    await page.keyboard.press("PageDown")


async def capture_api(page, url, api_match, extract_fn, key_fn, limit,
                      max_scrolls=8, max_wait=8.0, stall_limit=3,
                      initial_sleep=5, scroll_fn=None, prepare_fn=None,
                      end_fn=None):
    items = []
    seen = set()
    state = {"limit_reached": False, "exhausted": False, "crashed": False}

    def check_crash():
        if state["crashed"]:
            raise PageCrashed("Tab Chrome crash (cek --shm-size / memori container)")

    def on_crash(_):
        state["crashed"] = True
        log_error("Tab crash terdeteksi (Target crashed).")

    async def handle_resp(res):
        if state["limit_reached"] or res.request.method == "OPTIONS":
            return
        if api_match not in res.url:
            return
        if res.status != 200:
            log_warning(f"API: {api_match} status {res.status}: {res.url[:150]}")
            return
        try:
            data_json = await res.json()
        except Exception as e:
            log_warning(f"API: Gagal parse JSON ({api_match}): {e}")
            return
        try:
            if isinstance(data_json, dict):
                log_info(
                    f"API: {api_match} has_more={data_json.get('has_more')} "
                    f"cursor={data_json.get('cursor')} keys={list(data_json.keys())[:8]}")
            for item in extract_fn(data_json):
                k = key_fn(item)
                if not k or k in seen:
                    continue
                seen.add(k)
                items.append(item)
                if len(items) >= limit:
                    state["limit_reached"] = True
                    break
            if end_fn and end_fn(data_json):
                state["exhausted"] = True
                log_info("API: Server menandai data sudah habis (has_more=0).")
            log_info(f"API: Total tertangkap: {len(items)}")
        except Exception as e:
            log_warning(f"API: Gagal ekstrak data: {e}")

    page.on("response", handle_resp)
    page.on("crash", on_crash)
    try:
        log_info(f"Membuka link: {url}")
        try:
            nav_resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            if "crash" in str(e).lower():
                state["crashed"] = True
            raise
        check_crash()
        await asyncio.sleep(initial_sleep)
        check_crash()
        await page_diag(page, nav_resp, "after_goto")
        check_crash()

        if prepare_fn:
            await prepare_fn(page)
            check_crash()

        log_info(f"Data awal tertangkap: {len(items)}")

        scroller = scroll_fn or default_scroll
        stalled = 0
        for i in range(max_scrolls):
            check_crash()
            if state["limit_reached"]:
                log_info("Limit tercapai, berhenti scroll.")
                break
            if state["exhausted"]:
                log_info("Tidak ada data lagi, berhenti scroll.")
                break

            before = len(items)
            log_info(f"Scroll {i + 1}/{max_scrolls}...")
            try:
                await scroller(page)
            except Exception as e:
                if "crash" in str(e).lower():
                    state["crashed"] = True
                    check_crash()
                log_warning(f"Scroll gagal: {e}")

            waited = 0.0
            while (len(items) == before and waited < max_wait
                   and not state["limit_reached"] and not state["exhausted"]
                   and not state["crashed"]):
                await asyncio.sleep(0.5)
                waited += 0.5
            check_crash()

            if len(items) == before:
                if state["exhausted"]:
                    break
                log_warning("Data baru tidak terdeteksi (mungkin mentok/lambat).")
                stalled += 1
            else:
                stalled = 0
                if state["exhausted"]:
                    break
                await asyncio.sleep(1.0)

            if stalled >= stall_limit:
                log_info(f"{stall_limit}x scroll tanpa data baru. Berhenti.")
                break

        await asyncio.sleep(1)
        if not items:
            await page_diag(page, None, "no_items")
            await save_debug_shot(page)
        elif stalled >= stall_limit:
            # Berhenti karena macet: simpan screenshot untuk melihat kondisi halaman
            await page_diag(page, None, "stalled")
            await save_debug_shot(page, "debug_stalled.png")
    finally:
        try:
            page.remove_listener("response", handle_resp)
            page.remove_listener("crash", on_crash)
        except Exception:
            pass

    log_success(f"Capture {api_match} selesai: {len(items)} data")
    return items
