"""Preset Instagram harus setara dengan MediaParser lama (search, komentar, user timeline)."""
import contextlib
import copy
import io
import random
import unittest
import warnings

from cdp_scraper import get_mapper
from cdp_scraper.presets import instagram as ig
from tests import sample_instagram as S
from tests.legacy_instagram import MediaParser as Legacy

warnings.filterwarnings("ignore", category=DeprecationWarning)

# null pada key ini sengaja dibiarkan: pada parser lama menyebabkan crash (hasil trial dilewati), bukan beda hasil
KEEP_NONE = {"edges", "node", "items", "page_info", "data", "xdt_fbsearch__top_serp_graphql", "text",
             "candidates", "carousel_media", "user", "caption", "image_versions2", "hd_profile_pic_url_info",
             S.USER_KEY}


def mutate(obj, rng, p_delete=0.05, p_none=0.05):
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            roll = rng.random()
            if roll < p_delete:
                continue
            if roll < p_delete + p_none and key not in KEEP_NONE:
                out[key] = None
                continue
            out[key] = mutate(value, rng, p_delete, p_none)
        return out
    if isinstance(obj, list):
        return [mutate(x, rng, p_delete, p_none) for x in obj if rng.random() > 0.05]
    if isinstance(obj, int) and not isinstance(obj, bool) and rng.random() < 0.12:
        return str(obj)
    return obj


def quiet(fn, *args):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args)


def differences(actual, expected):
    out = []
    for j, (a, e) in enumerate(zip(actual, expected)):
        for key in sorted(set(a) | set(e)):
            if a.get(key, "<none>") != e.get(key, "<none>"):
                out.append(f"item{j}.{key}: lama={e.get(key)!r} mapping={a.get(key)!r}")
    return out


def compare(testcase, legacy_fn, mapper, builder, trials, label, clean=lambda x: x):
    rng = random.Random(20260103)
    compared = 0
    for i in range(trials):
        payload = builder(rng)
        try:
            expected = legacy_fn(payload)
        except Exception:
            continue
        if isinstance(expected, dict) or any(isinstance(x, dict) and "error" in x for x in expected):
            continue
        expected = clean(expected)
        compared += 1
        actual = mapper(payload)
        testcase.assertEqual(len(actual), len(expected), f"{label} trial {i}: jumlah item beda")
        testcase.assertEqual(differences(actual, expected), [], f"{label} trial {i}")
    testcase.assertGreater(compared, trials * 0.4, f"terlalu banyak trial dilewati: {compared}/{trials}")
    print(f"  [{label}] dibandingkan {compared}/{trials} trial, 0 selisih")


def drop_empty_profile(items):
    return [i for i in items if not (i.get("type") == "user_profile" and not any(
        i.get(k) for k in ("username", "full_name", "profile_pic_url_hd")))]


BLANK_COMMENT = quiet(Legacy.parse_media_data_comment, {"data": {"c": {"edges": [{"node": {}}], "page_info": {}}}}, None)[0][0]


class SearchParity(unittest.TestCase):
    def test_sample(self):
        expected = quiet(Legacy.parse_media_data, S.SEARCH)
        self.assertEqual(ig.search_mapper(S.SEARCH), expected)
        self.assertEqual([i["id"] for i in expected], ["1", "2", "3", "4"])
        self.assertEqual(expected[0]["music_title"], "Lagu")
        self.assertEqual(expected[0]["image_urls"], "https://www.instagram.com/p/C1/media/?size=m")
        self.assertEqual(expected[0]["p_created_at"], "2023-11-14T22:13:21Z")

    def test_random(self):
        compare(self, lambda p: quiet(Legacy.parse_media_data, p), ig.search_mapper,
                lambda rng: mutate(copy.deepcopy(S.SEARCH), rng), 400, "search")

    def test_documented_difference_no_error_items(self):
        self.assertEqual(quiet(Legacy.parse_media_data, {"data": {}}), [{"error": "Data edges tidak ditemukan"}])
        for bad in ({"data": {}}, {}, None, [], "x"):
            self.assertEqual(ig.search_mapper(bad), [])


