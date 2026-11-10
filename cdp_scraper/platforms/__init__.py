from .registry import get_platform, list_platforms, register_platform, unregister_platform
from .runner import Scraper, ScrapeResult
from .spec import Endpoint, Platform, end_when_empty, end_when_falsy

__all__ = ["Endpoint", "Platform", "Scraper", "ScrapeResult", "end_when_empty",
           "end_when_falsy", "get_platform", "list_platforms", "register_platform",
           "unregister_platform"]
