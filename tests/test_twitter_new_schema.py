"""Preset twitter.search harus membaca skema baru (SearchByRawQuery) dan tetap membaca skema lama."""
import json
import os
import unittest

from cdp_scraper.presets.twitter import SEARCH_API_MATCH, search_mapper
from tests.sample_twitter import SAMPLE

NEW = json.load(open(os.path.join(os.path.dirname(__file__), "sample_search_by_raw_query.json")))


class TwitterNewSchema(unittest.TestCase):
    def test_api_match(self):
        self.assertTrue(SEARCH_API_MATCH.search("https://api.x.com/graphql/abc/SearchByRawQuery?variables=1"))
        self.assertTrue(SEARCH_API_MATCH.search("https://x.com/i/api/graphql/abc/SearchTimeline?variables=1"))
        self.assertFalse(SEARCH_API_MATCH.search("https://x.com/i/api/graphql/abc/TweetDetail?variables=1"))

    def test_new_schema_fields(self):
        rows = search_mapper(NEW)
        self.assertEqual(len(rows), 3)
        r = rows[0]
        self.assertEqual((r["id"], r["created_at"], r["dateid"]), ("2125159986729034024", "2026-11-24T09:29:59Z", "2026-11-24"))
        self.assertEqual((r["like__s"], r["view_count"], r["user_followers_count"], r["statuses_count"]),
                         (2, 14769, 10124827, 447563))
        self.assertEqual((r["user_screen_name"], r["hashtags"], r["verified__b"]), ("infoBMKG", ["Gempa", "BMKG"], True))
        self.assertTrue(r["text"].startswith("#Gempa Info Gempa"))
        self.assertTrue(r["media_urls"][0].startswith("https://pbs.twimg.com/"))
        self.assertEqual(search_mapper.report(NEW)["empty_fields"].count("text"), 0)

    def test_old_schema_still_works(self):
        rows = search_mapper(SAMPLE)
        self.assertGreaterEqual(len(rows), 5)
        self.assertEqual(rows[0]["like__s"], 5)


if __name__ == "__main__":
    unittest.main()