class CommentsParity(unittest.TestCase):
    def test_sample_and_media_id_placeholder(self):
        payload = S.comments_payload(3)
        expected, page = quiet(Legacy.parse_media_data_comment, payload, None)
        self.assertEqual(ig.comments_mapper(payload), expected)
        self.assertEqual(ig.comments_page_info(payload), page)
        with_id, _ = quiet(Legacy.parse_media_data_comment, payload, "M99")
        self.assertEqual([c["media_id"] for c in with_id], ["M99"] * 3)

    def test_nested_connection_found_anywhere(self):
        payload = S.comments_payload(2, depth=4)
        expected, page = quiet(Legacy.parse_media_data_comment, payload, None)
        self.assertEqual(len(expected), 2)
        self.assertEqual(ig.comments_mapper(payload), expected)
        self.assertEqual(ig.comments_page_info(payload), page)

    def test_page_info_and_exhausted(self):
        for has_next in (True, False):
            payload = S.comments_payload(1, has_next=has_next)
            self.assertEqual(ig.comments_page_info(payload), quiet(Legacy.parse_media_data_comment, payload, None)[1])
            self.assertEqual(ig.comments_exhausted(payload), not has_next)
        for unrelated in ({}, {"data": {"x": 1}}, None, []):
            self.assertFalse(ig.comments_exhausted(unrelated))
            self.assertEqual(ig.comments_page_info(unrelated), {"has_next_page": False, "end_cursor": None})
            self.assertEqual(ig.comments_mapper(unrelated), [])

    def test_random(self):
        compare(self, lambda p: quiet(Legacy.parse_media_data_comment, p, None)[0], ig.comments_mapper,
                lambda rng: mutate(S.comments_payload(4, depth=2), rng), 400, "comments",
                clean=lambda items: [c for c in items if c != BLANK_COMMENT])


class RestCommentsTests(unittest.TestCase):
    def test_rest_payload_gives_same_records_as_graphql_shape(self):
        expected, _ = quiet(Legacy.parse_media_data_comment, S.comments_payload(3), None)
        self.assertEqual(ig.comments_mapper(S.rest_comments(3)), expected)

    def test_exhausted_flags_for_rest(self):
        self.assertFalse(ig.comments_exhausted(S.rest_comments(2, has_more=True)))
        self.assertTrue(ig.comments_exhausted(S.rest_comments(2, has_more=False)))
        self.assertFalse(ig.comments_exhausted({"comments": []}))
        self.assertFalse(ig.comments_exhausted({"comments": "bukan list", "has_more_comments": True}))

    def test_graphql_behaviour_unchanged_and_unrelated_ignored(self):
        self.assertTrue(ig.comments_exhausted(S.comments_payload(1, has_next=False)))
        self.assertFalse(ig.comments_exhausted(S.comments_payload(1, has_next=True)))
        for unrelated in ({}, {"data": {"x": 1}}, None, [], {"status": "ok"}):
            self.assertFalse(ig.comments_exhausted(unrelated))
            self.assertEqual(ig.comments_mapper(unrelated), [])

    def test_api_match_covers_graphql_and_rest_only(self):
        for url in ("https://www.instagram.com/graphql/query", "https://www.instagram.com/api/graphql",
                    "https://www.instagram.com/api/v1/media/3081573788433385479/comments/?can_support_threading=true"):
            self.assertTrue(ig.COMMENTS_API_MATCH.search(url), url)
        for url in ("https://www.instagram.com/api/v1/feed/timeline/", "https://www.instagram.com/api/v1/media/123/info/",
                    "https://static.cdninstagram.com/rsrc.php/abc.js"):
            self.assertFalse(ig.COMMENTS_API_MATCH.search(url), url)


