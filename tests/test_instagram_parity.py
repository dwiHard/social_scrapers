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
