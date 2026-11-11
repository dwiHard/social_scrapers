"""Mapping deklaratif response JSON -> list dict, tanpa menulis parser per platform."""
import copy
import importlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple

from ..logs import get_logger
from .paths import MISSING, resolve
from .registry import get_mapper, register_mapper
from .transforms import get_transform


class _Exists:
    def __repr__(self):
        return "EXISTS"


EXISTS = _Exists()
_BLANK = (None, "", [], {})
_SKIP = object()
_TEMPLATE_RE = re.compile(r"\{([^{}]+)\}")


@dataclass(frozen=True)
class FieldSpec:
    path: Optional[str] = None
    any_of: Tuple[str, ...] = ()
    template: Optional[str] = None
    constant: Any = MISSING
    fn: Optional[Callable] = None
    default: Any = None
    transform: Any = None
    required: bool = False


def F(path=None, *, any_of=(), template=None, fn=None, default=None, transform=None, required=False):
    """Definisi satu field output.

    path: path di record; any_of: beberapa path, ambil yang pertama terisi;
    template: 'https://x/{user.name}/{id}'; fn: callable(record) -> nilai;
    default: dipakai jika kosong; transform: nama/callable/list; required: item dibuang jika kosong.
    """
    return FieldSpec(path=path, any_of=tuple(any_of), template=template, fn=fn,
                     default=default, transform=transform, required=required)


def const(value):
    return FieldSpec(constant=value)


def _normalize_spec(spec):
    if isinstance(spec, FieldSpec):
        return spec
    if isinstance(spec, str):
        return FieldSpec(path=spec)
    if isinstance(spec, dict):
        return F(**spec)
    if isinstance(spec, tuple) and spec and isinstance(spec[0], str):
        return F(spec[0],
                 transform=spec[1] if len(spec) > 1 else None,
                 default=spec[2] if len(spec) > 2 else None)
    if callable(spec):
        return FieldSpec(fn=spec)
    raise TypeError(f"Spec field tidak valid: {spec!r}")


def _render(template, record):
    def repl(match):
        value = resolve(record, match.group(1))
        return "" if value is MISSING or value is None else str(value)
    return _TEMPLATE_RE.sub(repl, template)


def _make_getter(spec):
    transform = get_transform(spec.transform) if spec.transform is not None else None
    default = spec.default

    def fallback():
        return copy.copy(default) if isinstance(default, (list, dict)) else default

    def getter(record):
        if spec.constant is not MISSING:
            return spec.constant
        value = MISSING
        if spec.fn is not None:
            value = spec.fn(record)
        elif spec.template is not None:
            value = _render(spec.template, record)
        elif spec.any_of:
            for path in spec.any_of:
                candidate = resolve(record, path)
                if candidate is not MISSING and candidate not in _BLANK:
                    value = candidate
                    break
        elif spec.path is not None:
            value = resolve(record, spec.path)

        if value is MISSING or value is None:
            return fallback()
        if transform is not None:
            value = transform(value)
            if value is None:
                return fallback()
        return value

    return getter


def _make_checker(where):
    if where is None:
        return None
    if callable(where):
        return where
    checks = list(where.items())

    def check(record):
        for path, expected in checks:
            value = resolve(record, path)
            if expected is EXISTS:
                ok = value is not MISSING and value not in _BLANK
            elif callable(expected):
                ok = bool(expected(None if value is MISSING else value))
            else:
                ok = value is not MISSING and value == expected
            if not ok:
                return False
        return True
    return check