class StrictCommentDetectionTests(unittest.TestCase):
    """Koneksi lain di halaman post (saran akun, dll) tidak boleh dianggap komentar maupun penanda 'habis'."""

    def test_unrelated_connections_are_ignored(self):
        for payload in (S.UNRELATED, S.EMPTY_CONNECTION):
            self.assertEqual(ig.comments_mapper(payload), [])
            self.assertFalse(ig.comments_exhausted(payload))
        legacy_garbage = quiet(Legacy.parse_media_data_comment, S.UNRELATED, None)[0]
        self.assertEqual([c["id"] for c in legacy_garbage], ["s1"])   # parser lama menganggapnya komentar

    def test_exhausted_needs_comments_with_edges(self):
        self.assertFalse(ig.comments_exhausted(S.comments_page([], False)))   # kosong: belum pasti habis
        self.assertTrue(ig.comments_exhausted(S.comments_page([1], False)))
        self.assertFalse(ig.comments_exhausted(S.comments_page([1], True)))

    def test_shape_heuristic_when_key_name_is_unknown(self):
        payload = {"data": {"nama_tak_dikenal": {"edges": [{"node": S.comment(1)}], "page_info": {"has_next_page": False}}}}
        self.assertEqual([c["id"] for c in ig.comments_mapper(payload)], ["c1"])
        self.assertTrue(ig.comments_exhausted(payload))

    def test_picks_the_comment_connection_among_several(self):
        payload = {"data": {**S.UNRELATED["data"], **S.comments_page([1, 2], True)["data"], **S.EMPTY_CONNECTION["data"]}}
        self.assertEqual([c["id"] for c in ig.comments_mapper(payload)], ["c1", "c2"])
        self.assertFalse(ig.comments_exhausted(payload))


class EmbeddedDataTests(unittest.TestCase):
    def test_comments_embedded_in_html(self):
        html = S.post_html(count=3, has_next=True)
        payloads = ig.parse_body(html)
        self.assertEqual(len(payloads), 1)
        self.assertEqual([c["id"] for c in ig.comments_mapper(payloads[0])], ["c1", "c2", "c3"])
        self.assertFalse(ig.comments_exhausted(payloads[0]))
        self.assertTrue(ig.comments_exhausted(ig.parse_body(S.post_html(count=2, has_next=False))[0]))

    def test_user_timeline_embedded_in_html(self):
        html = S.post_html(extra_json=[S.USER["data"]])   # dibungkus lagi agar bersarang di dalam JSON lain
        html = html.replace("</head>", '<script type="application/json">' + __import__("json").dumps({"deep": [S.USER["data"]]}) + "</script></head>")
        payloads = [p for p in ig.embedded_payloads(html) if S.USER_KEY in p["data"]]
        self.assertGreaterEqual(len(payloads), 1)
        self.assertEqual([i["type"] for i in ig.parse_user_timeline(payloads[0])], ["user_profile"] + ["post_data"] * 3)

    def test_no_embedded_data_and_broken_scripts(self):
        for html in ("<html><body>kosong</body></html>", '<script type="application/json">{rusak page_info</script>',
                     "<script>var page_info = 1;</script>"):
            self.assertEqual(ig.embedded_payloads(html), [], html)

    def test_document_url_patterns(self):
        for url in ("https://www.instagram.com/p/DfxPv2GS3az/", "https://www.instagram.com/p/DfxPv2GS3az",
                    "https://www.instagram.com/reel/DfxPv2GS3az/?igsh=x", "https://www.instagram.com/natgeo/p/DfxPv2GS3az/"):
            self.assertTrue(ig.COMMENTS_API_MATCH.search(url), url)
        for url in ("https://www.instagram.com/p/DfxPv2GS3az/media/?size=m", "https://www.instagram.com/ajax/bz?a=1",
                    "https://static.cdninstagram.com/btmanifest/1054856395/instagram/main"):
            self.assertFalse(ig.COMMENTS_API_MATCH.search(url), url)
        for url in ("https://www.instagram.com/natgeo/", "https://www.instagram.com/natgeo", "https://www.instagram.com/api/graphql"):
            self.assertTrue(ig.USER_API_MATCH.search(url), url)
        self.assertFalse(ig.USER_API_MATCH.search("https://www.instagram.com/"))


