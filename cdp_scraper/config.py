import dataclasses
import os
from dataclasses import dataclass, field
from typing import Optional

from . import logs

ENGINES = ("auto", "patchright", "playwright")


@dataclass(frozen=True)
class CDPConfig:
    """Konfigurasi koneksi CDP. Immutable, bisa dibuat banyak (satu per platform).

    transport: 'playwright' (default) | 'raw' (CDP mentah via websocket, alias 'websocket'/'cdp')
               | 'auto' (Playwright, jatuh ke raw bila ditolak browser) | nama transport custom.
    engine: pilihan library untuk transport playwright ('auto' | 'patchright' | 'playwright').
    cdp_url: 'http://host:port' (tab dicari lewat /json) atau, khusus raw,
             'ws://host:port/devtools/page/<id>' (dipakai langsung).
    auth_token: dikirim sebagai 'Authorization: Bearer ...' (mis. CDP_AUTH_TOKEN milik Anoa).
    target: raw saja. 'first' = tab pertama yang ada, 'new' = buat tab baru (/json/new),
            selain itu = id / potongan url / judul tab.
    focus_emulation: raw saja. True = kirim Emulation.setFocusEmulationEnabled agar tab dianggap fokus
            (membantu infinite scroll di tab latar belakang; belum tentu didukung semua browser).
    rewrite_ws_host: raw saja. Ganti host:port di webSocketDebuggerUrl dengan host:port cdp_url
            (server di belakang socat/Docker sering mengembalikan 127.0.0.1:9223).
    """

    cdp_url: str = "http://localhost:9222"
    timezone: Optional[str] = "Asia/Jakarta"
    lock_timeout: float = 30
    max_sessions: int = 5
    engine: str = "auto"
    transport: str = "playwright"
    auth_token: Optional[str] = field(default=None, repr=False)
    target: str = "first"
    rewrite_ws_host: bool = True
    focus_emulation: bool = False
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
        if not isinstance(self.transport, str) or not self.transport:
            raise ValueError("transport harus berupa nama (str), mis. 'playwright' atau 'raw'")

    def replace(self, **changes):
        return dataclasses.replace(self, **changes)

    @classmethod
    def from_env(cls, prefix="", environ=None):
        """Baca CDP_URL, BROWSER_TIMEZONE, LOCK_WAIT_TIMEOUT, MAX_CONCURRENT_SESSIONS, CDP_ENGINE,
        CDP_TRANSPORT, CDP_AUTH_TOKEN, CDP_TARGET (opsional dengan prefix, mis. 'TWITTER_' -> TWITTER_CDP_URL)."""
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
            transport=pick("CDP_TRANSPORT", str, base.transport),
            auth_token=pick("CDP_AUTH_TOKEN", str, base.auth_token),
            target=pick("CDP_TARGET", str, base.target),
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
