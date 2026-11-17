"""Sesi browser via CDP: satu tab per request + batas sesi bersamaan."""
import asyncio
import functools
import threading
from contextlib import asynccontextmanager

from ..config import get_default_config
from ..errors import BrowserBusy
from ..health import check_cdp
from ..logs import get_logger
from .state import LAST_DIAG
from .transports import auth_headers, create_transport, load_engine  # noqa: F401  (load_engine: kompatibilitas)


class CDPSessionManager:
    """Mengelola slot sesi untuk satu konfigurasi CDP.

    Cara bicara ke browser ditentukan `config.transport` (lihat `transports.py`):
    playwright | raw | auto | transport custom.
    engine_factory: opsional, callable seperti `async_playwright` (berguna untuk test/engine custom).
    transport: opsional, objek Transport siap pakai (menimpa config.transport).
    """

    def __init__(self, config=None, log=None, engine_factory=None, transport=None):
        self.config = config or get_default_config()
        self.log = log or get_logger()
        self.transport = transport or create_transport(self.config, engine_factory)
        self._slots = threading.BoundedSemaphore(self.config.max_sessions)
        self._count_lock = threading.Lock()
        self._active = 0

    @property
    def engine(self):
        return self.transport.engine

    @property
    def engine_label(self):
        return self.transport.engine_label

    @property
    def active(self):
        return self._active

    @property
    def is_busy(self):
        return self._active >= self.config.max_sessions

    def _sessions(self):
        return {"active": self._active, "max": self.config.max_sessions, "busy": self.is_busy}

    def health_sync(self, timeout=3.0, tabs=False):
        """Status koneksi CDP + slot sesi (sinkron, HTTP saja; cocok untuk route Flask sync)."""
        return {**check_cdp(self.config.cdp_url, timeout=timeout, tabs=tabs,
                            headers=auth_headers(self.config)),
                "sessions": self._sessions(), "engine": self.engine}

    async def health(self, timeout=3.0, deep=False, tabs=False):
        """Apakah sudah terhubung ke server CDP. `deep=True` sekaligus mencoba koneksi sungguhan
        lewat transport yang dipakai (tanpa membuka tab baru) untuk memastikan benar-benar bisa dipakai."""
        loop = asyncio.get_running_loop()
        report = await loop.run_in_executor(
            None, functools.partial(self.health_sync, timeout=timeout, tabs=tabs))
        if deep and report["connected"]:
            report["deep"] = await self.transport.deep_check(timeout)
            if not report["deep"]["connected"]:
                report["connected"], report["error"] = False, report["deep"]["error"]
            report["engine"] = self.engine
        return report

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
        """Yield page baru yang ditutup saat selesai (API ala Playwright, apa pun transport-nya)."""
        log = log or self.log
        log.info("Menunggu giliran browser (lock)...")
        await self._acquire()
        with self._count_lock:
            self._active += 1
        try:
            async with self.transport.page(log) as page:
                LAST_DIAG["engine"] = self.engine_label
                yield page
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
