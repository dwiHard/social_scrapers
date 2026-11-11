"""Resolver path untuk JSON bersarang.

Sintaks: `a.b.c`, indeks `a[0].b`, semua elemen `a[].b`, filter `a[type=1].b`
(filter bertipe: =1 angka, =true boolean, ="1" atau =abc string).
Path berwildcard/filter selalu menghasilkan list (kosong jika tidak ada);
nilai None/"" pada ujung key dibuang.
"""
import json
import re

_TOKEN_RE = re.compile(r"\[[^\]]*\]|[^.\[\]]+")
_INDEX_RE = re.compile(r"-?\d+")
_cache = {}


class _Missing:
    def __repr__(self):
        return "MISSING"

    def __bool__(self):
        return False


MISSING = _Missing()


def compile_path(path):
    compiled = _cache.get(path)
    if compiled is None:
        tokens = _TOKEN_RE.findall(path)
        multi = False
        for tok in tokens:
            if tok.startswith("["):
                inner = tok[1:-1]
                if inner == "" or "=" in inner:
                    multi = True
                elif not _INDEX_RE.fullmatch(inner):
                    raise ValueError(f"Token path tidak valid: {tok!r} pada {path!r}")
        compiled = _cache[path] = (tuple(tokens), multi)
    return compiled


_literal_cache = {}


def _literal(text):
    """Teks filter -> nilai bertipe: 1 -> int, true -> bool, "1" -> str, abc -> str."""
    if text not in _literal_cache:
        try:
            value = json.loads(text)
        except ValueError:
            value = text
        _literal_cache[text] = value if isinstance(value, (int, float, str, bool)) or value is None else text
    return _literal_cache[text]


def _same(value, text):
    return value == _literal(text)


def resolve(data, path):
    """Nilai pada path, atau MISSING (list untuk path wildcard/filter)."""
    tokens, multi = compile_path(path)
    current = [data]
    for tok in tokens:
        nxt = []
        if tok.startswith("["):
            inner = tok[1:-1]
            if inner == "":
                for node in current:
                    if isinstance(node, (list, tuple)):
                        nxt.extend(node)
            elif "=" in inner:
                key, _, expected = inner.partition("=")
                for node in current:
                    if isinstance(node, (list, tuple)):
                        nxt.extend(x for x in node if isinstance(x, dict) and key in x and _same(x[key], expected))
            else:
                idx = int(inner)
                for node in current:
                    if isinstance(node, (list, tuple)) and -len(node) <= idx < len(node):
                        nxt.append(node[idx])
        else:
            for node in current:
                if isinstance(node, dict) and tok in node:
                    nxt.append(node[tok])
        current = nxt
        if not current:
            return [] if multi else MISSING
    if multi:
        if tokens and not tokens[-1].startswith("["):
            current = [v for v in current if v is not None and v != ""]
        return current
    return current[0]


def get_path(data, path, default=None):
    value = resolve(data, path)
    return default if value is MISSING else value
