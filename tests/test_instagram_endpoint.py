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

    def test_comments_over_rest_endpoint_with_api_match_regex(self):
        rest_url = "https://www.instagram.com/api/v1/media/3081573788433385479/comments/?can_support_threading=true"

        class RestCtx(FakeContext):
            async def new_page(self):
                page = FakePage(self.batches, api_url=rest_url)
                self.pages_made.append(page)
                return page

        plat = platform()
        plat.endpoint("comments").api_match = ig.COMMENTS_API_MATCH
        batches = [S.rest_comments(3, has_more=True), S.rest_comments(2, has_more=False, start=4)]
        manager = CDPSessionManager(CDPConfig(), engine_factory=fake_engine(RestCtx(batches)))
        res = run(Scraper(plat, manager=manager).run("comments", {"code": "ABC", "media_id": "M7"}, limit=50))
        self.assertEqual([c["id"] for c in res.items], ["c1", "c2", "c3", "c4", "c5"])
        self.assertEqual({c["media_id"] for c in res.items}, {"M7"})
        self.assertEqual(res.stopped_by, "exhausted")

    def test_diagnostics_explain_why_nothing_was_captured(self):
        other = "https://www.instagram.com/api/v1/media/999/comments/?x=1"

        class OtherCtx(FakeContext):
            async def new_page(self):
                page = FakePage(self.batches, api_url=other)
                self.pages_made.append(page)
                return page

        manager = CDPSessionManager(CDPConfig(), engine_factory=fake_engine(OtherCtx([S.rest_comments(2)])))
        res = run(Scraper(platform(), manager=manager).run("comments", {"code": "ABC", "media_id": "M7"}, limit=5))
        self.assertEqual((res.status, res.count), ("no_data", 0))
        net = res.diagnostics["network"]
        self.assertEqual((net["matched"], net["parse_errors"]), (0, 0))

    def test_real_world_flow_ssr_first_page_then_pagination_by_scrolling(self):
        """Meniru diagnostics nyata: redirect 301, HTML berisi komentar halaman 1, lima response GraphQL tak terkait
        (salah satunya koneksi dengan has_next_page=false), lalu halaman 2 baru datang setelah scroll."""
        doc, gql = "https://www.instagram.com/p/DfxPv2GS3az/", "https://www.instagram.com/api/graphql"
        on_goto = [("https://www.instagram.com/p/DfxPv2GS3az", "", 301), (doc, S.post_html(count=3, has_next=True)),
                   (gql, S.UNRELATED), (gql, S.EMPTY_CONNECTION), (gql, {"data": {"viewer": {"id": "1"}}}),
                   (gql, S.UNRELATED), (gql, {"data": None}),
                   ("https://www.instagram.com/ajax/bz?a=1", "bukan json")]
        on_scroll = [(gql, S.comments_page([4, 5], False))]

        plat = platform()
        endpoint = plat.endpoint("comments")
        endpoint.api_match = ig.COMMENTS_API_MATCH
        endpoint.capture_options = {**FAST, "body_parser": ig.parse_body}
        manager = CDPSessionManager(CDPConfig(), engine_factory=fake_engine(Ctx([on_goto, on_scroll])))
        res = run(Scraper(plat, manager=manager).run("comments", {"code": "DfxPv2GS3az", "media_id": "4031072400074045107"}, limit=50))

        self.assertEqual([c["id"] for c in res.items], ["c1", "c2", "c3", "c4", "c5"])
        self.assertEqual({c["media_id"] for c in res.items}, {"4031072400074045107"})
        self.assertEqual(res.stopped_by, "exhausted")
        self.assertGreaterEqual(res.diagnostics["scrolls"], 1)          # bug lama: scrolls = 0
        net = res.diagnostics["network"]
        self.assertEqual((net["bad_status"], net["parse_errors"]), (0, 0))
        self.assertEqual(net["matched"], 7)                              # dokumen + 5 graphql + halaman 2 (301 tidak dihitung)

    def test_old_behaviour_stopped_before_first_scroll(self):
        """Dengan hanya koneksi tak terkait di halaman, scraper tetap menunggu dan scroll (tidak berhenti dini)."""
        gql = "https://www.instagram.com/api/graphql"
        plat = platform()
        plat.endpoint("comments").api_match = ig.COMMENTS_API_MATCH
        plat.endpoint("comments").capture_options = {**FAST, "body_parser": ig.parse_body}
        manager = CDPSessionManager(CDPConfig(), engine_factory=fake_engine(Ctx([[(gql, S.UNRELATED), (gql, S.EMPTY_CONNECTION)]])))
        res = run(Scraper(plat, manager=manager).run("comments", {"code": "ABC", "media_id": "M1"}, limit=50))
        self.assertNotEqual(res.stopped_by, "exhausted")
        self.assertGreaterEqual(res.diagnostics["scrolls"], 1)
        self.assertEqual(res.count, 0)
        self.assertGreaterEqual(res.diagnostics["network"]["matched"], 2)   # kedua response diproses (+1 per scroll)

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
