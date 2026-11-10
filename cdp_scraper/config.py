import dataclasses
import os
from dataclasses import dataclass
from typing import Optional

from . import logs

ENGINES = ("auto", "patchright", "playwright")


@dataclass(frozen=True)
class CDPConfig:
    """Konfigurasi koneksi CDP. Immutable, bisa dibuat banyak (satu per platform)."""

    cdp_url: str = "http://localhost:9222"
    timezone: Optional[str] = "Asia/Jakarta"
    lock_timeout: float = 30
    max_sessions: int = 5
    engine: str = "auto"
    bring_to_front: bool = True
    debug_screenshots: bool = True
    debug_dir: Optional[str] = None

    def __post_init__(self):
        if self.max_sessions < 1:
            raise ValueError("max_sessions minimal 1")
        if self.lock_timeout < 0:
            raise ValueError("lock_timeout tidak boleh negatif")
        if self.engine not in ENGINES:
            raise ValueError(f"engine harus salah satu dari {ENGINES}")

    def replace(self, **changes):
        return dataclasses.replace(self, **changes)

    @classmethod
    def from_env(cls, prefix="", environ=None):
        """Baca CDP_URL, BROWSER_TIMEZONE, LOCK_WAIT_TIMEOUT, MAX_CONCURRENT_SESSIONS
        (opsional dengan prefix, mis. 'TWITTER_' -> TWITTER_CDP_URL)."""
        env = os.environ if environ is None else environ
        base = cls()

        def pick(name, cast, default):
            raw = env.get(prefix + name)
            return default if raw in (None, "") else cast(raw)

        return cls(
            cdp_url=pick("CDP_URL", str, base.cdp_url),
            timezone=pick("BROWSER_TIMEZONE", str, base.timezone),
            lock_timeout=pick("LOCK_WAIT_TIMEOUT", float, base.lock_timeout),
            max_sessions=pick("MAX_CONCURRENT_SESSIONS", int, base.max_sessions),
            engine=pick("CDP_ENGINE", str, base.engine),
        )


_default = CDPConfig()


def get_default_config():
    return _default


def set_default_config(config):
    global _default
    _default = config
    return _default


def setup_cdp(cdp_url=None, timezone=None, lock_timeout=None, max_sessions=None,
              custom_logger=None, **extra):
    """Atur konfigurasi default (kompatibel dengan versi 0.1.x)."""
    changes = {k: v for k, v in {
        "cdp_url": cdp_url, "timezone": timezone,
        "lock_timeout": lock_timeout, "max_sessions": max_sessions,
    }.items() if v is not None}
    changes.update(extra)
    config = set_default_config(_default.replace(**changes))
    if custom_logger is not None:
        logs.set_base_logger(custom_logger)
    return config
