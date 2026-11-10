from flask import jsonify

from config import REQUEST_TIMEOUT
from browser.state import LAST_DIAG


def parse_limit(value, default):
    return int(value) if str(value).isdigit() else default


def timeout_response(include_diag=False):
    body = {"status": "timeout",
            "message": f"Scraping melebihi batas waktu ({REQUEST_TIMEOUT} detik) atau browser sibuk",
            "data": [], "total_scraped": 0}
    if include_diag:
        body["diagnostics"] = dict(LAST_DIAG)
    return jsonify(body), 504


def safe_int(value, default=0):
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def safe_str(value, default=''):
    if value is None:
        return default
    return str(value).strip()


def validate_url(url):
    if not url:
        return ''
    url = safe_str(url)
    if url and not url.startswith(('http://', 'https://')):
        return ''
    return url.strip()
