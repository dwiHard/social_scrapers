"""Pembaca file .env sederhana (stdlib, tanpa python-dotenv).

  from cdp_scraper import load_env_file
  load_env_file(".env")          # sebelum CDPConfig.from_env() / TelegramNotifier.from_env()

Aturan: nilai yang SUDAH ada di environment (docker-compose, systemd, export) tidak ditimpa, kecuali override=True.
Format yang didukung: KEY=VALUE, `export KEY=VALUE`, "dalam kutip ganda" (escape \\n \\" \\\\), 'kutip tunggal' (literal),
baris komentar `# ...`, komentar di akhir nilai tanpa kutip (` # ...`), baris kosong. Tidak ada ekspansi ${VAR}.
"""
import os
import re

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")
_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}


def _parse_value(raw):
    raw = raw.strip()
    if raw[:1] == '"':
        out, i = [], 1
        while i < len(raw):
            ch = raw[i]
            if ch == "\\" and i + 1 < len(raw):
                out.append(_ESCAPES.get(raw[i + 1], "\\" + raw[i + 1]))
                i += 2
                continue
            if ch == '"':
                return "".join(out)
            out.append(ch)
            i += 1
        return "".join(out)          # kutip penutup tidak ada: ambil apa adanya
    if raw[:1] == "'":
        end = raw.find("'", 1)
        return raw[1:end] if end != -1 else raw[1:]
    match = re.search(r"\s#", raw)
    return (raw[:match.start()] if match else raw).strip()


def parse_env(text):
    """Teks .env -> dict (urutan sesuai file; kunci ganda: yang terakhir menang)."""
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") or line.startswith("export\t"):
            line = line[7:].lstrip()
        key, sep, raw = line.partition("=")
        key = key.strip()
        if not sep or not _KEY.match(key):
            continue
        values[key] = _parse_value(raw)
    return values


def load_env_file(path=".env", *, override=False, environ=None, required=False):
    """Baca file .env dan isi environment. Mengembalikan dict seluruh isi file (bukan hanya yang diterapkan).

    path: lokasi file (relatif terhadap working directory proses). Tidak ada file -> {} (atau FileNotFoundError
    bila required=True). override=False: variabel yang sudah ada di environment tidak diubah.
    """
    env = os.environ if environ is None else environ
    try:
        with open(path, encoding="utf-8-sig") as handle:
            values = parse_env(handle.read())
    except FileNotFoundError:
        if required:
            raise
        return {}
    for key, value in values.items():
        if override or key not in env:
            env[key] = value
    return values
