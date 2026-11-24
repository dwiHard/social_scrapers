"""Preset mapping X/Twitter (GraphQL timeline). Terdaftar sebagai: twitter.search.

Mendukung dua bentuk respons sekaligus:
  - skema baru (operasi `SearchByRawQuery`): `content.content.tweet_results`, metrik di `counts`,
    teks/tanggal di `details`, user di `profile_bio` / `relationship_counts` / `tweet_counts`;
  - skema lama (operasi `SearchTimeline`): `content.itemContent.tweet_results`, semua di `legacy`.
Untuk `api_match` pakai `SEARCH_API_MATCH` (cocok dengan kedua nama operasi).
"""
import re

from ..parsing import EXISTS, F, FieldMapper, const, get_path, register_mapper
from ..parsing.transforms import get_transform

USER = "core.user_results.result"
SEARCH_API_MATCH = re.compile(r"/(SearchByRawQuery|SearchTimeline)\b")
_LEGACY_DATE = "%a %b %d %H:%M:%S %z %Y"
_iso_ms, _iso_legacy = get_transform("iso_utc"), get_transform(f"iso_utc:{_LEGACY_DATE}")
_day_ms, _day_legacy = get_transform("date_id"), get_transform(f"date_id:{_LEGACY_DATE}")


def tweet_from_entry(entry):
    """Ambil objek tweet dari satu entry timeline (skema baru atau lama); {} bila bukan tweet."""
    if not isinstance(entry, dict):
        return {}
    for path in ("content.content.tweet_results.result", "content.itemContent.tweet_results.result",
                 "item.content.tweet_results.result"):
        found = get_path(entry, path)
        if isinstance(found, dict) and found:
            return unwrap_visibility(found)
    return {}


def _created(record, ms, legacy):
    value = get_path(record, "details.created_at_ms")
    if value not in (None, ""):
        return ms(value)
    value = get_path(record, "legacy.created_at")
    return legacy(value) if value else None


def unwrap_visibility(record):
    if record.get("__typename") == "TweetWithVisibilityResults":
        return record.get("tweet") or {}
    return record


def _screen_name(r):
    return get_path(r, f"{USER}.core.screen_name") or get_path(r, f"{USER}.legacy.screen_name") or ""


def _engagement(r):
    views = int(get_path(r, "views.count", 0) or 0)
    total = sum(int(_count(r, k) or 0) for k in ("favorite_count", "retweet_count", "reply_count", "quote_count"))
    return round(total / views * 100, 2) if views else 0.0


def _count(r, key):
    value = get_path(r, f"counts.{key}")
    return value if value not in (None, "") else get_path(r, f"legacy.{key}", 0)


def _c(key):
    return F(fn=lambda r: _count(r, key), transform="int", default=0)


def _hashtags(r):
    return get_path(r, "details.hashtag_entities[].text") or get_path(r, "legacy.entities.hashtags[].text") or []


def _mentions(field):
    def getter(r):
        return (get_path(r, f"mention_entities[].{field}") or get_path(r, f"legacy.entities.user_mentions[].{field}") or [])
    return getter


