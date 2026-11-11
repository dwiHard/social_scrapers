"""Salinan parser TikTok lama (referensi regresi). Jangan diubah: dipakai test_parity untuk membuktikan mapping setara."""
import re
from datetime import datetime, timezone
from cdp_scraper.utils import (
    safe_int, safe_str, normalize_username, normalize_hashtag,
    validate_url, calculate_engagement_rate
)


def parse_tiktok_api_search(api_data: dict) -> list:
    parsed_results = []
    if not api_data or not isinstance(api_data, dict):
        return []

    for item in api_data.get('data', []):
        if item.get('type') == 1:
            video_data = item.get('item', {})
            if not video_data:
                continue

            # Extract nested data
            author_info = video_data.get('author', {})
            stats = video_data.get('stats', {})
            location = video_data.get('poi')
            author_stats = video_data.get('authorStats', {})
            music_info = video_data.get('music', {})
            video_info = video_data.get('video', {})
            
            # Basic info
            video_id = video_data.get('id', '')
            author_unique_id = author_info.get('uniqueId', '')
            video_url = f"https://www.tiktok.com/@{author_unique_id}/video/{video_id}"
            description = video_data.get('desc', '')
            
            # Timestamp & Date ID processing
            timestamp = video_data.get('createTime')
            formatted_date = ''
            date_id = None
            if timestamp:
                dt_object = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                formatted_date = dt_object.isoformat().replace('+00:00', 'Z')
                date_id = dt_object.strftime('%Y-%m-%d')            
            
            # Engagement rate
            engagement_rate = calculate_engagement_rate(stats)
            
            # Statistics
            likes = safe_int(stats.get('diggCount', 0))
            comments_count = safe_int(stats.get('commentCount', 0))
            shares = safe_int(stats.get('shareCount', 0))
            views = safe_int(stats.get('playCount', 0))
            bookmarks = safe_int(stats.get('collectCount', 0))

            # Extract hashtags and mentions from textExtra with normalization
            hashtags = []
            hashtags_normalized = []
            mention_usernames = []
            mention_usernames_normalized = []
            mention_user_ids = []
            
            for extra in video_data.get('textExtra', []):
                if extra.get('type') == 1 and extra.get('hashtagName'):
                    raw_hashtag = extra.get('hashtagName')
                    hashtags.append(raw_hashtag)
                    hashtags_normalized.append(normalize_hashtag(raw_hashtag))
                elif extra.get('type') == 0 and extra.get('userUniqueId'):
                    raw_username = extra.get('userUniqueId')
                    mention_usernames.append(raw_username)
                    mention_usernames_normalized.append(normalize_username(raw_username))
                    mention_user_ids.append(safe_str(extra.get('userId')))
            
            parsed_item = {
                # === Video Identity ===
                'id': safe_str(video_id),
                'url': validate_url(video_url),
                
                # === Statistics ===
                'video_like_count': likes,
                'video_comment_count': comments_count,
                'video_share_count': shares,
                'video_play_count': views,
                'video_bookmark_count': bookmarks,
                'engagement_rate': engagement_rate,
                
                # === Content ===
                'user_post_desc': safe_str(description),
                'video_hashtags': hashtags,
                'video_mentions_screen_name': mention_usernames,
                'video_mentions_username_id': mention_usernames,
                'video_mentions_user_id': mention_user_ids,
                
                # === Timestamps & Partition Keys ===
                'dateid': date_id,
                'p_created_at': formatted_date,
                
                # === Video Metadata ===
                'video_duration': safe_int(video_info.get('duration', 0)),
                'video_ratio': safe_str(video_info.get('ratio', '')),
                'video_cover': validate_url(video_info.get('cover', '')),
                'video_play_addr': validate_url(video_info.get('playAddr', '')),
                
                # === Author Info ===
                'author_id': safe_str(author_info.get('id', '')),
                'author_username_id': safe_str(author_unique_id),
                'author_nickname_id': safe_str(author_info.get('nickname', '')),
                'author_avatar': validate_url(author_info.get('avatarThumb', '')),
                'is_verified': bool(author_info.get('verified', False)),
                
                # === Author Statistics ===
                'author_following_count': safe_int(author_stats.get('followingCount', 0)),
                'author_follower_count': safe_int(author_stats.get('followerCount', 0)),
                'author_like_count': safe_int(author_stats.get('heartCount', 0)),
                'author_video_count': safe_int(author_stats.get('videoCount', 0)),
                
                # === Music Info ===
                'music_id': safe_str(music_info.get('id', '')),
                'music_title': safe_str(music_info.get('title', '')),
                'music_author_name': safe_str(music_info.get('authorName', '')),
                'music_album': safe_str(music_info.get('album', '')),
                'music_cover': validate_url(music_info.get('coverThumb', '')),
                'music_duration': safe_int(music_info.get('duration', 0)),
                'music_is_original': bool(music_info.get('original', False)),
                'music_play_url': validate_url(music_info.get('playUrl', '')),
                
                # === Location Info ===
                'location_name': safe_str(location.get('name', '') if location else ''),
                'location_address': safe_str(location.get('address', '') if location else ''),
                'location_city': safe_str(location.get('city', '') if location else ''),
                'location_category': safe_str(location.get('category', '') if location else ''),
                
                'posts': True
            }
            
            parsed_results.append(parsed_item)
            
    return parsed_results


