"""Contoh platform TikTok: mapping diambil dari preset, tinggal dirakit jadi Endpoint."""
from cdp_scraper import Endpoint, Platform, make_scroller
from cdp_scraper.presets.tiktok import search_mapper, user_videos_mapper

OVERLAYS = ('[data-e2e="modal-close-inner-button"]', 'div[class*="ModalClose"]')

search_parser = search_mapper
user_videos_parser = user_videos_mapper

tiktok = Platform(
    name="tiktok",
    overlay_selectors=OVERLAYS,
    endpoints=[
        Endpoint(
            "search", url="https://www.tiktok.com/search?q={keyword}",
            api_match="search/general/full", parser="tiktok.search",
            params=("keyword",), label="keyword", limit=20, max_limit=20,
            initial_sleep=4,
            scroll=make_scroller(wheel=2500, containers=True,
                                 click_pattern="load more|lihat lebih banyak|muat lebih banyak"),
        ),
        Endpoint(
            "user_videos", url="https://www.tiktok.com/@{username}",
            api_match="post/item_list", parser="tiktok.user_videos",
            params=("username",), label="username", limit=30,
            normalize=lambda p: {**p, "username": str(p["username"]).lstrip("@")},
        ),
    ],
)
