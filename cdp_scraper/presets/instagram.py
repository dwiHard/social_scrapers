"""Preset mapping Instagram (GraphQL), setara MediaParser lama. Terdaftar sebagai:

  instagram.search         <- parse_media_data          (Top SERP)
  instagram.comments       <- parse_media_data_comment  (media_id ditempel lewat Endpoint.attach_params)
  instagram.user_profile   <- bagian profil parse_user_data
  instagram.user_posts     <- bagian post parse_user_data
  instagram.user_timeline  <- parse_user_data (profil + semua post, dalam satu list)

URL GraphQL Instagram sama untuk banyak query, jadi parser ini berbasis struktur: response yang
bukan miliknya menghasilkan list kosong. Untuk item profil yang tidak punya `id`, pakai
`key=item_key` pada Endpoint. Perbedaan dengan parser lama: tidak ada item `{"error": ...}`
(hasil kosong = []), dan record kosong atau post tanpa caption tidak lagi menggagalkan seluruh response.
"""
import json
import re
from datetime import datetime, timezone

from ..parsing import F, FieldMapper, const, get_path, register_mapper

HASHTAG_RE = re.compile(r"#(\w+)")
MENTION_RE = re.compile(r"@(\w+)")
SEARCH_EDGES = "data.xdt_fbsearch__top_serp_graphql.edges"
USER_EDGES = "data.xdt_api__v1__feed__user_timeline_graphql_connection.edges"


def _to_datetime(timestamp):
    try:
        if timestamp > 1000000000000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (ValueError, TypeError, OSError, OverflowError):
        return None


def to_iso(timestamp):
    """Unix timestamp (detik/milidetik) -> yyyy-MM-dd'T'HH:mm:ss'Z', None jika tidak valid."""
    dt = _to_datetime(timestamp) if timestamp else None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def to_date(timestamp):
    """Unix timestamp (detik/milidetik) -> yyyy-MM-dd, None jika tidak valid."""
    dt = _to_datetime(timestamp) if timestamp else None
    return dt.strftime("%Y-%m-%d") if dt else None


def item_key(item):
    """Kunci de-duplikasi: id untuk media/komentar/post, username untuk item profil."""
    return item.get("id") or item.get("username")


def loads_response_text(response):
    """JSON dari teks/response; membuang prefix 'for (;;);' yang kadang ditambahkan Instagram."""
    text = getattr(response, "text", response).strip()
    if text.startswith("for (;;);"):
        text = text[len("for (;;);"):]
    return json.loads(text)


def _tags(pattern, text_fn):
    return lambda record: pattern.findall(text_fn(record) or "")


def _media_caption(record):
    return (record.get("caption") or {}).get("text", "")


def _owner(record):
    return record.get("user") or {}


def _music(record):
    info = (record.get("music_metadata") or {}).get("music_info") or {}
    asset = info.get("music_asset_info") or {}
    if asset and asset.get("title"):
        return asset.get("title"), asset.get("display_artist")
    return None, None


def _search_media(data):
    for edge in get_path(data, SEARCH_EDGES) or []:
        if not isinstance(edge, dict):
            continue
        node = edge.get("node") or {}
        items = node["items"] if "items" in node else [node]
        for item in items or []:
            if isinstance(item, dict):
                yield item.get("media") or item


SEARCH_FIELDS = {
    "id": "pk",
    "comment_count": "comment_count",
    "like_count": "like_count",
    "url": F(fn=lambda r: f"https://www.instagram.com/p/{r.get('code')}" if r.get("code") else None),
    "hashtags": F(fn=_tags(HASHTAG_RE, _media_caption)),
    "mentions": F(fn=_tags(MENTION_RE, _media_caption)),
    "caption": F(fn=_media_caption),
    "p_created_at": F(fn=lambda r: to_iso(r.get("taken_at"))),
    "dateid": F(fn=lambda r: to_date(r.get("taken_at"))),
    "image_urls": F(fn=lambda r: f"https://www.instagram.com/p/{r.get('code')}/media/?size=m"
                    if r.get("code") else None),
    "owner_full_name": "user.full_name",
    "owner_id": F(fn=lambda r: _owner(r).get("id") or _owner(r).get("pk")),
    "owner_profile_pic_url": "user.profile_pic_url",
    "owner_username": "user.username",
    "is_verified": "user.is_verified",
    "location_name": "location.name",
    "location_lat": "location.lat",
    "location_lng": "location.lng",
    "music_title": F(fn=lambda r: _music(r)[0]),
    "music_artist": F(fn=lambda r: _music(r)[1]),
    "is_private": "user.is_private",
    "posts": const(True),
    "crawler_ig": const(True),
}

search_mapper = FieldMapper(
    items=_search_media,
    record_where=lambda r: bool(r.get("pk") or r.get("code")),
    fields=SEARCH_FIELDS, name="instagram.search")


