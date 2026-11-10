"""Shim kompatibilitas; gunakan `cdp_scraper.messaging`."""
from ..messaging.redpanda import delivery_callback, get_default_producer  # noqa: F401


def __getattr__(name):
    if name == "kafka_producer":
        return get_default_producer().producer
    raise AttributeError(name)