class FieldMapper:
    """Callable(api_json) -> list[dict]; cocok sebagai `extract_fn` capture.

    items: path ke list item (str / list path / callable(json) -> iterable)
    fields: {nama_output: spec}; spec = 'path' | ('path','transform',default) | F(...) | const(x) | callable
    item_path: sub-path di tiap item yang berisi record sebenarnya (mis. 'item')
    where / record_where: filter sebelum / sesudah item_path+unwrap ({path: nilai|EXISTS|callable} atau callable)
    unwrap: callable(record) -> record (mis. membuka pembungkus 'tweet')
    """

    def __init__(self, items, fields, *, item_path=None, where=None, record_where=None,
                 unwrap=None, name="mapper", log=None):
        self.name = name
        self._log = log or get_logger(name)
        if callable(items):
            self._items_fn = items
            self._items_paths = ()
        else:
            self._items_fn = None
            self._items_paths = (items,) if isinstance(items, str) else tuple(items)
        self._item_path = item_path
        self._where = _make_checker(where)
        self._record_where = _make_checker(record_where)
        self._unwrap = unwrap
        self._getters = [(out, _make_getter(_normalize_spec(spec)), _normalize_spec(spec).required)
                         for out, spec in fields.items()]
        self._fields = dict(fields)
        self._options = {"items": items, "item_path": item_path, "where": where,
                         "record_where": record_where, "unwrap": unwrap, "name": name, "log": log}

    def _raw_items(self, data):
        if self._items_fn is not None:
            return list(self._items_fn(data) or [])
        out = []
        for path in self._items_paths:
            value = resolve(data, path)
            if value is MISSING or value is None:
                continue
            if isinstance(value, (list, tuple)):
                out.extend(value)
            elif isinstance(value, dict):
                out.append(value)
        return out

    def _map(self, record):
        result = {}
        for out, getter, required in self._getters:
            value = getter(record)
            if required and value in _BLANK:
                return _SKIP
            result[out] = value
        return result

    def __call__(self, data):
        if data is None:
            return []
        parsed = []
        for raw in self._raw_items(data):
            try:
                if self._where and not self._where(raw):
                    continue
                record = resolve(raw, self._item_path) if self._item_path else raw
                if record is MISSING:
                    continue
                if self._unwrap:
                    record = self._unwrap(record)
                if not isinstance(record, dict) or not record:
                    continue
                if self._record_where and not self._record_where(record):
                    continue
                mapped = self._map(record)
                if mapped is not _SKIP:
                    parsed.append(mapped)
            except Exception as e:
                self._log.warning(f"Gagal map item: {e}")
        return parsed

    @property
    def fields(self):
        return dict(self._fields)

    def extend(self, fields=None, *, remove=(), **options):
        """Mapper baru turunan dari ini: tambah/timpa `fields`, buang `remove`,
        dan ganti opsi lain (items, where, item_path, name, ...)."""
        merged = dict(self._fields)
        merged.update(fields or {})
        for name in remove:
            merged.pop(name, None)
        return FieldMapper(fields=merged, **{**self._options, **options})

    def report(self, data):
        """Periksa mapping terhadap data contoh: berapa item, dan field mana yang terisi."""
        items = self(data)
        stats = {}
        for name in self._fields:
            filled = [it.get(name) for it in items if it.get(name) not in _BLANK]
            stats[name] = {"filled": len(filled), "empty": len(items) - len(filled),
                           "example": filled[0] if filled else None}
        return {"items": len(items), "fields": stats,
                "empty_fields": [n for n, st in stats.items() if items and st["filled"] == 0]}

    def explain(self, data, width=60):
        """Versi teks dari report(): tandai field yang tidak pernah terisi (kemungkinan path salah)."""
        rep = self.report(data)
        lines = [f"[{self.name}] {rep['items']} item dari data contoh"]
        for name, st in rep["fields"].items():
            mark = "OK    " if st["filled"] else "KOSONG"
            example = repr(st["example"])
            example = example if len(example) <= width else example[:width - 3] + "..."
            lines.append(f"  {mark} {name:<28} {st['filled']}/{rep['items']}  {example}")
        return "\n".join(lines)

    @classmethod
    def from_config(cls, config, register=False):
        """Bangun mapper dari dict/JSON, tanpa menulis Python.

        Kunci: name, items, item_path, where, record_where, unwrap, fields, extends, remove.
        Spec field: "path" | [path, transform, default] | {path|any_of|template|const|fn, default, transform, required}.
        Nilai where "$exists" = EXISTS; `fn`/`unwrap` berupa "modul:fungsi".
        """
        unknown = set(config) - _CONFIG_KEYS
        if unknown:
            raise ValueError(f"Kunci config tidak dikenal: {', '.join(sorted(unknown))}")
        fields = {name: _spec_from_config(spec) for name, spec in (config.get("fields") or {}).items()}
        options = {}
        for key in ("name", "items", "item_path"):
            if key in config:
                options[key] = config[key]
        for key in ("where", "record_where"):
            if key in config:
                options[key] = _where_from_config(config[key])
        if config.get("unwrap"):
            options["unwrap"] = _import_callable(config["unwrap"])

        if config.get("extends"):
            mapper = get_mapper(config["extends"]).extend(
                fields=fields, remove=config.get("remove", ()), **options)
        else:
            if "items" not in config:
                raise ValueError("Config mapper butuh 'items' (atau 'extends')")
            mapper = cls(fields=fields, **options)
        if register:
            register_mapper(mapper.name, mapper, replace=True)
        return mapper

    @classmethod
    def from_json(cls, source, register=False):
        """`source`: path file .json atau teks JSON."""
        source = str(source)
        if os.path.exists(source):
            with open(source, encoding="utf-8") as handle:
                source = handle.read()
        text = source
        return cls.from_config(json.loads(text), register=register)


_CONFIG_KEYS = {"name", "items", "item_path", "where", "record_where", "unwrap",
                "fields", "extends", "remove"}


def _import_callable(path):
    module_name, _, attr = path.replace(":", ".").rpartition(".")
    if not module_name:
        raise ValueError(f"Gunakan format 'modul:fungsi', bukan {path!r}")
    return getattr(importlib.import_module(module_name), attr)


def _spec_from_config(spec):
    if isinstance(spec, list):
        return tuple(spec)
    if isinstance(spec, dict):
        kwargs = dict(spec)
        if "const" in kwargs:
            return const(kwargs["const"])
        if "fn" in kwargs:
            kwargs["fn"] = _import_callable(kwargs["fn"])
        return F(**kwargs)
    return spec


def _where_from_config(where):
    if not isinstance(where, dict):
        raise ValueError("where pada config harus berupa objek {path: nilai}")
    return {path: EXISTS if expected == "$exists" else expected for path, expected in where.items()}


def load_mappers(directory, register=True):
    """Muat semua *.json di folder (urut nama; mapper yang di-`extends` harus lebih dulu)."""
    loaded = []
    for filename in sorted(os.listdir(directory)):
        if filename.endswith(".json"):
            loaded.append(FieldMapper.from_json(os.path.join(directory, filename), register=register))
    return loaded
