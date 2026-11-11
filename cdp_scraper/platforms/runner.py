"""Scraper generik: menjalankan endpoint platform apa pun."""
import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..browser.actions import close_overlays, scroll_page_down
from ..browser.capture import capture
from ..browser.diagnostics import DebugOptions
from ..browser.session import get_manager
from ..config import get_default_config
from ..errors import PageCrashed
from ..parsing.registry import get_mapper
from ..logs import get_logger
from .registry import get_platform


@dataclass
class ScrapeResult:
    label: str
    items: List[Any] = field(default_factory=list)
    status: str = "success"
    error: Optional[str] = None
    stopped_by: Optional[str] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    @property
    def count(self):
        return len(self.items)

    def to_dict(self, label_key="keyword"):
        return {"data": self.items, label_key: self.label,
                "keyword_status": 1 if self.items else 0,
                "results_count": self.count, "status": self.status}


class Scraper:
    """Jalankan endpoint sebuah Platform (objek atau nama terdaftar).

    run(): satu parameter, exception diteruskan (PageCrashed, BrowserBusy, ValueError, ...).
    run_many(): banyak parameter dalam satu tab; error per item jadi status 'error'.
    """

    def __init__(self, platform, manager=None, log=None):
        self.platform = get_platform(platform) if isinstance(platform, str) else platform
        self.log = (log or get_logger()).bind(self.platform.name)
        if manager is None:
            cfg = self.platform.cdp
            if isinstance(cfg, dict):
                cfg = get_default_config().replace(**cfg)
            manager = get_manager(cfg or get_default_config())
        self.manager = manager

    def _prepare_hook(self, endpoint):
        platform = self.platform

        async def prepare(page):
            if any(hint in page.url for hint in platform.login_url_hints):
                self.log.error("Browser belum login ke platform ini, hasil tidak akan muncul")
                return
            if platform.overlay_selectors:
                await close_overlays(page, platform.overlay_selectors)
                await asyncio.sleep(1)
            if endpoint.prepare:
                await endpoint.prepare(page)

        return prepare

    def _scroll_hook(self, endpoint):
        base = endpoint.scroll or self.platform.default_scroll or scroll_page_down
        selectors = self.platform.overlay_selectors
        if not selectors:
            return base

        async def scroll(page):
            await close_overlays(page, selectors)
            await base(page)

        return scroll

    async def _run_one(self, page, endpoint, params, limit):
        cfg = self.manager.config
        lim = endpoint.resolve_limit(limit)
        diag = {"engine": f"{self.manager.engine} (connect_over_cdp)"}
        parser = get_mapper(endpoint.parser) if isinstance(endpoint.parser, str) else endpoint.parser
        options = dict(
            max_scrolls=endpoint.resolve_scrolls(lim), max_wait=endpoint.max_wait,
            stall_limit=endpoint.stall_limit, initial_sleep=endpoint.initial_sleep,
            scroll_fn=self._scroll_hook(endpoint), prepare_fn=self._prepare_hook(endpoint),
            end_fn=endpoint.end, nav_timeout_ms=endpoint.nav_timeout_ms,
            log=self.log, diag=diag,
            debug=DebugOptions(cfg.debug_screenshots, cfg.debug_dir))
        options.update(endpoint.capture_options)
        result = await capture(page, endpoint.build_url(params), endpoint.api_match,
                               parser, endpoint.key, lim, **options)
        return ScrapeResult(label=endpoint.label_for(params), items=result.items,
                            status="success" if result.items else "no_data",
                            stopped_by=result.stopped_by, diagnostics=result.diagnostics)

    async def run(self, endpoint, params=None, limit=None):
        ep = self.platform.endpoint(endpoint)
        prepared = ep.prepare_params(params)
        async with self.manager.session(log=self.log) as page:
            return await self._run_one(page, ep, prepared, limit)

    async def run_many(self, endpoint, params_list, limit=None):
        ep = self.platform.endpoint(endpoint)
        prepared = [ep.prepare_params(p) for p in params_list]
        results = []
        crashed = False
        async with self.manager.session(log=self.log) as page:
            for idx, params in enumerate(prepared):
                label = ep.label_for(params)
                if crashed:
                    results.append(ScrapeResult(label, status="error", error="tab crash pada item sebelumnya"))
                    continue
                if idx and self.platform.delay_between_runs:
                    await asyncio.sleep(self.platform.delay_between_runs)
                try:
                    results.append(await self._run_one(page, ep, params, limit))
                except PageCrashed as e:
                    crashed = True
                    results.append(ScrapeResult(label, status="error", error=str(e)))
                except Exception as e:
                    self.log.error(f"Gagal scrape '{label}'", exc_info=True)
                    results.append(ScrapeResult(label, status="error", error=str(e)))
        return results
