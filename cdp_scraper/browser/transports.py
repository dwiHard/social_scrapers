"""Transport: cara library ini berbicara dengan browser.

- ``playwright`` : Playwright/Patchright `connect_over_cdp` (default, paling lengkap).
- ``raw``        : CDP mentah lewat websocket ke satu tab (alias: ``websocket``, ``cdp``).
                   Untuk browser yang CDP-nya terbatas, mis. Qt WebEngine / Anoa, yang menolak
                   ``Browser.setDownloadBehavior`` sehingga Playwright gagal connect.
- ``auto``       : coba Playwright dulu; kalau ditolak / tidak terpasang, pindah ke ``raw``.

Transport sendiri bisa ditambah dengan ``register_transport(nama, factory)``.
"""
import asyncio
import importlib
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import AsyncExitStack, asynccontextmanager

from ..errors import BrowserBusy
from ..logs import get_logger
from .rawpage import CDPConnection, RawPage

ALIASES = {"websocket": "raw", "ws": "raw", "cdp": "raw"}


# ---- helper HTTP/URL (sinkron, dijalankan di executor) ----------------------------------------

def auth_headers(config):
    return {"Authorization": f"Bearer {config.auth_token}"} if config.auth_token else {}


def _http_json(url, headers=None, timeout=5.0, method="GET"):
    request = urllib.request.Request(url, headers=headers or {}, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_ok(url, headers=None, timeout=5.0):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()


def _http_base(cdp_url):
    if "://" not in cdp_url:
        cdp_url = "http://" + cdp_url
    parts = urllib.parse.urlsplit(cdp_url)
    scheme = {"ws": "http", "wss": "https"}.get(parts.scheme, parts.scheme)
    return scheme, parts.netloc


def _ws_scheme(http_scheme):
    return "wss" if http_scheme == "https" else "ws"


def _is_direct_page_ws(cdp_url):
    parts = urllib.parse.urlsplit(cdp_url)
    return parts.scheme in ("ws", "wss") and parts.path.startswith("/devtools/page/")


def _pick_target(targets, wanted):
    pages = [t for t in targets if isinstance(t, dict) and t.get("type") == "page"
             and t.get("webSocketDebuggerUrl")]
    if wanted not in ("first", "new", None, ""):
        matched = [t for t in pages if wanted == t.get("id") or wanted in t.get("url", "")
                   or wanted in t.get("title", "")]
        if not matched:
            raise LookupError(f"Tab dengan id/url/judul '{wanted}' tidak ditemukan "
                              f"(ada {len(pages)} tab)")
        return matched[0]
    if not pages:
        raise LookupError("Tidak ada tab (type=page) di server CDP")
    return pages[0]


def resolve_page_target(config, log):
    """Kembalikan (ws_url, target_id, owns). Sinkron: pakai di executor.

    - ``cdp_url`` berupa ``ws://host:port/devtools/page/<id>``  -> dipakai langsung.
    - selain itu  -> GET /json (``/json/list``), pilih tab sesuai ``config.target``;
      host:port di URL websocket diganti agar sesuai ``cdp_url`` (server di belakang
      socat/Docker sering mengembalikan ``127.0.0.1:9223``).
    """
    if _is_direct_page_ws(config.cdp_url):
        return config.cdp_url, config.cdp_url.rsplit("/", 1)[-1], False

    scheme, netloc = _http_base(config.cdp_url)
    base = f"{scheme}://{netloc}"
    headers = auth_headers(config)
    owns = False
    target = None
    if config.target == "new":
        for method in ("PUT", "GET"):                 # Chrome >= 111 mewajibkan PUT
            try:
                target = _http_json(f"{base}/json/new?about:blank", headers, method=method)
                owns = True
                break
            except Exception as e:
                log.debug(f"/json/new via {method}: {e}")
        if target is None:
            log.warning("Browser tidak bisa membuat tab baru lewat /json/new, memakai tab yang ada.")
    if target is None:
        try:
            targets = _http_json(f"{base}/json", headers)
        except urllib.error.HTTPError:
            targets = _http_json(f"{base}/json/list", headers)
        target = _pick_target(targets, config.target)

    ws_url = target["webSocketDebuggerUrl"]
    if config.rewrite_ws_host:
        parts = urllib.parse.urlsplit(ws_url)
        ws_url = urllib.parse.urlunsplit((_ws_scheme(scheme), netloc, parts.path, parts.query, ""))
    return ws_url, target.get("id"), owns


# ---- transport -----------------------------------------------------------------------------

class Transport:
    """Kontrak transport. Subclass cukup mengimplementasi `page()` dan (opsional) `deep_check()`."""

    name = "transport"
    engine = None

    def __init__(self, config):
        self.config = config

    @property
    def engine_label(self):
        return f"{self.engine or self.name}"

    @asynccontextmanager
    async def page(self, log):
        """Yield objek page (API ala Playwright) dan bersihkan saat selesai."""
        raise NotImplementedError
        yield  # pragma: no cover

    async def deep_check(self, timeout):
        raise NotImplementedError


def load_engine(preference="auto"):
    names = ("patchright", "playwright") if preference == "auto" else (preference,)
    last_error = None
    for name in names:
        try:
            module = importlib.import_module(f"{name}.async_api")
            return name, module.async_playwright
        except ImportError as e:
            last_error = e
    raise ImportError(
        f"Engine browser tidak tersedia ({'/'.join(names)}). Install: pip install playwright "
        "atau pakai transport='raw'"
    ) from last_error


class PlaywrightTransport(Transport):
    name = "playwright"

    def __init__(self, config, engine_factory=None):
        super().__init__(config)
        self._factory = engine_factory
        self.engine = "custom" if engine_factory else None

    def _engine_factory(self):
        if self._factory is None:
            self.engine, self._factory = load_engine(self.config.engine)
        return self._factory

    @property
    def engine_label(self):
        return f"{self.engine} (connect_over_cdp)"

    def _connect_kwargs(self):
        headers = auth_headers(self.config)
        return {"headers": headers} if headers else {}

    async def deep_check(self, timeout):
        try:
            factory = self._engine_factory()
            async with factory() as p:
                browser = await asyncio.wait_for(
                    p.chromium.connect_over_cdp(self.config.cdp_url, **self._connect_kwargs()), timeout)
                return {"connected": True, "contexts": len(browser.contexts), "error": None}
        except asyncio.TimeoutError:
            return {"connected": False, "contexts": None, "error": f"timeout setelah {timeout:g} detik"}
        except Exception as e:
            return {"connected": False, "contexts": None, "error": str(e) or e.__class__.__name__}

    @asynccontextmanager
    async def page(self, log):
        cfg = self.config
        factory = self._engine_factory()
        async with factory() as p:
            log.info(f"Menghubungkan ke CDP di {cfg.cdp_url} ({self.engine})...")
            browser = await p.chromium.connect_over_cdp(cfg.cdp_url, **self._connect_kwargs())

            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await context.new_page()
            if cfg.bring_to_front:
                await page.bring_to_front()

            client = None
            try:
                try:
                    client = await context.new_cdp_session(page)
                    await client.send("Network.enable")
                    if cfg.timezone:
                        try:
                            await client.send("Emulation.setTimezoneOverride",
                                              {"timezoneId": cfg.timezone})
                        except Exception as e:
                            log.debug(f"timezone override: {e}")
                except Exception as e:
                    log.warning(f"Gagal setup CDP: {e}")

                yield page
            finally:
                if client is not None:
                    try:
                        await asyncio.wait_for(client.detach(), timeout=3.0)
                    except Exception as e:
                        log.debug(f"detach: {e}")
                try:
                    await asyncio.wait_for(page.close(), timeout=3.0)
                except asyncio.TimeoutError:
                    log.warning("Penutupan tab terlalu lama (diabaikan).")
                except Exception as e:
                    log.debug(f"page.close: {e}")
                log.info("Sesi CDP selesai, koneksi diputus.")


_target_locks = {}
_target_locks_guard = threading.Lock()


def _target_lock(key):
    with _target_locks_guard:
        return _target_locks.setdefault(key, threading.Lock())


class RawCDPTransport(Transport):
    """CDP mentah: satu websocket level-halaman, tanpa Playwright."""

    name = "raw"
    engine = "raw-cdp"

    @property
    def engine_label(self):
        return "raw-cdp (websocket)"

    async def _resolve(self, log):
        return await asyncio.get_running_loop().run_in_executor(
            None, resolve_page_target, self.config, log)

    async def deep_check(self, timeout):
        try:
            async def probe():
                ws_url, _id, _owns = await self._resolve(get_logger())
                conn = await CDPConnection.open(ws_url, headers=auth_headers(self.config), timeout=timeout)
                try:
                    await conn.send("Runtime.evaluate", {"expression": "1+1"}, timeout=timeout)
                finally:
                    await conn.close()
            await asyncio.wait_for(probe(), timeout)
            return {"connected": True, "contexts": None, "error": None}
        except asyncio.TimeoutError:
            return {"connected": False, "contexts": None, "error": f"timeout setelah {timeout:g} detik"}
        except Exception as e:
            return {"connected": False, "contexts": None, "error": str(e) or e.__class__.__name__}

    @asynccontextmanager
    async def page(self, log):
        cfg = self.config
        ws_url, target_id, owns = await self._resolve(log)

        lock = None
        if not owns:       # tab yang dipakai bersama tidak boleh dipakai dua sesi sekaligus
            lock = _target_lock((ws_url.split("//", 1)[-1]))
            loop = asyncio.get_running_loop()
            deadline = loop.time() + cfg.lock_timeout
            while not lock.acquire(blocking=False):
                if loop.time() > deadline:
                    raise BrowserBusy("Tab browser (raw CDP) sedang dipakai sesi lain")
                await asyncio.sleep(0.2)
        page = None
        try:
            log.info(f"Menghubungkan ke CDP mentah di {ws_url}...")
            conn = await CDPConnection.open(ws_url, headers=auth_headers(cfg), log=log)
            scheme, netloc = _http_base(cfg.cdp_url)

            async def closer():
                await asyncio.get_running_loop().run_in_executor(
                    None, lambda: _http_ok(f"{scheme}://{netloc}/json/close/{target_id}", auth_headers(cfg)))

            page = RawPage(conn, log=log, target_id=target_id, owns_target=owns, closer=closer)
            await page.setup(timezone=cfg.timezone, bring_to_front=cfg.bring_to_front)
            yield page
        finally:
            if page is not None:
                try:
                    await asyncio.wait_for(page.close(), timeout=5.0)
                except Exception as e:
                    log.debug(f"raw page.close: {e}")
                log.info("Sesi CDP mentah selesai.")
            if lock is not None:
                lock.release()


_FALLBACK_HINTS = ("not supported", "protocol error", "browser context management",
                   "setdownloadbehavior", "setautoattach", "engine browser tidak tersedia")


class AutoTransport(Transport):
    """Playwright dulu; bila ditolak browser (atau tidak terpasang) otomatis pindah ke raw."""

    name = "auto"

    def __init__(self, config, engine_factory=None):
        super().__init__(config)
        self.primary = PlaywrightTransport(config, engine_factory)
        self.fallback = RawCDPTransport(config)
        self._use_fallback = False

    @property
    def active(self):
        return self.fallback if self._use_fallback else self.primary

    @property
    def engine(self):
        return self.active.engine

    @property
    def engine_label(self):
        return self.active.engine_label

    @staticmethod
    def _should_fallback(error):
        if isinstance(error, ImportError):
            return True
        text = str(error).lower()
        return any(hint in text for hint in _FALLBACK_HINTS)

    async def deep_check(self, timeout):
        if self._use_fallback:
            return await self.fallback.deep_check(timeout)
        report = await self.primary.deep_check(timeout)
        if not report["connected"] and self._should_fallback(RuntimeError(report["error"] or "")):
            return await self.fallback.deep_check(timeout)
        return report

    @asynccontextmanager
    async def page(self, log):
        async with AsyncExitStack() as stack:
            if self._use_fallback:
                page = await stack.enter_async_context(self.fallback.page(log))
            else:
                try:
                    page = await stack.enter_async_context(self.primary.page(log))
                except Exception as e:
                    if not self._should_fallback(e):
                        raise
                    self._use_fallback = True
                    log.warning(f"Playwright ditolak browser ({str(e).splitlines()[0][:120]}); "
                                "beralih ke transport raw CDP.")
                    page = await stack.enter_async_context(self.fallback.page(log))
            yield page


# ---- registry ------------------------------------------------------------------------------

_registry = {
    "playwright": lambda config, engine_factory=None: PlaywrightTransport(config, engine_factory),
    "raw": lambda config, engine_factory=None: RawCDPTransport(config),
    "auto": lambda config, engine_factory=None: AutoTransport(config, engine_factory),
}


def register_transport(name, factory):
    """Daftarkan transport custom. factory(config) -> objek `Transport`
    (punya `page(log)` async context manager, `deep_check(timeout)`, `engine`, `engine_label`)."""
    _registry[name] = lambda config, engine_factory=None: factory(config)


def list_transports():
    return sorted(_registry)


def create_transport(config, engine_factory=None):
    name = ALIASES.get(config.transport, config.transport)
    if engine_factory is not None and name == "raw":
        raise ValueError("engine_factory hanya untuk transport playwright/auto")
    try:
        factory = _registry[name]
    except KeyError:
        raise ValueError(f"transport '{config.transport}' tidak dikenal "
                         f"(tersedia: {', '.join(list_transports())}, alias: {', '.join(ALIASES)})") from None
    return factory(config, engine_factory)