def _find_connection(obj):
    if isinstance(obj, dict):
        if isinstance(obj.get("edges"), list) and "page_info" in obj:
            return obj
        for value in obj.values():
            found = _find_connection(value)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_connection(value)
            if found:
                return found
    return None


def _connection(data):
    return _find_connection(data.get("data", data)) if isinstance(data, dict) else None


def comments_page_info(data):
    """Info paginasi komentar: {"has_next_page", "end_cursor"} (setara return kedua parser lama)."""
    conn = _connection(data)
    if not conn:
        return {"has_next_page": False, "end_cursor": None}
    page_info = conn.get("page_info", {}) or {}
    return {"has_next_page": page_info.get("has_next_page", False), "end_cursor": page_info.get("end_cursor")}


def comments_exhausted(data):
    """end_fn komentar: True hanya jika response memuat koneksi komentar dan tidak ada halaman lagi."""
    conn = _connection(data)
    return bool(conn) and not (conn.get("page_info") or {}).get("has_next_page", False)


def _comment_nodes(data):
    conn = _connection(data)
    for edge in (conn or {}).get("edges", []):
        yield ((edge.get("node", {}) or {}) if isinstance(edge, dict) else {})


COMMENT_FIELDS = {
    "id": F(fn=lambda r: r.get("pk") or r.get("id")),
    "text": F(fn=lambda r: r.get("text", "")),
    "hashtags": _tags(HASHTAG_RE, lambda r: r.get("text", "")),
    "mentions": _tags(MENTION_RE, lambda r: r.get("text", "")),
    "media_id": const(None),
    "c_created_at": F(fn=lambda r: to_iso(r.get("created_at"))),
    "dateid": F(fn=lambda r: to_date(r.get("created_at"))),
    "comment_like_count": "comment_like_count",
    "reply_count": "child_comment_count",
    "user_id": F(fn=lambda r: _owner(r).get("pk") or _owner(r).get("id")),
    "comment_username": "user.username",
    "comment_is_verified": "user.is_verified",
    "comment_profile_pic_url": "user.profile_pic_url",
    "posts": const(False),
    "crawler_ig": const(True),
}

comments_mapper = FieldMapper(items=_comment_nodes, fields=COMMENT_FIELDS, name="instagram.comments")


def _post_caption_text(record):
    caption = record.get("caption")
    return caption.get("text") if caption else ""


def _post_created_at(record):
    return (record.get("caption") or {}).get("created_at")


def _slides(record):
    carousel = record.get("carousel_media")
    if carousel and isinstance(carousel, list):
        slides = []
        for index, slide in enumerate(carousel):
            candidates = (slide.get("image_versions2") or {}).get("candidates") or [{}]
            slides.append({"slide_no": index + 1, "accessibility_caption": slide.get("accessibility_caption"),
                           "url": candidates[0].get("url")})
        return slides
    candidates = (record.get("image_versions2") or {}).get("candidates") or []
    return [{"slide_no": 1, "accessibility_caption": record.get("accessibility_caption"),
             "url": candidates[0].get("url") if candidates else None}]


POST_FIELDS = {
    "type": const("post_data"),
    "id": "id",
    "post_code": "code",
    "like_count": "like_count",
    "comment_count": "comment_count",
    "created_at": F(fn=lambda r: to_iso(_post_created_at(r))),
    "text": F(fn=_post_caption_text),
    "hashtags": F(fn=_tags(HASHTAG_RE, _post_caption_text)),
    "mentions": F(fn=_tags(MENTION_RE, _post_caption_text)),
    "date_id": F(fn=lambda r: to_date(_post_created_at(r))),
    "url": F(fn=lambda r: f"https://www.instagram.com/p/{r.get('code')}"),
    "is_carousel": F(fn=lambda r: True if r.get("carousel_media") else False),
    "posts": const(True),
    "crawler_ig": const(True),
    "all_slides": F(fn=_slides),
}

user_profile_mapper = FieldMapper(
    items=f"{USER_EDGES}[0].node.user", name="instagram.user_profile",
    fields={"type": const("user_profile"), "username": "username", "full_name": "full_name",
            "profile_pic_url_hd": "hd_profile_pic_url_info.url"})

user_posts_mapper = FieldMapper(items=USER_EDGES, item_path="node", fields=POST_FIELDS,
                                name="instagram.user_posts")


def parse_user_timeline(data):
    """Profil (dari edge pertama) lalu semua post; list kosong jika tidak ada edge."""
    if not get_path(data, USER_EDGES):
        return []
    return user_profile_mapper(data) + user_posts_mapper(data)


for _name, _parser in (("instagram.search", search_mapper), ("instagram.comments", comments_mapper),
                       ("instagram.user_profile", user_profile_mapper),
                       ("instagram.user_posts", user_posts_mapper),
                       ("instagram.user_timeline", parse_user_timeline)):
    register_mapper(_name, _parser, replace=True)
