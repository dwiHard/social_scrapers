def media(i, **extra):
    record = {
        "pk": str(i), "code": f"C{i}", "taken_at": 1700000000 + i, "comment_count": 3, "like_count": 10,
        "caption": {"text": f"halo #kopi #jakarta @budi {i}", "created_at": 1700000000 + i},
        "user": {"username": "dina", "full_name": "Dina", "id": "77", "pk": "78",
                 "profile_pic_url": "https://p.example/x.jpg", "is_verified": True, "is_private": False},
        "location": {"name": "Jakarta", "lat": -6.2, "lng": 106.8},
        "music_metadata": {"music_info": {"music_asset_info": {"title": "Lagu", "display_artist": "Penyanyi"}}},
        "carousel_media": [{"image_versions2": {"candidates": [{"url": "https://p.example/1.jpg", "width": 1, "height": 1}]}}],
        "image_versions2": {"candidates": [{"url": "https://p.example/main.jpg"}]},
    }
    record.update(extra)
    return record


SEARCH = {"data": {"xdt_fbsearch__top_serp_graphql": {"edges": [
    {"node": {"items": [{"media": media(1)}, {"media": media(2)}]}},
    {"node": media(3)},
    {"node": {"items": [{"media": None, "pk": "4", "code": "C4"}]}},
    {"node": {"items": [{"media": {"foo": 1}}]}},
    {"node": {}},
]}}}


def comment(i, **extra):
    record = {"pk": f"c{i}", "text": f"bagus #kopi @budi {i}", "created_at": 1700000000 + i,
              "comment_like_count": 4, "child_comment_count": 2,
              "user": {"pk": "9", "id": "9x", "username": f"u{i}", "is_verified": False,
                       "profile_pic_url": "https://p.example/u.jpg"}}
    record.update(extra)
    return record


def comments_payload(count=3, has_next=True, depth=1):
    connection = {"edges": [{"node": comment(i)} for i in range(1, count + 1)],
                  "page_info": {"has_next_page": has_next, "end_cursor": "abc"}}
    wrapped = {"xdt_api__v1__media__media_id__comments__connection": connection}
    for level in range(depth - 1):
        wrapped = {f"lapis{level}": wrapped, "lain": [{"edges": [1]}]}
    return {"data": wrapped}


USER_KEY = "xdt_api__v1__feed__user_timeline_graphql_connection"


def post(i, carousel=True, **extra):
    record = {"id": f"p{i}", "code": f"CODE{i}", "like_count": 5, "comment_count": 2,
              "caption": {"text": f"foto #kopi @budi {i}", "created_at": 1700000000 + i},
              "user": {"username": "dina", "full_name": "Dina", "hd_profile_pic_url_info": {"url": "https://p.example/hd.jpg"}},
              "accessibility_caption": "satu foto",
              "image_versions2": {"candidates": [{"url": "https://p.example/main.jpg"}]}}
    if carousel:
        record["carousel_media"] = [
            {"accessibility_caption": "foto 1", "image_versions2": {"candidates": [{"url": "https://p.example/s1.jpg"}]}},
            {"accessibility_caption": "foto 2", "image_versions2": {"candidates": [{"url": "https://p.example/s2.jpg"}]}}]
    record.update(extra)
    return record


USER = {"data": {USER_KEY: {"edges": [{"node": post(1)}, {"node": post(2, carousel=False)}, {"node": post(3)}]}}}
