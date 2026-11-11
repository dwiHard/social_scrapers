"""Contoh platform X/Twitter: URL operator pencarian + mapping dari preset."""
import urllib.parse

from cdp_scraper import (Endpoint, Platform, end_when_empty, make_scroller, make_wait_for)
from cdp_scraper.presets.twitter import search_mapper

FILTERS = ("since", "until", "min_faves", "min_retweets", "min_replies")


def build_search_url(keyword=None, from_user=None, **filters):
    operators = [f"from:{from_user}"] if from_user else []
    operators += [f"{name}:{filters[name]}" for name in FILTERS if filters.get(name) not in (None, "")]
    parts = []
    if keyword:
        parts.append(urllib.parse.quote(str(keyword)))
    if operators:
        parts.append(urllib.parse.quote(" ".join(operators), safe=":"))
    return f"https://x.com/search?q={'%20'.join(parts)}&src=trend_clicks&f=live&vertical=trends"


def validate(params):
    if not params.get("keyword") and not params.get("from_user"):
        raise ValueError("Isi minimal salah satu: keyword atau from_user")


search_parser = search_mapper


twitter = Platform(
    name="twitter",
    cdp={"cdp_url": "http://localhost:9223"},
    login_url_hints=("/login", "/i/flow"),
    delay_between_runs=2.0,
    endpoints=[
        Endpoint(
            "search", url=build_search_url, api_match="SearchTimeline", parser="twitter.search",
            key="id", validate=validate, label=lambda p: p.get("keyword") or f"from:{p.get('from_user')}",
            limit=20, max_limit=100, max_scrolls=lambda limit: min(30, limit // 10 + 6),
            initial_sleep=4, end=end_when_empty(search_mapper),
            prepare=make_wait_for('article[data-testid="tweet"]'),
            scroll=make_scroller(wheel=3000, window_scroll="viewport", viewport_factor=2,
                                 click_pattern="^(retry|coba lagi)$"),
        ),
    ],
)
