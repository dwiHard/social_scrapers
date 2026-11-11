"""Sesi browser via CDP: satu tab per request + batas sesi bersamaan."""
import asyncio
import importlib
import threading
from contextlib import asynccontextmanager

from ..config import get_default_config
from ..errors import BrowserBusy
from ..logs import get_logger
from .state import LAST_DIAG


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
        f"Engine browser tidak tersedia ({'/'.join(names)}). Install: pip install playwright"
    ) from last_error


class CDPSessionManager:
    """Mengelola slot sesi untuk satu konfigurasi CDP.

    engine_factory: opsional, callable seperti `async_playwright` (berguna untuk test/engine custom).
    """

    def __init__(self, config=None, log=None, engine_factory=None):
        self.config = config or get_default_config()
        self.log = log or get_logger()
        self.engine = "custom" if engine_factory else None
        self._factory = engine_factory
        self._slots = threading.BoundedSemaphore(self.config.max_sessions)
        self._count_lock = threading.Lock()
        self._active = 0

    @property
    def active(self):
        return self._active

    @property
    def is_busy(self):
        return self._active >= self.config.max_sessions

    def _engine_factory(self):
        if self._factory is None:
            self.engine, self._factory = load_engine(self.config.engine)
        return self._factory

    async def _acquire(self, timeout=None):
        timeout = self.config.lock_timeout if timeout is None else timeout
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not self._slots.acquire(blocking=False):
            if loop.time() > deadline:
                raise BrowserBusy("Browser sedang sibuk, coba lagi nanti")
            await asyncio.sleep(0.5)

    @asynccontextmanager
    async def session(self, log=None):
        """Yield page baru (tab sendiri) yang ditutup saat selesai."""
        log = log or self.log
        cfg = self.config
        factory = self._engine_factory()
        log.info("Menunggu giliran browser (lock)...")
        await self._acquire()
        with self._count_lock:
            self._active += 1
        try:
            async with factory() as p:
                log.info(f"Menghubungkan ke CDP di {cfg.cdp_url} ({self.engine})...")
                LAST_DIAG["engine"] = f"{self.engine} (connect_over_cdp)"
                browser = await p.chromium.connect_over_cdp(cfg.cdp_url)

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
        finally:
            with self._count_lock:
                self._active -= 1
            self._slots.release()


_managers = {}
_managers_lock = threading.Lock()


def get_manager(config=None, log=None):
    """Manager ter-cache per konfigurasi; konfigurasi sama = slot sama."""
    config = config or get_default_config()
    with _managers_lock:
        manager = _managers.get(config)
        if manager is None:
            manager = _managers[config] = CDPSessionManager(config, log=log)
        return manager


def default_manager():
    return get_manager(get_default_config())


def playwright_session():
    return default_manager().session()


def is_browser_busy():
    return default_manager().is_busy
