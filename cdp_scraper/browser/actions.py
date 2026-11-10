"""Aksi halaman yang bisa dirakit per platform: tutup overlay, scroll, tunggu elemen."""
from ..logs import get_logger

_SCROLL_JS = """(o) => {
    if (o.window === 'bottom') window.scrollTo(0, document.documentElement.scrollHeight);
    else if (o.window === 'viewport') window.scrollBy(0, window.innerHeight * o.factor);
    if (o.containers) {
        for (const el of document.querySelectorAll('div')) {
            const st = getComputedStyle(el);
            if ((st.overflowY === 'auto' || st.overflowY === 'scroll')
                && el.scrollHeight > el.clientHeight + 50) {
                el.scrollTop = el.scrollHeight;
            }
        }
    }
    if (o.pattern) {
        const re = new RegExp(o.pattern, 'i');
        const btn = [...document.querySelectorAll('button, [role="button"]')]
            .find(b => re.test((b.innerText || '').trim()));
        if (btn) btn.click();
    }
}"""


async def close_overlays(page, selectors):
    """Klik tombol penutup popup/modal (selector CSS diberikan platform)."""
    if not selectors:
        return
    try:
        await page.evaluate(
            "(sels) => document.querySelectorAll(sels.join(',')).forEach(b => b.click())",
            list(selectors))
    except Exception:
        pass


async def scroll_page_down(page):
    await page.keyboard.press("PageDown")


def make_scroller(*, wheel=2500, window_scroll="bottom", viewport_factor=2.0,
                  containers=False, click_pattern=None, mouse=(0.5, 0.5), key=None):
    """Bangun fungsi scroll generik.

    wheel: delta mouse wheel (0 = nonaktif); window_scroll: 'bottom' | 'viewport' | None;
    containers: scroll semua div overflow; click_pattern: regex teks tombol 'load more'/'retry';
    mouse: posisi kursor (fraksi viewport); key: tombol keyboard tambahan (mis. 'End').
    """
    options = {"window": window_scroll, "factor": viewport_factor,
               "containers": containers, "pattern": click_pattern}
    use_js = bool(window_scroll or containers or click_pattern)

    async def _scroll(page):
        if wheel:
            vp = page.viewport_size or {"width": 1280, "height": 800}
            await page.mouse.move(vp["width"] * mouse[0], vp["height"] * mouse[1])
            await page.mouse.wheel(0, wheel)
        if use_js:
            await page.evaluate(_SCROLL_JS, options)
        if key:
            await page.keyboard.press(key)

    return _scroll


def make_wait_for(selector, timeout_ms=15000, message=None):
    """Fungsi prepare: tunggu elemen pertama muncul (hanya warning jika tidak muncul)."""
    async def _wait(page, log=None):
        log = log or get_logger()
        try:
            await page.wait_for_selector(selector, state="attached", timeout=timeout_ms)
        except Exception:
            log.warning(message or f"Elemen '{selector}' belum muncul setelah {timeout_ms // 1000} detik.")
    return _wait
