"""Uji asap transport pydoll terhadap browser sungguhan (pydoll ASLI), langkah demi langkah.

  pip install pydoll-python
  python examples/pydoll_smoke.py http://172.20.1.9:9225

Setiap langkah mencetak OK/GAGAL dan bentuk data mentah dari pydoll, supaya mudah dicocokkan dengan
adaptor di cdp_scraper/browser/pydoll_conn.py bila ada perbedaan versi.
"""
import asyncio
import importlib.metadata
import sys

from cdp_scraper import CDPConfig, CDPSessionManager
from cdp_scraper.browser.pydoll_conn import import_connection_handler
from cdp_scraper.browser.transports import resolve_page_target
from cdp_scraper.logs import get_logger


def step(name, ok, detail=""):
    print(f"[{'OK' if ok else 'GAGAL'}] {name} {detail}")
    return ok


async def main(cdp_url):
    try:
        version = importlib.metadata.version("pydoll-python")
    except Exception:
        version = "tidak terpasang"
    if not step("pydoll terpasang", version != "tidak terpasang", version):
        return
    Handler = import_connection_handler()
    step("import ConnectionHandler", True, f"{Handler.__module__}.{Handler.__name__}")

    config = CDPConfig(cdp_url=cdp_url, transport="pydoll")
    ws_url, target_id, owns = resolve_page_target(config, get_logger())
    step("cari tab lewat /json", True, f"{ws_url} (dibuat baru: {owns})")

    handler = Handler(ws_address=ws_url)
    loaded = asyncio.Event()
    events = []

    async def on_event(message):
        events.append(message.get("method"))
        if message.get("method") == "Page.loadEventFired":
            loaded.set()

    try:
        raw = await handler.execute_command({"method": "Runtime.evaluate",
                                             "params": {"expression": "1+1", "returnByValue": True}}, timeout=10)
        step("execute_command(Runtime.evaluate)", True, f"-> {raw!r}")
        for method in ("Page.enable", "Network.enable"):
            await handler.execute_command({"method": method, "params": {}}, timeout=10)
        for name in ("Page.loadEventFired", "Network.responseReceived"):
            outcome = handler.register_callback(name, on_event)
            if asyncio.iscoroutine(outcome):
                outcome = await outcome
            step(f"register_callback({name})", True, f"-> id {outcome!r}")
        await handler.execute_command({"method": "Page.navigate", "params": {"url": "https://example.com"}}, timeout=30)
        try:
            await asyncio.wait_for(loaded.wait(), 30)
            step("event diterima", True, f"{sorted(set(events))}")
        except asyncio.TimeoutError:
            step("event diterima", False, f"(hanya: {sorted(set(events))})")
    except Exception as e:
        step("langkah pydoll", False, f"{type(e).__name__}: {e}")
    finally:
        try:
            await handler.close()
        except Exception:
            pass
        if owns:
            pass

    manager = CDPSessionManager(config)
    try:
        async with manager.session() as page:
            await page.goto("https://example.com")
            step("transport pydoll end-to-end", True, f"title={await page.title()!r}")
    except Exception as e:
        step("transport pydoll end-to-end", False, f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9222"))
