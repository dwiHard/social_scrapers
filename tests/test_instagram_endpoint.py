"""Preset Instagram dipakai lewat Scraper: media_id ditempel, halaman terakhir dikenali, profil tidak terbuang."""
import unittest

from cdp_scraper import CDPConfig, CDPSessionManager, Endpoint, Platform, Scraper
from cdp_scraper.presets import instagram as ig
from tests import sample_instagram as S
from tests.fakes import FAST, FakeContext, FakePage, fake_engine, run, scroll_emit

GRAPHQL = "https://www.instagram.com/graphql/query"


class Ctx(FakeContext):
    async def new_page(self):
        page = FakePage(self.batches, api_url=GRAPHQL)
        self.pages_made.append(page)
        return page


def platform():
    common = dict(api_match="graphql/query", initial_sleep=0, max_scrolls=6, stall_limit=2,
                  scroll=scroll_emit, capture_options=FAST)
    return Platform("instagram", endpoints=[
        Endpoint("comments", url="https://www.instagram.com/p/{code}/", parser="instagram.comments",
                 params=("code", "media_id"), label="code", key="id", end=ig.comments_exhausted,
                 attach_params={"media_id": "media_id"}, **common),
        Endpoint("user", url="https://www.instagram.com/{username}/", parser="instagram.user_timeline",
                 params=("username",), label="username", key=ig.item_key, **common),
        Endpoint("search", url="https://www.instagram.com/explore/search/keyword/?q={keyword}",
                 parser="instagram.search", params=("keyword",), label="keyword", key="id", **common),
    ])


def scraper(batches):
    manager = CDPSessionManager(CDPConfig(), engine_factory=fake_engine(Ctx(batches)))
    return Scraper(platform(), manager=manager)


class InstagramEndpointTests(unittest.TestCase):
    def test_comments_paginate_until_last_page_and_attach_media_id(self):
        page1 = S.comments_payload(3, has_next=True)
        unrelated = {"data": {"xdt_something_else": {"ok": True}}}
        page2 = {"data": {"conn": {"edges": [{"node": S.comment(3)}, {"node": S.comment(4)}, {"node": S.comment(5)}],
                                   "page_info": {"has_next_page": False, "end_cursor": None}}}}
        res = run(scraper([page1, unrelated, page2]).run("comments", {"code": "ABC", "media_id": "M99"}, limit=50))
        self.assertEqual([c["id"] for c in res.items], ["c1", "c2", "c3", "c4", "c5"])
        self.assertEqual({c["media_id"] for c in res.items}, {"M99"})
        self.assertEqual(res.stopped_by, "exhausted")
        self.assertEqual(res.items[0]["c_created_at"], "2023-11-14T22:13:21Z")

    def test_user_timeline_keeps_profile_item_once(self):
        res = run(scraper([S.USER, S.USER]).run("user", {"username": "dina"}, limit=50))
        self.assertEqual([ig.item_key(i) for i in res.items], ["dina", "p1", "p2", "p3"])
        self.assertEqual(res.items[0]["type"], "user_profile")

    def test_search_via_name_and_unrelated_responses_ignored(self):
        res = run(scraper([{"data": {"nothing": 1}}, S.SEARCH]).run("search", {"keyword": "kopi"}, limit=50))
        self.assertEqual([i["id"] for i in res.items], ["1", "2", "3", "4"])
        self.assertEqual(res.items[0]["owner_username"], "dina")


if __name__ == "__main__":
    unittest.main()
