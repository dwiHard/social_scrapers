"""Preset mapping TikTok, setara dengan parse_tiktok_api_search, parse_tiktok_api_user_videos,
dan parse_comment_data pada parser lama. Terdaftar sebagai:
tiktok.user_videos, tiktok.search, tiktok.comments."""
from ..parsing import F, FieldMapper, const, register_mapper
from ..utils import calculate_engagement_rate, safe_str

IDENTITY_STATS = {
    "id": ("id", "str", ""),
    "url": F(template="https://www.tiktok.com/@{author.uniqueId}/video/{id}", transform="url"),
    "video_like_count": ("stats.diggCount", "int", 0),
    "video_comment_count": ("stats.commentCount", "int", 0),
    "video_share_count": ("stats.shareCount", "int", 0),
    "video_play_count": ("stats.playCount", "int", 0),
    "video_bookmark_count": ("stats.collectCount", "int", 0),
    "engagement_rate": F(fn=lambda r: calculate_engagement_rate(r.get("stats") or {})),
}

CONTENT = {
    "user_post_desc": ("desc", "str", ""),
    "video_hashtags": "textExtra[type=1].hashtagName",
    "video_mentions_screen_name": "textExtra[type=0].userUniqueId",
    "video_mentions_username_id": "textExtra[type=0].userUniqueId",
    "video_mentions_user_id": F(fn=lambda r: [
        safe_str(e.get("userId")) for e in r.get("textExtra") or []
        if e.get("type") == 0 and e.get("userUniqueId")]),
}

TIMESTAMPS = {
    "dateid": F("createTime", transform="date_id"),
    "p_created_at": F("createTime", transform="iso_utc", default=""),
}

VIDEO_META = {
    "video_duration": ("video.duration", "int", 0),
    "video_ratio": ("video.ratio", "str", ""),
    "video_cover": ("video.cover", "url", ""),
}

AUTHOR = {
    "author_id": ("author.id", "str", ""),
    "author_username_id": ("author.uniqueId", "str", ""),
    "author_nickname_id": ("author.nickname", "str", ""),
    "author_avatar": ("author.avatarThumb", "url", ""),
    "is_verified": ("author.verified", "bool", False),
    "author_following_count": ("authorStats.followingCount", "int", 0),
    "author_follower_count": ("authorStats.followerCount", "int", 0),
    "author_like_count": ("authorStats.heartCount", "int", 0),
    "author_video_count": ("authorStats.videoCount", "int", 0),
}

MUSIC = {
    "music_id": ("music.id", "str", ""),
    "music_title": ("music.title", "str", ""),
    "music_author_name": ("music.authorName", "str", ""),
    "music_album": ("music.album", "str", ""),
    "music_cover": ("music.coverThumb", "url", ""),
    "music_duration": ("music.duration", "int", 0),
    "music_play_url": ("music.playUrl", "url", ""),
}

LOCATION = {
    "location_name": ("poi.name", "str", ""),
    "location_address": ("poi.address", "str", ""),
    "location_city": ("poi.city", "str", ""),
    "location_category": ("poi.category", "str", ""),
}

VIDEO_FIELDS = {**IDENTITY_STATS, **CONTENT, **TIMESTAMPS, **VIDEO_META, **AUTHOR,
                **MUSIC, **LOCATION, "posts": const(True)}

user_videos_mapper = FieldMapper(items="itemList", fields=VIDEO_FIELDS, name="tiktok.user_videos")

search_mapper = user_videos_mapper.extend(
    fields={"video_play_addr": ("video.playAddr", "url", ""),
            "music_is_original": ("music.original", "bool", False)},
    items="data", where={"type": 1}, item_path="item", name="tiktok.search")

comments_mapper = FieldMapper(items="comments", name="tiktok.comments", fields={
    "id": "cid",
    "post_id": "aweme_id",
    "comment_username": "user.unique_id",
    "comment_nickname": "user.nickname",
    "comment_user_id": "user.uid",
    "comment_avatar": "user.avatar_thumb.url_list[0]",
    "text": ("text", None, ""),
    "comment_language": "comment_language",
    "reply_comment_total": F("reply_comment_total", default=0),
    "comment_like_count": F("digg_count", default=0),
    "comment_total": F("reply_comment_total", default=0),
    "dateid": F("create_time", transform="date_id"),
    "c_created_at": F("create_time", transform="iso_utc"),
    "is_reply": F(fn=lambda r: 1 if r.get("reply_to_reply_id") else 0),
    "reply_to_reply_id": "reply_to_reply_id",
    "reply_comment_id": "reply_id",
    "posts": const(False),
})

for _mapper in (user_videos_mapper, search_mapper, comments_mapper):
    register_mapper(_mapper.name, _mapper, replace=True)
