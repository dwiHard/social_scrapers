import re
from datetime import datetime, timezone

from flask import jsonify

from config import REQUEST_TIMEOUT
from browser.state import LAST_DIAG


def parse_limit(value, default):
    return int(value) if str(value).isdigit() else default


def timeout_response(include_diag=False):
    body = {"status": "timeout",
            "message": f"Scraping melebihi batas waktu ({REQUEST_TIMEOUT} detik) atau browser sibuk",
            "data": [], "total_scraped": 0}
    if include_diag:
        body["diagnostics"] = dict(LAST_DIAG)
    return jsonify(body), 504


def safe_int(value, default=0):
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def safe_str(value, default=''):
    if value is None:
        return default
    return str(value).strip()


def clean_text(text, preserve_newlines=True):
    if not text:
        return ''

    text = re.sub(r'(?i)\b(?:https?://|www\.)\S+', '', text)

    text = re.sub(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U000024C2-\U0001F251]+', '', text)

    if preserve_newlines:
        text = re.sub(r'[^\w\s\.,!?@#\-\n\r]', '', text)
    else:
        text = re.sub(r'[^\w\s\.,!?@#-]', '', text)

    if preserve_newlines:
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            cleaned_line = re.sub(r'\s+', ' ', line).strip()
            if cleaned_line:
                cleaned_lines.append(cleaned_line)
        text = '\n'.join(cleaned_lines)
    else:
        text = re.sub(r'\s+', ' ', text)

    return text.lower().strip()


def clean_text_simple(text):
    if not text:
        return ''
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n', '\n', text)
    return text.strip()


def normalize_username(username):
    if not username:
        return ''
    username = re.sub(r'^@+', '', str(username))
    username = re.sub(r'[^\w\.]', '', username)
    return username.lower().strip()


def normalize_hashtag(hashtag):
    if not hashtag:
        return ''
    hashtag = re.sub(r'^#+', '', str(hashtag))
    hashtag = re.sub(r'[^\w]', '', hashtag)
    return hashtag.lower().strip()


def validate_url(url):
    if not url:
        return ''
    url = safe_str(url)
    if url and not url.startswith(('http://', 'https://')):
        return ''
    return url.strip()


def extract_mentions_regex(text):
    if not text:
        return []
    mentions = re.findall(r'@([a-zA-Z0-9_.]+)', text)
    return list(set([normalize_username(m) for m in mentions if m]))


def extract_hashtags_regex(text):
    if not text:
        return []
    hashtags = re.findall(r'#([a-zA-Z0-9_]+)', text)
    return list(set([normalize_hashtag(h) for h in hashtags if h]))


def extract_challenges(challenges_data):
    if not challenges_data:
        return []
    challenges = []
    for ch in challenges_data:
        title = safe_str(ch.get('title', ''))
        desc = safe_str(ch.get('desc', ''))
        challenges.append({
            'id': safe_str(ch.get('id', '')),
            'title': title,
            'title_clean': normalize_hashtag(title),
            'desc': desc,
            'desc_clean': clean_text(desc),
            'cover': validate_url(ch.get('coverLarger', ''))
        })
    return challenges


def calculate_freshness(create_time_unix):
    if not create_time_unix:
        return None
    now = datetime.now(timezone.utc).timestamp()
    diff_seconds = now - create_time_unix
    return round(diff_seconds / 86400, 2)


def calculate_engagement_rate(stats):
    likes = safe_int(stats.get('diggCount', 0))
    comments = safe_int(stats.get('commentCount', 0))
    shares = safe_int(stats.get('shareCount', 0))
    plays = safe_int(stats.get('playCount', 0))

    if plays == 0:
        return 0.0

    engagement = likes + comments + shares
    return round((engagement / plays) * 100, 2)


def find_mentions(text):
    return extract_mentions_regex(text)