def parse_tiktok_api_user_videos(api_data: dict) -> list:
    parsed_results = []
    if not api_data or not isinstance(api_data, dict):
        return []
    
    item_list = api_data.get('itemList', [])
    if not item_list:
        return []
    
    for video_data in item_list:
        if not video_data:
            continue
        
        # Extract nested data
        author_info = video_data.get('author', {})
        stats = video_data.get('stats', {})
        location = video_data.get('poi')
        author_stats = video_data.get('authorStats', {})
        music_info = video_data.get('music', {})
        video_info = video_data.get('video', {})
        
        # Basic info
        video_id = video_data.get('id', '')
        author_unique_id = author_info.get('uniqueId', '')
        video_url = f"https://www.tiktok.com/@{author_unique_id}/video/{video_id}"
        description = video_data.get('desc', '')
        
        # Timestamp & Date ID processing
        timestamp = video_data.get('createTime')
        formatted_date = ''
        date_id = None
        if timestamp:
            dt_object = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            formatted_date = dt_object.isoformat().replace('+00:00', 'Z')
            date_id = dt_object.strftime('%Y-%m-%d')        

        # Engagement rate
        engagement_rate = calculate_engagement_rate(stats)
        
        # Statistics
        likes = safe_int(stats.get('diggCount', 0))
        comments_count = safe_int(stats.get('commentCount', 0))
        shares = safe_int(stats.get('shareCount', 0))
        views = safe_int(stats.get('playCount', 0))
        bookmarks = safe_int(stats.get('collectCount', 0))

        # Extract hashtags and mentions from textExtra
        hashtags = []
        hashtags_normalized = []
        mention_usernames = []
        mention_usernames_normalized = []
        mention_user_ids = []
        
        for extra in video_data.get('textExtra', []):
            if extra.get('type') == 1 and extra.get('hashtagName'):
                raw_hashtag = extra.get('hashtagName')
                hashtags.append(raw_hashtag)
                hashtags_normalized.append(normalize_hashtag(raw_hashtag))
            elif extra.get('type') == 0 and extra.get('userUniqueId'):
                raw_username = extra.get('userUniqueId')
                mention_usernames.append(raw_username)
                mention_usernames_normalized.append(normalize_username(raw_username))
                mention_user_ids.append(safe_str(extra.get('userId')))
        
        parsed_item = {
            # === Video Identity ===
            'id': safe_str(video_id),
            'url': validate_url(video_url),
            
            # === Statistics ===
            'video_like_count': likes,
            'video_comment_count': comments_count,
            'video_share_count': shares,
            'video_play_count': views,
            'video_bookmark_count': bookmarks,
            
            # === Content ===
            'user_post_desc': safe_str(description),
            'video_hashtags': hashtags,
            'video_mentions_screen_name': mention_usernames,
            'video_mentions_username_id': mention_usernames,
            'video_mentions_user_id': mention_user_ids,
            'engagement_rate': engagement_rate,
            
            # === Timestamps & Partition Keys ===
            'dateid': date_id,
            'p_created_at': formatted_date,
            
            # === Video Metadata ===
            'video_duration': safe_int(video_info.get('duration', 0)),
            'video_ratio': safe_str(video_info.get('ratio', '')),
            'video_cover': validate_url(video_info.get('cover', '')),
            
            # === Author Info ===
            'author_id': safe_str(author_info.get('id', '')),
            'author_username_id': safe_str(author_unique_id),
            'author_nickname_id': safe_str(author_info.get('nickname', '')),
            'author_avatar': validate_url(author_info.get('avatarThumb', '')),
            'is_verified': bool(author_info.get('verified', False)),
            
            # === Author Statistics ===
            'author_following_count': safe_int(author_stats.get('followingCount', 0)),
            'author_follower_count': safe_int(author_stats.get('followerCount', 0)),
            'author_like_count': safe_int(author_stats.get('heartCount', 0)),
            'author_video_count': safe_int(author_stats.get('videoCount', 0)),
            
            # === Music Info ===
            'music_id': safe_str(music_info.get('id', '')),
            'music_title': safe_str(music_info.get('title', '')),
            'music_author_name': safe_str(music_info.get('authorName', '')),
            'music_album': safe_str(music_info.get('album', '')),
            'music_cover': validate_url(music_info.get('coverThumb', '')),
            'music_duration': safe_int(music_info.get('duration', 0)),
            'music_play_url': validate_url(music_info.get('playUrl', '')),
            
            # === Location Info ===
            'location_name': safe_str(location.get('name', '') if location else ''),
            'location_address': safe_str(location.get('address', '') if location else ''),
            'location_city': safe_str(location.get('city', '') if location else ''),
            'location_category': safe_str(location.get('category', '') if location else ''),
            
            'posts': True
        }
        
        parsed_results.append(parsed_item)
    
    return parsed_results