TWEET_FIELDS = {
    # ---------------- Identitas Tweet ----------------
    "id": F(any_of=["rest_id", "legacy.id_str"], transform="str"),
    "text": F(any_of=["note_tweet.note_tweet_results.result.text", "details.full_text", "legacy.full_text"],
              transform="str", default=""),
    "language": ("legacy.lang", "str", ""),
    "created_at": F(fn=lambda r: _created(r, _iso_ms, _iso_legacy), default=""),
    "dateid": F(fn=lambda r: _created(r, _day_ms, _day_legacy)),
    "url__s": F(fn=lambda r: f"https://x.com/{_screen_name(r)}/status/{r.get('rest_id', '')}"),
    
    # ---------------- Metrics (Menggunakan standar nama LAMA) ----------------
    "like__s": _c("favorite_count"),
    "retweet_count": _c("retweet_count"),
    "reply_count__s": _c("reply_count"),
    "quote_count": _c("quote_count"),
    "view_count": ("views.count", "int", 0),
    "bookmark_count": _c("bookmark_count"),
    "engagement_rate": F(fn=_engagement),                    
    
    # ---------------- Entities & Media ----------------
    "hashtags": F(fn=_hashtags),
    "mention_screen_name": F(fn=_mentions("screen_name")),
    "mention_name": F(fn=_mentions("name")),
    "media_urls": F(any_of=["media_entities2[].media_url_https",
                            "legacy.extended_entities.media[].media_url_https",
                            "legacy.entities.media[].media_url_https"], transform="each:url"),

    # ---------------- Reply, Quote, & Thread (Standar nama LAMA) ----------------
    "is_reply": F(fn=lambda r: 1 if get_path(r, "legacy.in_reply_to_status_id_str") else 0),
    "is_retweet": F(fn=lambda r: 1 if get_path(r, "legacy.retweeted_status_result") else 0),
    "conversation_id": ("legacy.conversation_id_str", "str", ""),
    "quoted_status_id_str": ("legacy.quoted_status_id_str", "str", ""),
    "in_reply_to_screen_name": ("legacy.in_reply_to_screen_name", "str", ""),
    "in_reply_to_status_id": ("legacy.in_reply_to_status_id_str", "str", ""),
    "in_reply_to_user_id": ("legacy.in_reply_to_user_id_str", "str", ""),
    
    # ---------------- User Profile (Menggunakan standar nama LAMA) ----------------
    "user_id": (f"{USER}.rest_id", "str", ""),
    "user_screen_name": F(fn=_screen_name),
    "user_name": F(any_of=[f"{USER}.core.name", f"{USER}.legacy.name"], transform="str", default=""),
    "user_description": F(any_of=[f"{USER}.profile_bio.description", f"{USER}.legacy.description"],
                          transform="str", default=""),
    "location": F(any_of=[f"{USER}.legacy.location", f"{USER}.location.location"], transform="str", default=""),
    "user_profile_image_url": F(any_of=[f"{USER}.avatar.image_url", f"{USER}.legacy.profile_image_url_https"], transform="url", default=""),
    "user_profile_banner_url": (f"{USER}.legacy.profile_banner_url", "url", ""),
    "user_created_at": F(any_of=[f"{USER}.legacy.created_at", f"{USER}.core.created_at"], transform="iso_utc:%a %b %d %H:%M:%S %z %Y", default=""),
    "verified__b": F(fn=lambda r: bool(get_path(r, f"{USER}.is_blue_verified") or
                                       get_path(r, f"{USER}.verification.is_blue_verified") or 
                                       get_path(r, f"{USER}.legacy.verified") or 
                                       get_path(r, f"{USER}.verification.verified"))),
    
    # ---------------- User Metrics (Menggunakan standar nama LAMA) ----------------
    "user_followers_count": F(any_of=[f"{USER}.relationship_counts.followers", f"{USER}.legacy.followers_count"],
                             transform="int", default=0),
    "user_following_count": F(any_of=[f"{USER}.relationship_counts.following", f"{USER}.legacy.friends_count"],
                             transform="int", default=0),
    "user_favorites_count": (f"{USER}.legacy.favourites_count", "int", 0),
    "user_listed_count": (f"{USER}.legacy.listed_count", "int", 0),
    "user_fast_followers_count": (f"{USER}.legacy.fast_followers_count", "int", 0),
    "user_normal_followers_count": (f"{USER}.legacy.normal_followers_count", "int", 0),
    "statuses_count": F(any_of=[f"{USER}.tweet_counts.tweets", f"{USER}.legacy.statuses_count"],
                       transform="int", default=0),
    "media_count": (f"{USER}.legacy.media_count", "int", 0),
    
    "posts": const(True),
}

TIMELINE = "data.search_by_raw_query.search_timeline.timeline.instructions[]"

search_mapper = FieldMapper(
    items=[f"{TIMELINE}.entries[]", f"{TIMELINE}.entry"],
    unwrap=tweet_from_entry,
    record_where=lambda r: any(k in r for k in ("legacy", "counts", "details")),
    fields=TWEET_FIELDS, name="twitter.search",
)

register_mapper(search_mapper.name, search_mapper, replace=True)