class UserTimelineParity(unittest.TestCase):
    def test_sample(self):
        expected = quiet(Legacy.parse_user_data, S.USER)
        self.assertEqual(ig.parse_user_timeline(S.USER), expected)
        self.assertEqual([i["type"] for i in expected], ["user_profile", "post_data", "post_data", "post_data"])
        self.assertEqual([len(i["all_slides"]) for i in expected[1:]], [2, 1, 2])
        self.assertEqual(expected[1]["url"], "https://www.instagram.com/p/CODE1")

    def test_registered_names_and_key(self):
        self.assertEqual(get_mapper("instagram.user_timeline")(S.USER), ig.parse_user_timeline(S.USER))
        self.assertEqual([ig.item_key(i) for i in ig.parse_user_timeline(S.USER)], ["dina", "p1", "p2", "p3"])

    def test_random(self):
        compare(self, lambda p: quiet(Legacy.parse_user_data, p), ig.parse_user_timeline,
                lambda rng: mutate(copy.deepcopy(S.USER), rng, p_delete=0.03, p_none=0.03), 400, "user_timeline",
                clean=drop_empty_profile)

    def test_documented_differences(self):
        self.assertEqual(quiet(Legacy.parse_user_data, {"data": {}}), {"data": []})
        self.assertEqual(ig.parse_user_timeline({"data": {}}), [])
        no_caption = copy.deepcopy(S.USER)
        no_caption["data"][S.USER_KEY]["edges"][0]["node"]["caption"] = None
        self.assertIsInstance(quiet(Legacy.parse_user_data, no_caption), dict)
        posts = ig.parse_user_timeline(no_caption)
        self.assertEqual((len(posts), posts[1]["created_at"], posts[1]["text"]), (4, None, ""))
        no_user = copy.deepcopy(S.USER)
        del no_user["data"][S.USER_KEY]["edges"][0]["node"]["user"]
        self.assertEqual(quiet(Legacy.parse_user_data, no_user)[0]["username"], None)
        self.assertEqual([i["type"] for i in ig.parse_user_timeline(no_user)], ["post_data"] * 3)


class ParseBodyTests(unittest.TestCase):
    def test_variants(self):
        import json
        doc = {"data": {"a": 1}}
        text = json.dumps(doc)
        self.assertEqual(ig.parse_body(text), [doc])
        self.assertEqual(ig.parse_body("for (;;);" + text), [doc])
        self.assertEqual(ig.parse_body("  for (;;);" + text + "  \n"), [doc])
        self.assertEqual(ig.parse_body(text + "\n" + json.dumps({"label": "x"})), [doc, {"label": "x"}])
        self.assertEqual(ig.parse_body("sampah\n" + text + "\nsampah lagi"), [doc])
        self.assertEqual(ig.parse_body("for (;;);" + text + "\nfor (;;);" + text), [doc, doc])
        for bad in ("", "for (;;);", "bukan json sama sekali"):
            with self.assertRaises(ValueError):
                ig.parse_body(bad)
        self.assertEqual(ig.parse_body("<html></html>"), [])   # halaman HTML tanpa data tertanam: bukan error


class HelpersParity(unittest.TestCase):
    def test_timestamp_helpers(self):
        for ts in (1700000000, 1700000000123, 1.5, 0, None, "x", "1700000000", -5, 10**20):
            expected_iso = quiet(Legacy._convert_timestamp_to_iso, ts) if ts else None
            expected_date = quiet(Legacy._convert_timestamp_to_date, ts) if ts else None
            self.assertEqual(ig.to_iso(ts), expected_iso, ts)
            self.assertEqual(ig.to_date(ts), expected_date, ts)

    def test_loads_response_text(self):
        class Resp:
            text = '  for (;;);{"a": 1}  '
        self.assertEqual(ig.loads_response_text(Resp()), Legacy.parse_json_response(Resp()))
        self.assertEqual(ig.loads_response_text('{"b": 2}'), {"b": 2})


if __name__ == "__main__":
    unittest.main()
