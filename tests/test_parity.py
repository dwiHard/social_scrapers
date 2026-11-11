"""Mapping preset TikTok harus setara dengan parser lama untuk data acak."""
import copy
import random
import unittest

import cdp_scraper.presets.tiktok as preset
from tests import legacy_tiktok as legacy
from tests.sample_tiktok import MINIMAL, VIDEO

COMMENT = {"cid": "c1", "aweme_id": "123", "text": "mantap", "create_time": 1700000000, "digg_count": 5,
           "reply_comment_total": 2, "comment_language": "id", "reply_to_reply_id": "c0", "reply_id": "c0",
           "user": {"unique_id": "u1", "nickname": "U1", "uid": "100",
                    "avatar_thumb": {"url_list": ["https://p/x.jpg"]}}}

# nilai None pada key ini memang diperlakukan beda: parser lama membiarkan None, mapping memakai default
KEEP_NONE = {"id", "uniqueId", "text", "reply_comment_total", "digg_count", "textExtra", "user", "video",
             "author", "stats", "authorStats", "music"}


def mutate(obj, rng, p_delete=0.1, p_none=0.06):
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
        return [mutate(x, rng, p_delete, p_none) for x in obj if rng.random() > 0.1]
    if isinstance(obj, int) and not isinstance(obj, bool) and rng.random() < 0.15:
        return str(obj)
    return obj


def base_video(rng):
    video = copy.deepcopy(VIDEO)
    extra = video["textExtra"]
    extra.append({"type": 0, "userUniqueId": "tanpa_id"})
    extra.append({"type": 1, "hashtagName": ""})
    extra.append({"type": 0, "userUniqueId": "", "userId": 1})
    extra.append({"type": 2, "foo": "bar"})
    rng.shuffle(extra)
    return video


def compare(testcase, legacy_fn, mapper, builder, trials, label):
    rng = random.Random(20260101)
    compared = skipped = 0
    for i in range(trials):
        payload = builder(rng)
        try:
            expected = legacy_fn(payload)
        except Exception:
            skipped += 1
            continue
        compared += 1
        actual = mapper(payload)
        diffs = [f"item{j}.{k}: lama={e.get(k)!r} mapping={a.get(k)!r}"
                 for j, (a, e) in enumerate(zip(actual, expected)) for k in sorted(set(a) | set(e))
                 if a.get(k, "<none>") != e.get(k, "<none>")]
        testcase.assertEqual(len(actual), len(expected), f"{label} trial {i}: jumlah item beda")
        testcase.assertEqual(diffs, [], f"{label} trial {i}")
    testcase.assertGreater(compared, trials * 0.5, f"terlalu banyak trial dilewati ({skipped})")
    return compared


class ParityTests(unittest.TestCase):
    def test_search(self):
        def builder(rng):
            return {"data": [{"type": rng.choice([1, 1, 1, 4]), "item": mutate(base_video(rng), rng)}
                             for _ in range(3)] + [{"type": 1, "item": {}}, {"type": 1, "item": mutate(MINIMAL, rng)}]}
        n = compare(self, legacy.parse_tiktok_api_search, preset.search_mapper, builder, 400, "search")
        self.assertGreater(n, 200)

    def test_user_videos(self):
        def builder(rng):
            return {"itemList": [mutate(base_video(rng), rng) for _ in range(3)] + [None, {}, mutate(MINIMAL, rng)]}
        compare(self, legacy.parse_tiktok_api_user_videos, preset.user_videos_mapper, builder, 400, "user")

    def test_comments(self):
        def builder(rng):
            return {"comments": [mutate(COMMENT, rng, p_none=0.1) for _ in range(4)]}

        def legacy_fn(payload):
            return [legacy.parse_comment_data(c) for c in payload["comments"]]
        compare(self, legacy_fn, preset.comments_mapper, builder, 400, "comments")

    def test_known_difference_is_documented(self):
        payload = {"data": [{"type": 1, "item": {"id": "1", "author": {"uniqueId": None}}}]}
        self.assertEqual(preset.search_mapper(payload)[0]["url"], "https://www.tiktok.com/@/video/1")
        self.assertEqual(legacy.parse_tiktok_api_search(payload)[0]["url"], "https://www.tiktok.com/@None/video/1")


if __name__ == "__main__":
    unittest.main()
