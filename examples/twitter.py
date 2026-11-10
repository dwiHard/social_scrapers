"""Contoh platform X/Twitter: search live dengan operator filter (GraphQL SearchTimeline)."""
import urllib.parse

from cdp_scraper import (EXISTS, Endpoint, F, FieldMapper, Platform, const,
                         end_when_empty, get_path, make_scroller, make_wait_for)

FILTERS = ("since", "until", "min_faves", "min_retweets", "min_replies")
USER = "core.user_results.result"


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


def unwrap_visibility(record):
    if record.get("__typename") == "TweetWithVisibilityResults":
        return record.get("tweet") or {}
    return record


def _screen_name(r):
    return get_path(r, f"{USER}.core.screen_name") or get_path(r, f"{USER}.legacy.screen_name") or ""


def _engagement(r):
    legacy = r.get("legacy") or {}
    views = int(get_path(r, "views.count", 0) or 0)
    total = sum(int(legacy.get(k) or 0) for k in
                ("favorite_count", "retweet_count", "reply_count", "quote_count"))
    return round(total / views * 100, 2) if views else 0.0


TWEET_FIELDS = {
    "id": F(any_of=["rest_id", "legacy.id_str"], transform="str"),
    "url": F(fn=lambda r: f"https://x.com/{_screen_name(r)}/status/{r.get('rest_id', '')}"),
    "text": F(any_of=["note_tweet.note_tweet_results.result.text", "legacy.full_text"],
              transform="str", default=""),
    "language": ("legacy.lang", "str", ""),
    "hashtags": "legacy.entities.hashtags[].text",
    "mentions_screen_name": "legacy.entities.user_mentions[].screen_name",
    "mentions_user_id": F("legacy.entities.user_mentions[].id_str", transform="each:str"),
    "media_urls": F(any_of=["legacy.extended_entities.media[].media_url_https",
                            "legacy.entities.media[].media_url_https"], transform="each:url"),
    "like_count": ("legacy.favorite_count", "int", 0),
    "retweet_count": ("legacy.retweet_count", "int", 0),
    "reply_count": ("legacy.reply_count", "int", 0),
    "quote_count": ("legacy.quote_count", "int", 0),
    "bookmark_count": ("legacy.bookmark_count", "int", 0),
    "view_count": ("views.count", "int", 0),
    "engagement_rate": F(fn=_engagement),
    "dateid": F("legacy.created_at", transform="date_id:%a %b %d %H:%M:%S %z %Y"),
    "p_created_at": F("legacy.created_at", transform="iso_utc:%a %b %d %H:%M:%S %z %Y", default=""),
    "is_reply": F(fn=lambda r: 1 if get_path(r, "legacy.in_reply_to_status_id_str") else 0),
    "is_retweet": F(fn=lambda r: 1 if get_path(r, "legacy.retweeted_status_result") else 0),
    "reply_to_tweet_id": ("legacy.in_reply_to_status_id_str", "str", ""),
    "conversation_id": ("legacy.conversation_id_str", "str", ""),
    "author_id": (f"{USER}.rest_id", "str", ""),
    "author_username": F(fn=_screen_name),
    "author_name": F(any_of=[f"{USER}.core.name", f"{USER}.legacy.name"], transform="str", default=""),
    "author_avatar": F(any_of=[f"{USER}.avatar.image_url", f"{USER}.legacy.profile_image_url_https"],
                       transform="url", default=""),
    "is_verified": F(fn=lambda r: bool(get_path(r, f"{USER}.is_blue_verified")
                                       or get_path(r, f"{USER}.legacy.verified"))),
    "author_follower_count": (f"{USER}.legacy.followers_count", "int", 0),
    "author_following_count": (f"{USER}.legacy.friends_count", "int", 0),
    "author_tweet_count": (f"{USER}.legacy.statuses_count", "int", 0),
    "posts": const(True),
}

TIMELINE = "data.search_by_raw_query.search_timeline.timeline.instructions[]"

search_parser = FieldMapper(
    items=[f"{TIMELINE}.entries[]", f"{TIMELINE}.entry"],
    item_path="content.itemContent.tweet_results.result",
    unwrap=unwrap_visibility,
    record_where={"legacy": EXISTS},
    fields=TWEET_FIELDS, name="twitter.search",
)

twitter = Platform(
    name="twitter",
    cdp={"cdp_url": "http://localhost:9223"},
    login_url_hints=("/login", "/i/flow"),
    delay_between_runs=2.0,
    endpoints=[
        Endpoint(
            "search", url=build_search_url, api_match="SearchTimeline", parser=search_parser,
            key="id", validate=validate, label=lambda p: p.get("keyword") or f"from:{p.get('from_user')}",
            limit=20, max_limit=100, max_scrolls=lambda limit: min(30, limit // 10 + 6),
            initial_sleep=4, end=end_when_empty(search_parser),
            prepare=make_wait_for('article[data-testid="tweet"]'),
            scroll=make_scroller(wheel=3000, window_scroll="viewport", viewport_factor=2,
                                 click_pattern="^(retry|coba lagi)$"),
        ),
    ],
)
