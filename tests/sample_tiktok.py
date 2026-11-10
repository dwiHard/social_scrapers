VIDEO = {
  "id": "7300000000000000001", "desc": "Halo #kopi #jakarta @budi", "createTime": 1700000000,
  "author": {"id": "11", "uniqueId": "andi", "nickname": "Andi", "avatarThumb": "https://p.example/a.jpg", "verified": True},
  "stats": {"diggCount": 120, "commentCount": "7", "shareCount": 3, "playCount": 5000, "collectCount": 9},
  "authorStats": {"followingCount": 1, "followerCount": 2000, "heartCount": 99999, "videoCount": 40},
  "music": {"id": "m1", "title": "Lagu", "authorName": "Penyanyi", "album": "AL", "coverThumb": "https://p.example/m.jpg",
            "duration": 30, "original": True, "playUrl": "https://p.example/m.mp3"},
  "video": {"duration": 15, "ratio": "540p", "cover": "https://p.example/c.jpg", "playAddr": "https://p.example/v.mp4"},
  "poi": {"name": "Kafe X", "address": "Jl. A", "city": "Jakarta", "category": "Food"},
  "textExtra": [{"type": 1, "hashtagName": "kopi"}, {"type": 1, "hashtagName": "jakarta"},
                {"type": 0, "userUniqueId": "budi", "userId": 555}],
}
MINIMAL = {"id": 8, "desc": "", "author": {"uniqueId": "x"}, "stats": {}, "textExtra": []}
SEARCH = {"data": [{"type": 1, "item": VIDEO}, {"type": 4, "item": VIDEO}, {"type": 1, "item": {}}, {"type": 1, "item": MINIMAL}]}
USER = {"itemList": [VIDEO, MINIMAL, None]}
