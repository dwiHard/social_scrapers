import collections
import logging
import time

LOGGER_NAME = "cdp_scraper"
DEFAULT_JOB = "cdp"
LOG_FORMAT = "[{asctime}] [{levelname}] {message}"

_base = logging.getLogger(LOGGER_NAME)
_base.addHandler(logging.NullHandler())


def set_base_logger(logger):
    global _base
    _base = logger


class JobLogger:
    """Logger berformat `[job] Status message: detail`."""

    __slots__ = ("job", "_base")

    def __init__(self, job=DEFAULT_JOB, base=None):
        self.job = job
        self._base = base

    @property
    def base(self):
        return self._base or _base

    def bind(self, job):
        return JobLogger(job, self._base)

    def _msg(self, status, detail):
        return f"[{self.job}] {status} message: {detail}"

    def success(self, detail):
        self.base.info(self._msg("Success", detail))

    def info(self, detail):
        self.base.info(self._msg("Info", detail))

    def warning(self, detail):
        self.base.warning(self._msg("Warning", detail))

    def error(self, detail, exc_info=False):
        self.base.error(self._msg("Error", detail), exc_info=exc_info)

    def debug(self, detail):
        self.base.debug(self._msg("Debug", detail))


def get_logger(job=DEFAULT_JOB):
    return JobLogger(job)


def setup_logging(level=logging.INFO, fmt=LOG_FORMAT):
    logging.basicConfig(level=level, format=fmt, style="{", datefmt="%Y-%m-%d %H:%M:%S")


class RecordingLog:
    """Pembungkus logger yang meneruskan semua log lalu menyimpan N baris terakhir (untuk lampiran alert)."""

    def __init__(self, inner, max_lines=300):
        self._inner = inner
        self._lines = collections.deque(maxlen=max_lines)

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def bind(self, job):
        return RecordingLog(self._inner.bind(job), self._lines.maxlen)

    def _record(self, level, detail):
        job = getattr(self._inner, "job", DEFAULT_JOB)
        self._lines.append(f"{time.strftime('%H:%M:%S')} [{level}] [{job}] {detail}")

    def lines(self, last=None):
        items = list(self._lines)
        return items[-last:] if last else items

    def success(self, detail):
        self._record("OK", detail)
        self._inner.success(detail)

    def info(self, detail):
        self._record("INFO", detail)
        self._inner.info(detail)

    def warning(self, detail):
        self._record("WARN", detail)
        self._inner.warning(detail)

    def error(self, detail, exc_info=False):
        self._record("ERROR", detail)
        self._inner.error(detail, exc_info=exc_info)

    def debug(self, detail):
        self._record("DEBUG", detail)
        self._inner.debug(detail)
