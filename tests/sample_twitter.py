def tweet(i, name="abc", **over):
    result = {"__typename": "Tweet", "rest_id": str(i),
      "core": {"user_results": {"result": {"rest_id": "9", "core": {"screen_name": name, "name": name.upper()},
               "avatar": {"image_url": "https://p.example/av.jpg"},
               "legacy": {"followers_count": 5, "friends_count": 2, "statuses_count": 11},
               "is_blue_verified": True}}},
      "views": {"count": "100"},
      "legacy": {"full_text": "hi #x @y", "favorite_count": 5, "retweet_count": 1, "reply_count": 2,
                 "quote_count": 0, "bookmark_count": 1, "created_at": "Wed Oct 10 20:19:24 +0000 2018", "lang": "in",
                 "in_reply_to_status_id_str": "77", "conversation_id_str": "55",
                 "entities": {"hashtags": [{"text": "x"}], "user_mentions": [{"screen_name": "y", "id_str": "7"}]},
                 "extended_entities": {"media": [{"media_url_https": "https://p.example/1.jpg"}, {"media_url_https": "bukan-url"}]}}}
    result.update(over)
    return {"entryId": f"tweet-{i}", "content": {"itemContent": {"tweet_results": {"result": result}}}}

wrapped = tweet(3, "wrapped")
inner = wrapped["content"]["itemContent"]["tweet_results"]["result"]
wrapped["content"]["itemContent"]["tweet_results"]["result"] = {"__typename": "TweetWithVisibilityResults", "tweet": inner}
longnote = tweet(4, "long", note_tweet={"note_tweet_results": {"result": {"text": "teks panjang sekali"}}})
legacy_user = tweet(5, "old")
u = legacy_user["content"]["itemContent"]["tweet_results"]["result"]["core"]["user_results"]["result"]
u["legacy"]["screen_name"] = "old_legacy"; u["core"] = {}; u.pop("avatar"); u["legacy"]["profile_image_url_https"] = "https://p.example/old.jpg"
retweet = tweet(6, "rt"); retweet["content"]["itemContent"]["tweet_results"]["result"]["legacy"]["retweeted_status_result"] = {"x": 1}

SAMPLE = {"data": {"search_by_raw_query": {"search_timeline": {"timeline": {"instructions": [
    {"type": "TimelineAddEntries", "entries": [tweet(1), tweet(2, "dua"), wrapped, longnote, legacy_user, retweet,
        {"entryId": "cursor-bottom-1", "content": {"value": "abc"}},
        {"entryId": "who-to-follow", "content": {"items": []}}]},
    {"type": "TimelineReplaceEntry", "entry": tweet(9, "replace")},
]}}}}}
EMPTY = {"data": {}}
