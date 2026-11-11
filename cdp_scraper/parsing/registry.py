import threading

_mappers = {}
_lock = threading.Lock()


def register_mapper(name, mapper, replace=False):
    """Daftarkan mapper dengan nama agar bisa dipakai ulang (Endpoint.parser='nama', extends='nama')."""
    with _lock:
        if name in _mappers and not replace:
            raise ValueError(f"Mapper '{name}' sudah terdaftar (pakai replace=True)")
        _mappers[name] = mapper
    return mapper


def get_mapper(name):
    try:
        return _mappers[name]
    except KeyError:
        raise KeyError(f"Mapper '{name}' belum terdaftar (tersedia: {', '.join(sorted(_mappers)) or '-'})")


def list_mappers():
    return sorted(_mappers)


def unregister_mapper(name):
    with _lock:
        _mappers.pop(name, None)
