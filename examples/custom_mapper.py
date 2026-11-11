"""Menambah FieldMapper sendiri: transform custom, mapper dari JSON, turunan (extend), dan pengecekan sample.

Jalankan dari root repo:  python -m examples.custom_mapper
"""
import os

from cdp_scraper import F, FieldMapper, const, load_mappers, register_mapper, register_transform
from cdp_scraper.presets.tiktok import search_mapper  # noqa: F401  (mendaftarkan 'tiktok.*')

SAMPLE = {"result": {"posts": [
    {"post_id": 11, "kind": "video", "caption": "Kopi enak #kopi", "author": {"handle": "Dina"},
     "metrics": {"likes": "12", "views": 3400}, "published": "2025-03-01T10:00:00+07:00",
     "tags": [{"label": "kopi"}, {"label": ""}]},
    {"post_id": 12, "kind": "ad", "caption": "Promo", "author": {"handle": "toko"},
     "metrics": {"likes": 1, "views": 90}, "sponsor": {"brand": "TokoX"}, "tags": []},
]}}

# 1) transform custom: dipakai dari Python maupun JSON lewat namanya
register_transform("ribuan", lambda v: round(int(v) / 1000, 1))

# 2) mapper dari JSON (tanpa kode parser); file berurutan nama: feed_base lalu feed_with_ads (extends)
here = os.path.join(os.path.dirname(__file__), "mappers")
feed, feed_ads = load_mappers(here)

# 3) turunan lewat Python: ambil mapper yang ada, tambah/timpa/buang field
feed_slim = feed.extend(
    fields={"text_upper": F("caption", transform=["str", "upper"]), "source": const("contoh.com")},
    remove=["views_ribuan", "platform"],
    name="contoh.feed_slim")
register_mapper(feed_slim.name, feed_slim, replace=True)

# 4) mapper baru dari nol, langsung di Python
mini = FieldMapper(items="result.posts", name="contoh.mini",
                   fields={"id": ("post_id", "str", ""), "likes": F("metrics.likes", transform="int", default=0)})

if __name__ == "__main__":
    print("feed      :", feed(SAMPLE))
    print("feed_ads  :", [(i["id"], i["kind"], i["sponsor"]) for i in feed_ads(SAMPLE)])
    print("feed_slim :", sorted(feed_slim(SAMPLE)[0]))
    print("mini      :", mini(SAMPLE))
    print()
    print(feed.explain(SAMPLE))
