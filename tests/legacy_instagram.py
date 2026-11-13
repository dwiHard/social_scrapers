"""Salinan parser Instagram lama (referensi regresi). Jangan diubah: dipakai test_instagram_parity."""
from datetime import datetime
import traceback, re, json

class MediaParser:
    @staticmethod
    def parse_media_data(json_data):
        """Parse data media dari GraphQL Top SERP dengan mode DEBUG"""
        try:
            result = []
            
            data_root = json_data.get('data', {})
            serp_data = data_root.get('xdt_fbsearch__top_serp_graphql', {})
            edges = serp_data.get('edges', [])
            
            if not edges:
                print("[DEBUG WARNING] Edges kosong! Berhenti parsing.")
                return [{"error": "Data edges tidak ditemukan"}]

            for i, edge in enumerate(edges):
                node = edge.get('node', {})
                items = node.get('items', [node]) 
                for j, item in enumerate(items):
                    media = item.get('media') if item.get('media') else item
                    media_id =media.get('pk')
                    media_code = media.get('code')
                    if not media or (not media_id and not media_code):
                        print(f"  -> [DEBUG SKIP] Item {i}.{j} bukan media valid (ID/Code tidak ada).")
                        continue

                    owner_data = media.get('user', {})
                    username = owner_data.get('username')
                    location_data = media.get('location', {}) or {}
                    caption_data = media.get('caption', {}) or {}
                    caption_text = caption_data.get('text', '')
                    caption_created_at_timestamp = media.get('taken_at') if media else None
                    caption_created_at_iso = MediaParser._convert_timestamp_to_iso(caption_created_at_timestamp) if caption_created_at_timestamp else None
                    date_id_at = MediaParser._convert_timestamp_to_date(caption_created_at_timestamp) if caption_created_at_timestamp else None
                    carousel_media = media.get('carousel_media') or []
                    image_urls = []

                    for carousel_item in carousel_media:
                        image_versions = carousel_item.get('image_versions2', {})
                        candidates = image_versions.get('candidates', [])
                        
                        candidate_urls = []
                        for candidate in candidates:
                            url = candidate.get('url')
                            if url:
                                candidate_urls.append({
                                    'url': url,
                                    'width': candidate.get('width'),
                                    'height': candidate.get('height')
                                })
                        
                        if candidate_urls:
                            selected_candidate = candidate_urls[0]  
                            image_urls.append(selected_candidate['url'])

                    if not image_urls and media.get('image_versions2'):
                        main_candidates = media['image_versions2'].get('candidates', [])
                        if main_candidates:
                            image_urls.append(main_candidates[0].get('url'))
                            
                    music_metadata = media.get('music_metadata', {})
                    music_title = None
                    music_artist = None
                    
                    if music_metadata:
                        music_info = music_metadata.get('music_info') or {}
                        if music_info:
                            music_asset_info = music_info.get('music_asset_info') or {}
                            if music_asset_info and music_asset_info.get('title'):
                                music_title = music_asset_info.get('title')
                                music_artist = music_asset_info.get('display_artist')

                    hashtags = re.findall(r"#(\w+)", caption_text)
                    mentions = re.findall(r"@(\w+)", caption_text)
                    
                    media_info = {
                        "id": media_id, 
                        "comment_count": media.get('comment_count'),
                        "like_count": media.get('like_count'),
                        "url": f"https://www.instagram.com/p/{media_code}" if media_code else None,
                        "hashtags": hashtags,  
                        "mentions": mentions, 
                        "caption": caption_text,
                        "p_created_at": caption_created_at_iso,
                        "dateid": date_id_at,
                        "image_urls" : f"https://www.instagram.com/p/{media_code}/media/?size=m" if media_code else None,
                        "owner_full_name": owner_data.get('full_name'),
                        "owner_id": owner_data.get('id') or owner_data.get('pk'),
                        "owner_profile_pic_url": owner_data.get('profile_pic_url'),
                        "owner_username": username,
                        "is_verified": owner_data.get('is_verified'),
                        "location_name": location_data.get('name'),
                        "location_lat": location_data.get('lat'),
                        "location_lng": location_data.get('lng'),
                        "music_title": music_title,
                        "music_artist": music_artist,
                        "is_private": owner_data.get('is_private'),
                        "posts": True,
                        "crawler_ig": True,
                    }
                    
                    result.append(media_info)
            return result
            
        except (KeyError, IndexError, TypeError) as e:
            print(f"[DEBUG FATAL ERROR] Parsing gagal karena: {e}")
            return [{"error": f"Data tidak ditemukan - {e}"}]

    @staticmethod
    def _find_connection(obj):
        """Cari node connection komentar (punya 'edges') di dalam respons, apa pun nama key-nya."""
        if isinstance(obj, dict):
            if isinstance(obj.get("edges"), list) and "page_info" in obj:
                return obj
            for v in obj.values():
                found = MediaParser._find_connection(v)
                if found:
                    return found
        elif isinstance(obj, list):
            for v in obj:
                found = MediaParser._find_connection(v)
                if found:
                    return found
        return None

    @staticmethod
    def parse_media_data_comment(raw_data, media_id):
        """Ubah respons GraphQL jadi list komentar + info paginasi."""
        conn = MediaParser._find_connection(raw_data.get("data", raw_data))
        if not conn:
            return [], {"has_next_page": False, "end_cursor": None}

        comments = []
        for edge in conn.get("edges", []):
            node = edge.get("node", {}) or {}
            user = node.get("user", {}) or {}
            caption_created_at_timestamp = node.get('created_at') if node else None
            caption_created_at_iso = MediaParser._convert_timestamp_to_iso(caption_created_at_timestamp) if caption_created_at_timestamp else None
            date_id_at = MediaParser._convert_timestamp_to_date(caption_created_at_timestamp) if caption_created_at_timestamp else None
            caption_text = node.get('text', '')
            hashtags = re.findall(r"#(\w+)", caption_text)
            mentions = re.findall(r"@(\w+)", caption_text)
            comments.append({
                "id": node.get("pk") or node.get("id"),
                "text": caption_text,
                "hashtags": hashtags,
                "mentions": mentions,
                "media_id": media_id,
                "c_created_at": caption_created_at_iso,
                 "dateid": date_id_at,
                "comment_like_count": node.get("comment_like_count"),
                "reply_count": node.get("child_comment_count"),
                "user_id": user.get("pk") or user.get("id"),
                "comment_username": user.get("username"),
                "comment_is_verified": user.get("is_verified"),
                "comment_profile_pic_url": user.get("profile_pic_url"),
                "posts": False,
                "crawler_ig": True,  
            })

        page_info = conn.get("page_info", {}) or {}
        return comments, {
            "has_next_page": page_info.get("has_next_page", False),
            "end_cursor": page_info.get("end_cursor"),
        }

    @staticmethod
    def parse_json_response(response):
        """Instagram kadang menambah prefix 'for (;;);' sebelum JSON."""
        text = response.text.strip()
        if text.startswith("for (;;);"):
            text = text[len("for (;;);"):]
        return json.loads(text)

    @staticmethod
    def parse_user_data(json_data):
        """
        Menggabungkan profil, like count, dan semua carousel media.
        Ditambahkan pengecekan agar tidak error jika postingan bukan carousel.
        """
        try:
            edges = json_data.get('data', {}).get('xdt_api__v1__feed__user_timeline_graphql_connection', {}).get('edges', [])
            
            if not edges:
                return {"data": []}

            combined_list = []

            first_node = edges[0].get('node', {})
            user_raw = first_node.get('user', {})
            
            combined_list.append({
                "type": "user_profile",
                "username": user_raw.get("username"),
                "full_name": user_raw.get("full_name"),
                "profile_pic_url_hd": user_raw.get("hd_profile_pic_url_info", {}).get("url")
            })

            for edge in edges:
                node = edge.get('node', {})
                
                slides = []
                carousel_raw = node.get('carousel_media') 
                
                if carousel_raw and isinstance(carousel_raw, list):
                    for index, slide in enumerate(carousel_raw):
                        slides.append({
                            "slide_no": index + 1,
                            "accessibility_caption": slide.get('accessibility_caption'),
                            "url": slide.get('image_versions2', {}).get('candidates', [{}])[0].get('url')
                        })
                else:
                    image_versions = node.get('image_versions2', {})
                    candidates = image_versions.get('candidates', [])
                    main_url = candidates[0].get('url') if candidates else None
                    
                    slides.append({
                        "slide_no": 1,
                        "accessibility_caption": node.get('accessibility_caption'),
                        "url": main_url
                    })
                caption_node = node.get('caption')
                caption_text = caption_node.get('text') if caption_node else ""
                hashtags = re.findall(r"#(\w+)", caption_text)
                mentions = re.findall(r"@(\w+)", caption_text)
                created_at_timestamp = caption_node.get('created_at')
                created_at_iso = MediaParser._convert_timestamp_to_iso(created_at_timestamp) if created_at_timestamp else None
                date_id_at = MediaParser._convert_timestamp_to_date(created_at_timestamp) if created_at_timestamp else None

                post_obj = {
                    "type": "post_data",
                    "id": node.get("id"),
                    "post_code": node.get("code"),
                    "like_count": node.get("like_count"),
                    "comment_count": node.get("comment_count"),
                    "created_at": created_at_iso,
                    "text": caption_text,
                    "hashtags": hashtags,  
                    "mentions": mentions,  
                    "date_id": date_id_at,
                    "url": f"https://www.instagram.com/p/{node.get('code')}",
                    "is_carousel": True if carousel_raw else False,
                    "posts": True,
                    "crawler_ig": True,
                    "all_slides": slides
                }
                
                combined_list.append(post_obj)

            return combined_list
            
        except Exception as e:
            print(traceback.format_exc())
            return {"error": f"Gagal gabung data: {str(e)}", "data": []}

    @staticmethod
    def _convert_timestamp_to_iso(timestamp):
        """Convert Unix timestamp to ISO 8601 format (yyyy-MM-dd'T'HH:mm:ss'Z')"""
        try:
            if timestamp > 1000000000000: 
                timestamp = timestamp / 1000
            
            dt = datetime.utcfromtimestamp(timestamp)
            return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        except (ValueError, TypeError, OSError) as e:
            print(f"DEBUG - Error converting timestamp {timestamp}: {e}")
            return None

    @staticmethod
    def _convert_timestamp_to_date(timestamp):
        """Convert Unix timestamp to date only (yyyy-MM-dd)"""
        try:
            if timestamp > 1000000000000:  
                timestamp = timestamp / 1000
            
            dt = datetime.utcfromtimestamp(timestamp)
            return dt.strftime('%Y-%m-%d') 
        except (ValueError, TypeError, OSError) as e:
            print(f"DEBUG - Error converting timestamp {timestamp}: {e}")
            return None
