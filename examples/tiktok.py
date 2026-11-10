"""Contoh platform TikTok: search & video milik user, parsing murni lewat mapping."""
from cdp_scraper import Endpoint, F, FieldMapper, Platform, const, make_scroller
from cdp_scraper.utils import calculate_engagement_rate

OVERLAYS = ('[data-e2e="modal-close-inner-button"]', 'div[class*="ModalClose"]')

VIDEO_FIELDS = {
    "id": ("id", "str", ""),
    "url": F(template="https://www.tiktok.com/@{author.uniqueId}/video/{id}", transform="url"),
    "video_like_count": ("stats.diggCount", "int", 0),
    "video_comment_count": ("stats.commentCount", "int", 0),
    "video_share_count": ("stats.shareCount", "int", 0),
    "video_play_count": ("stats.playCount", "int", 0),
    "video_bookmark_count": ("stats.collectCount", "int", 0),
    "engagement_rate": F(fn=lambda r: calculate_engagement_rate(r.get("stats") or {})),
    "user_post_desc": ("desc", "str", ""),
    "video_hashtags": "textExtra[type=1].hashtagName",
    "video_mentions_screen_name": "textExtra[type=0].userUniqueId",
    "video_mentions_username_id": "textExtra[type=0].userUniqueId",
    "video_mentions_user_id": F("textExtra[type=0].userId", transform="each:str"),
    "dateid": F("createTime", transform="date_id"),
    "p_created_at": F("createTime", transform="iso_utc", default=""),
    "video_duration": ("video.duration", "int", 0),
    "video_ratio": ("video.ratio", "str", ""),
    "video_cover": ("video.cover", "url", ""),
    "author_id": ("author.id", "str", ""),
    "author_username_id": ("author.uniqueId", "str", ""),
    "author_nickname_id": ("author.nickname", "str", ""),
    "author_avatar": ("author.avatarThumb", "url", ""),
    "is_verified": ("author.verified", "bool", False),
    "author_following_count": ("authorStats.followingCount", "int", 0),
    "author_follower_count": ("authorStats.followerCount", "int", 0),
    "author_like_count": ("authorStats.heartCount", "int", 0),
    "author_video_count": ("authorStats.videoCount", "int", 0),
    "music_id": ("music.id", "str", ""),
    "music_title": ("music.title", "str", ""),
    "music_author_name": ("music.authorName", "str", ""),
    "music_album": ("music.album", "str", ""),
    "music_cover": ("music.coverThumb", "url", ""),
    "music_duration": ("music.duration", "int", 0),
    "music_play_url": ("music.playUrl", "url", ""),
    "location_name": ("poi.name", "str", ""),
    "location_address": ("poi.address", "str", ""),
    "location_city": ("poi.city", "str", ""),
    "location_category": ("poi.category", "str", ""),
    "posts": const(True),
}

SEARCH_FIELDS = dict(VIDEO_FIELDS)
SEARCH_FIELDS["video_play_addr"] = ("video.playAddr", "url", "")
SEARCH_FIELDS["music_is_original"] = ("music.original", "bool", False)

search_parser = FieldMapper(items="data", where={"type": 1}, item_path="item",
                            fields=SEARCH_FIELDS, name="tiktok.search")
user_videos_parser = FieldMapper(items="itemList", fields=VIDEO_FIELDS, name="tiktok.user")

tiktok = Platform(
    name="tiktok",
    overlay_selectors=OVERLAYS,
    endpoints=[
        Endpoint(
            "search", url="https://www.tiktok.com/search?q={keyword}",
            api_match="search/general/full", parser=search_parser,
            params=("keyword",), label="keyword", limit=20, max_limit=20,
            initial_sleep=4,
            scroll=make_scroller(wheel=2500, containers=True,
                                 click_pattern="load more|lihat lebih banyak|muat lebih banyak"),
        ),
        Endpoint(
            "user_videos", url="https://www.tiktok.com/@{username}",
            api_match="post/item_list", parser=user_videos_parser,
            params=("username",), label="username", limit=30,
            normalize=lambda p: {**p, "username": str(p["username"]).lstrip("@")},
        ),
    ],
)
