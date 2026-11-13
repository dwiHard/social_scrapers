"""Pengecekan koneksi ke server CDP (Chrome remote debugging), hanya memakai stdlib."""
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request


def http_base(cdp_url):
    """URL HTTP dasar dari cdp_url (ws:// -> http://, tanpa path)."""
    if "://" not in cdp_url:
        cdp_url = "http://" + cdp_url
    parts = urllib.parse.urlsplit(cdp_url)
    scheme = {"ws": "http", "wss": "https"}.get(parts.scheme, parts.scheme)
    return f"{scheme}://{parts.netloc}"


def _get_json(url, timeout):
    with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data


def _describe(error, timeout):
    if isinstance(error, urllib.error.HTTPError):
        body = ""
        try:
            body = error.read().decode("utf-8", "replace").strip().replace("\n", " ")[:120]
        except Exception:
            pass
        return f"HTTP {error.code}" + (f": {body}" if body else "")
    if isinstance(error, urllib.error.URLError):
        reason = error.reason
        if isinstance(reason, socket.timeout):
            return f"timeout setelah {timeout:g} detik"
        return str(reason)
    if isinstance(error, (socket.timeout, TimeoutError)):
        return f"timeout setelah {timeout:g} detik"
    if isinstance(error, ValueError):
        return "respons bukan JSON CDP"
    return str(error) or error.__class__.__name__


def check_cdp(cdp_url, timeout=3.0, tabs=False):
    """Cek apakah server CDP menjawab (`GET /json/version`). Sinkron, tidak membuka tab.

    Return: {connected, cdp_url, browser, protocol_version, latency_ms, error[, tabs]}.
    """
    result = {"connected": False, "cdp_url": cdp_url, "browser": None,
              "protocol_version": None, "latency_ms": None, "error": None}
    base = http_base(cdp_url)
    started = time.perf_counter()
    try:
        data = _get_json(f"{base}/json/version", timeout)
        if not isinstance(data, dict):
            raise ValueError("bukan objek")
        result.update(connected=True, browser=data.get("Browser"),
                      protocol_version=data.get("Protocol-Version"),
                      latency_ms=round((time.perf_counter() - started) * 1000, 1))
        if tabs:
            pages = _get_json(f"{base}/json/list", timeout)
            result["tabs"] = len([t for t in pages if isinstance(t, dict) and t.get("type") == "page"])
    except Exception as e:
        result["connected"] = False
        result["error"] = _describe(e, timeout)
    return result