def parse_comment_data(comment_dict: dict) -> dict:
    user_info = comment_dict.get('user', {})
    
    timestamp_seconds = comment_dict.get('create_time')
    formatted_date = None
    date_id = None
    if timestamp_seconds:
        dt_object = datetime.fromtimestamp(timestamp_seconds, tz=timezone.utc)
        formatted_date = dt_object.isoformat().replace('+00:00', 'Z')
        date_id = dt_object.strftime('%Y-%m-%d')    

    full_text = comment_dict.get('text', '')
    
    # Extract avatar URL
    avatar_url = None
    avatar_thumb = user_info.get('avatar_thumb', {})
    if avatar_thumb and avatar_thumb.get('url_list'):
        avatar_url = avatar_thumb.get('url_list')[0]
    
    aweme_id = comment_dict.get('aweme_id')
    cid = comment_dict.get('cid')
    
    # Language & extra info
    comment_language = comment_dict.get('comment_language')
    reply_to_reply_id = comment_dict.get('reply_to_reply_id')
    reply_comment_id = comment_dict.get('reply_id')
    
    return {
        # === Comment Identity ===
        'id': cid,
        'post_id': aweme_id,
        
        # === User Information ===
        'comment_username': user_info.get('unique_id'),
        'comment_nickname': user_info.get('nickname'),
        'comment_user_id': user_info.get('uid'),
        'comment_avatar': avatar_url,
        
        # === Comment Content ===
        'text': full_text,
        'comment_language': comment_language,
        
        # === Engagement Metrics ===
        'reply_comment_total': comment_dict.get('reply_comment_total', 0),
        'comment_like_count': comment_dict.get('digg_count', 0),
        'comment_total': comment_dict.get('reply_comment_total', 0),
        
        # === Timestamps & Partition Keys ===
        'dateid': date_id,
        'c_created_at': formatted_date,
        
        # === Comment Hierarchy ===
        'is_reply': 1 if reply_to_reply_id else 0,
        'reply_to_reply_id': reply_to_reply_id,
        'reply_comment_id': reply_comment_id,
        'posts': False,
        
    }
