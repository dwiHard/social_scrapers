import unittest

from examples.tiktok import search_parser, tiktok, user_videos_parser
from examples.twitter import build_search_url, search_parser as tw_parser, twitter, validate
from tests.sample_tiktok import SEARCH, USER
from tests.sample_twitter import EMPTY, SAMPLE


class TikTokExample(unittest.TestCase):
    def test_search(self):
        items = search_parser(SEARCH)
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first["url"], "https://www.tiktok.com/@andi/video/7300000000000000001")
        self.assertEqual(first["video_hashtags"], ["kopi", "jakarta"])
        self.assertEqual(first["video_mentions_user_id"], ["555"])
        self.assertEqual(first["p_created_at"], "2023-11-14T22:13:20Z")
        self.assertEqual(first["engagement_rate"], 2.6)
        self.assertTrue(first["music_is_original"] and first["is_verified"] and first["posts"])
        self.assertEqual(items[1]["id"], "8")
        self.assertIsNone(items[1]["dateid"])
        self.assertEqual(items[1]["p_created_at"], "")

    def test_user_videos_and_url(self):
        self.assertEqual(len(user_videos_parser(USER)), 2)
        ep = tiktok.endpoint("user_videos")
        params = ep.prepare_params({"username": "@andi budi"})
        self.assertEqual(ep.build_url(params), "https://www.tiktok.com/@andi%20budi")
        with self.assertRaises(ValueError):
            ep.prepare_params({})


class TwitterExample(unittest.TestCase):
    def test_parse_cases(self):
        items = tw_parser(SAMPLE)
        self.assertEqual([i["id"] for i in items], ["1", "2", "3", "4", "5", "6", "9"])
        by_id = {i["id"]: i for i in items}
        self.assertEqual(by_id["3"]["user_screen_name"], "wrapped")
        self.assertEqual(by_id["4"]["text"], "teks panjang sekali")
        self.assertEqual(by_id["5"]["user_screen_name"], "old_legacy")
        self.assertEqual(by_id["6"]["is_retweet"], 1)
        self.assertEqual(by_id["1"]["media_urls"], ["https://p.example/1.jpg"])
        self.assertEqual(by_id["1"]["created_at"], "2018-10-10T20:19:24Z")
        self.assertEqual(tw_parser(EMPTY), [])

    def test_url_and_validation(self):
        url = build_search_url(keyword="kopi susu", from_user="abc", since="2025-01-01", min_faves=10)
        self.assertEqual(url, "https://x.com/search?q=kopi%20susu%20from:abc%20since:2025-01-01%20min_faves:10"
                              "&src=trend_clicks&f=live&vertical=trends")
        self.assertIn("q=from:abc&", build_search_url(from_user="abc"))
        with self.assertRaises(ValueError):
            twitter.endpoint("search").prepare_params({})
        validate({"keyword": "a"})


if __name__ == "__main__":
    unittest.main()
