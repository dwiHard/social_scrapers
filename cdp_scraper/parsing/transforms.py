"""Registry transform nilai untuk mapping. Spec: 'nama', 'nama:arg', callable, atau list (pipeline).

Contoh: 'int', 'str', 'url', 'iso_utc', 'iso_utc:%a %b %d %H:%M:%S %z %Y', 'each:url'.
"""
from datetime import datetime, timezone

from ..utils.utils import (clean_text, normalize_hashtag, normalize_username,
                           safe_float, safe_int, safe_str, validate_url)

_REGISTRY = {}


def register_transform(name, fn=None, takes_arg=False):
    """Daftarkan transform. fn(value) atau, bila takes_arg=True, fn(value, arg)."""
    def _register(func):
        _REGISTRY[name] = func if takes_arg else (lambda value, arg=None: func(value))
        return func
    return _register(fn) if fn is not None else _register


def _as_list(value):
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _to_datetime(value, fmt=None):
    if value in (None, ""):
        return None
    if fmt:
        try:
            parsed = datetime.strptime(str(value), fmt)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not number:
        return None
    if number > 1e11:
        number /= 1000.0
    try:
        return datetime.fromtimestamp(number, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _iso_utc(value, arg=None):
    dt = _to_datetime(value, arg)
    return dt.isoformat().replace("+00:00", "Z") if dt else None


def _date_id(value, arg=None):
    dt = _to_datetime(value, arg)
    return dt.strftime("%Y-%m-%d") if dt else None


def _first(value, arg=None):
    for item in _as_list(value):
        if item not in (None, "", [], {}):
            return item
    return None


def _unique(value, arg=None):
    out = []
    for item in _as_list(value):
        if item not in out:
            out.append(item)
    return out


_BUILTINS = {
    "int": lambda v, a=None: safe_int(v),
    "float": lambda v, a=None: safe_float(v),
    "str": lambda v, a=None: safe_str(v),
    "bool": lambda v, a=None: bool(v),
    "url": lambda v, a=None: validate_url(v),
    "lower": lambda v, a=None: None if v is None else str(v).lower(),
    "upper": lambda v, a=None: None if v is None else str(v).upper(),
    "strip": lambda v, a=None: None if v is None else str(v).strip(),
    "clean_text": lambda v, a=None: clean_text(v),
    "username": lambda v, a=None: normalize_username(v),
    "hashtag": lambda v, a=None: normalize_hashtag(v),
    "iso_utc": _iso_utc,
    "date_id": _date_id,
    "join": lambda v, a=None: (a if a is not None else ",").join(str(x) for x in _as_list(v)),
    "first": _first,
    "count": lambda v, a=None: len(v) if isinstance(v, (list, tuple, str, dict)) else 0,
    "unique": _unique,
    "drop_empty": lambda v, a=None: [x for x in _as_list(v) if x not in (None, "", [], {})],
}
_REGISTRY.update(_BUILTINS)


def get_transform(spec):
    """Ubah spec menjadi callable(value). Error langsung saat dibuat (fail fast)."""
    if callable(spec):
        return spec
    if isinstance(spec, (list, tuple)):
        steps = [get_transform(s) for s in spec]

        def pipeline(value):
            for step in steps:
                value = step(value)
            return value
        return pipeline
    if not isinstance(spec, str):
        raise TypeError(f"Spec transform tidak valid: {spec!r}")

    name, _, arg = spec.partition(":")
    arg = arg if ":" in spec else None
    if name == "each":
        inner = get_transform(arg or "str")
        return lambda value: [r for r in (inner(i) for i in _as_list(value)) if r not in (None, "")]
    if name not in _REGISTRY:
        raise ValueError(f"Transform tidak dikenal: {name!r} (tersedia: {', '.join(sorted(_REGISTRY))}, each)")
    func = _REGISTRY[name]
    return lambda value: func(value, arg)
