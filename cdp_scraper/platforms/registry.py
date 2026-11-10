import threading

_platforms = {}
_lock = threading.Lock()


def register_platform(platform, replace=False):
    with _lock:
        if platform.name in _platforms and not replace:
            raise ValueError(f"Platform '{platform.name}' sudah terdaftar (pakai replace=True)")
        _platforms[platform.name] = platform
    return platform


def get_platform(name):
    try:
        return _platforms[name]
    except KeyError:
        raise KeyError(f"Platform '{name}' belum terdaftar (tersedia: {', '.join(_platforms) or '-'})")


def list_platforms():
    return sorted(_platforms)


def unregister_platform(name):
    with _lock:
        _platforms.pop(name, None)
