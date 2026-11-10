class CDPError(Exception):
    """Base error semua exception di cdp_scraper."""


class PageCrashed(CDPError, RuntimeError):
    """Tab Chrome crash (Target crashed)."""


class BrowserBusy(CDPError, TimeoutError):
    """Semua slot sesi browser terpakai sampai batas waktu tunggu habis."""
