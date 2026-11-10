import logging

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
