"""Deskripsi deklaratif sebuah platform sosial media dan endpoint-nya."""
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple, Union

from ..config import CDPConfig


class _QuotedParams(dict):
    def __getitem__(self, key):
        value = dict.__getitem__(self, key)
        return urllib.parse.quote("" if value is None else str(value), safe="")


@dataclass
class Endpoint:
    """Satu jenis scraping (search, user_videos, comments, ...).

    url: template 'https://site/search?q={keyword}' (nilai otomatis di-URL-encode)
         atau callable(**params) -> url.
    api_match: potongan URL API (str), regex, atau callable(url) -> bool.
    parser: callable(api_json) -> list[dict] (mis. FieldMapper).
    key: nama field / callable untuk de-duplikasi.
    params: nama parameter wajib; defaults: nilai bawaan; normalize/validate: hook parameter.
    end: callable(api_json) -> bool penanda data habis; scroll/prepare: hook halaman.
    capture_options: kwargs tambahan ke capture (poll_interval, settle, ...).
    """

    name: str
    url: Union[str, Callable[..., str]]
    api_match: Any
    parser: Callable[[Any], list]
    key: Union[str, Callable] = "id"
    params: Tuple[str, ...] = ()
    defaults: Dict[str, Any] = field(default_factory=dict)
    normalize: Optional[Callable[[dict], Optional[dict]]] = None
    validate: Optional[Callable[[dict], None]] = None
    end: Optional[Callable[[Any], bool]] = None
    scroll: Optional[Callable] = None
    prepare: Optional[Callable] = None
    limit: int = 20
    max_limit: Optional[int] = None
    max_scrolls: Union[int, Callable[[int], int]] = 8
    max_wait: float = 8.0
    stall_limit: int = 3
    initial_sleep: float = 5.0
    nav_timeout_ms: int = 60000
    label: Union[str, Callable[[dict], str], None] = None
    capture_options: Dict[str, Any] = field(default_factory=dict)

    def _check_required(self, merged):
        missing = [p for p in self.params if merged.get(p) in (None, "", [])]
        if missing:
            raise ValueError(f"Param wajib untuk endpoint '{self.name}': {', '.join(missing)}")

    def prepare_params(self, params):
        merged = dict(self.defaults)
        merged.update(params or {})
        self._check_required(merged)
        if self.normalize:
            merged = self.normalize(merged) or merged
            self._check_required(merged)
        if self.validate:
            self.validate(merged)
        return merged

    def build_url(self, params):
        if callable(self.url):
            return self.url(**params)
        try:
            return self.url.format_map(_QuotedParams(params))
        except KeyError as e:
            raise ValueError(f"Param '{e.args[0]}' dibutuhkan oleh URL endpoint '{self.name}'")

    def resolve_limit(self, limit=None):
        value = self.limit if limit is None else int(limit)
        if self.max_limit:
            value = min(value, self.max_limit)
        return max(1, value)

    def resolve_scrolls(self, limit):
        return self.max_scrolls(limit) if callable(self.max_scrolls) else self.max_scrolls

    def label_for(self, params):
        if callable(self.label):
            return str(self.label(params))
        key = self.label or (self.params[0] if self.params else None)
        return str(params.get(key, "")) if key else self.name


@dataclass
class Platform:
    """Platform = kumpulan endpoint + pengaturan browser khusus.

    cdp: CDPConfig atau dict override (mis. {'cdp_url': 'http://localhost:9223'}).
    overlay_selectors: selector popup/login modal yang ditutup otomatis.
    login_url_hints: potongan URL yang berarti browser belum login (mis. '/login').
    default_scroll: fungsi scroll bawaan semua endpoint platform ini.
    """

    name: str
    endpoints: Any = field(default_factory=dict)
    cdp: Union[CDPConfig, Dict[str, Any], None] = None
    overlay_selectors: Tuple[str, ...] = ()
    login_url_hints: Tuple[str, ...] = ()
    delay_between_runs: float = 0.0
    default_scroll: Optional[Callable] = None

    def __post_init__(self):
        if not isinstance(self.endpoints, dict):
            self.endpoints = {ep.name: ep for ep in self.endpoints}

    def endpoint(self, name):
        try:
            return self.endpoints[name]
        except KeyError:
            raise KeyError(f"Endpoint '{name}' tidak ada di platform '{self.name}' "
                           f"(tersedia: {', '.join(self.endpoints)})")


def end_when_falsy(path):
    """end_fn: data habis jika nilai pada path kosong/False (mis. 'has_more')."""
    from ..parsing.paths import get_path
    return lambda data: not get_path(data, path)


def end_when_empty(parser):
    """end_fn: data habis jika response tidak menghasilkan item."""
    return lambda data: not parser(data)
