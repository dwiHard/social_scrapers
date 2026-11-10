import asyncio
from types import SimpleNamespace


class FakeResponse:
    def __init__(self, url, payload, status=200, method="GET"):
        self.url = url
        self.status = status
        self.request = SimpleNamespace(method=method)
        self._payload = payload

    async def json(self):
        return self._payload


class FakePage:
    """Page palsu: tiap goto/scroll memancarkan satu payload dari `batches`."""

    def __init__(self, batches=(), api_url="https://site.test/api/list?x=1"):
        self.url = "https://site.test/"
        self.viewport_size = {"width": 1280, "height": 800}
        self.batches = list(batches)
        self.api_url = api_url
        self.handlers = {}
        self.closed = False
        self.shots = []
        self.keyboard = SimpleNamespace(press=self._noop)

    async def _noop(self, *a, **k):
        return None

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        self.handlers[event].remove(handler)

    async def emit_next(self):
        payload = self.batches.pop(0) if self.batches else {"items": [], "has_more": 0}
        for handler in list(self.handlers.get("response", [])):
            await handler(FakeResponse(self.api_url, payload))

    async def goto(self, url, **kwargs):
        self.url = url
        await self.emit_next()
        return SimpleNamespace(status=200)

    async def title(self):
        return "fake"

    async def evaluate(self, *a, **k):
        return {}

    async def inner_text(self, *a, **k):
        return ""

    async def screenshot(self, path=None, **k):
        self.shots.append(path)

    async def bring_to_front(self):
        pass

    async def close(self):
        self.closed = True


async def scroll_emit(page):
    await page.emit_next()


class FakeContext:
    def __init__(self, batches=()):
        self.pages_made = []
        self.batches = list(batches)

    async def new_page(self):
        page = FakePage(self.batches)
        self.pages_made.append(page)
        return page

    async def new_cdp_session(self, page):
        raise RuntimeError("tanpa cdp")


def fake_engine(context):
    class _PW:
        class chromium:
            @staticmethod
            async def connect_over_cdp(url):
                return SimpleNamespace(contexts=[context])

    class _Engine:
        async def __aenter__(self):
            return _PW

        async def __aexit__(self, *a):
            return False

    return lambda: _Engine()


FAST = dict(initial_sleep=0, poll_interval=0.01, settle=0, final_sleep=0, max_wait=0.05)


def run(coro):
    return asyncio.run(coro)
