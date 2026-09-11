import html
import os
import re

import requests

TIKTOK_API_TOKEN = os.getenv("TIKTOK_API_TOKEN", "").strip()
TIKTOK_API_URL = os.getenv(
    "TIKTOK_API_URL",
    "https://api.apify.com/v2/actors/headlessagent~tiktok-profile-video-scraper/run-sync-get-dataset-items",
).strip()

_VIDEO_URL_RE = re.compile(
    r"https?://(?:www\.)?tiktok\.com/@([^/\s]+)/video/(\d+)/?",
    re.I,
)
_PROFILE_URL_RE = re.compile(
    r"https?://(?:www\.)?tiktok\.com/@([A-Za-z0-9._-]{1,50})/?(?:\?.*)?$",
    re.I,
)


def _video_match(value):
    return _VIDEO_URL_RE.fullmatch(value.strip())


def _profile_match(value):
    return _PROFILE_URL_RE.fullmatch(value.strip())


def _clean_username(value):
    value = value.strip()
    if value.startswith("@"):
        value = value[1:]
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,50}", value):
        raise ValueError("Username TikTok tidak valid")
    return value


def query_tiktok(value):
    value = value.strip()
    if not value:
        raise ValueError("Input TikTok kosong")
    if not TIKTOK_API_TOKEN:
        raise RuntimeError("TIKTOK_API_TOKEN belum dikonfigurasi")

    video_match = _video_match(value)
    profile_match = _profile_match(value)

    if video_match:
        payload = {"usernames": [], "videoUrls": [value]}
    elif profile_match:
        payload = {"usernames": [profile_match.group(1)], "videoUrls": []}
    else:
        payload = {"usernames": [_clean_username(value)], "videoUrls": []}

    response = requests.post(
        TIKTOK_API_URL,
        json=payload,
        headers={
            "Authorization": f"Bearer {TIKTOK_API_TOKEN}",
            "Content-Type": "application/json",
        },
        timeout=300,
    )
    response.raise_for_status()
    return response.json()


def _first(item, *keys):
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return None


def _number(value):
    if value is None or value == "":
        return None
    try:
        return f"{int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(value)


def _public_author(item):
    author = item.get("author")
    return author if isinstance(author, dict) else {}


def _extract_items(result):
    if isinstance(result, list):
        return result
    if not isinstance(result, dict):
        return []
    for key in ("data", "items", "results", "videos", "profiles"):
        value = result.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [value]
    return [result] if result else []


def _line(lines, label, value, limit=700):
    if value is None or value == "":
        return
    if isinstance(value, list):
        value = ", ".join(str(x) for x in value[:50])
    elif isinstance(value, dict):
        value = ", ".join(f"{k}: {v}" for k, v in value.items())
    text = str(value)
    if len(text) > limit:
        text = text[:limit] + "…"
    lines.append(f"{label}: {html.escape(text)}")


def format_tiktok_result(value, result):
    items = _extract_items(result)
    if not items:
        return (
            "🎵 <b>TIKTOK SCRAPER</b>\n\n"
            f"Input: <code>{html.escape(str(value))}</code>\n\n"
            "Tidak ada data publik yang ditemukan."
        )

    lines = [
        "🎵 <b>TIKTOK SCRAPER</b>",
        f"Input: <code>{html.escape(str(value))}</code>",
        f"📦 Item API: <b>{len(items)}</b>",
        "",
    ]

    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        author = _public_author(item)
        lines.append(f"<b>━━ ITEM {index} ━━</b>")

        # Profile / creator fields
        _line(lines, "👤 Username", _first(item, "username", "unique_id", "uniqueId") or _first(author, "username", "unique_id", "uniqueId"))
        _line(lines, "Nama", _first(item, "nickname", "display_name") or _first(author, "nickname", "display_name"))
        _line(lines, "Bio", _first(item, "signature", "bio", "description") or _first(author, "signature", "bio"))
        _line(lines, "Profil", _first(item, "profile_url", "author_url", "profileUrl") or _first(author, "profile_url", "url", "profileUrl"))
        _line(lines, "Avatar", _first(item, "avatar", "avatar_url", "avatarLarger", "cover") or _first(author, "avatar", "avatar_url", "avatarLarger"))
        _line(lines, "Verified", _first(item, "verified", "is_verified", "verified_account") or _first(author, "verified", "is_verified"))
        _line(lines, "Followers", _number(_first(item, "follower_count", "followers", "fans", "fans_count") or _first(author, "follower_count", "followers", "fans", "fans_count")))
        _line(lines, "Following", _number(_first(item, "following_count", "following") or _first(author, "following_count", "following")))
        _line(lines, "Total Likes", _number(_first(item, "heart_count", "total_likes", "likes") or _first(author, "heart_count", "total_likes", "likes")))
        _line(lines, "Total Video", _number(_first(item, "video_count", "videos_count") or _first(author, "video_count", "videos_count")))
        _line(lines, "Region", _first(item, "region", "region_code", "country") or _first(author, "region", "region_code", "country"))
        _line(lines, "Sec UID", _first(item, "secUid", "sec_uid") or _first(author, "secUid", "sec_uid"))

        # Video fields
        _line(lines, "Video ID", _first(item, "id", "video_id", "videoId"))
        _line(lines, "Video URL", _first(item, "video_url", "webVideoUrl", "share_url", "shareUrl"))
        _line(lines, "Caption", _first(item, "description", "content_desc", "desc", "title", "text"))
        _line(lines, "Views", _number(_first(item, "play_count", "view_count", "views")))
        _line(lines, "Likes", _number(_first(item, "digg_count", "like_count", "likes_count")))
        _line(lines, "Komentar", _number(_first(item, "comment_count", "comments_count")))
        _line(lines, "Shares", _number(_first(item, "share_count", "shares_count")))
        _line(lines, "Saves", _number(_first(item, "collect_count", "save_count", "saves_count")))
        _line(lines, "Durasi", _first(item, "duration", "video_duration"))
        _line(lines, "Waktu", _first(item, "create_time", "createTime", "published_at", "date"))
        _line(lines, "Musik", _first(item, "music_name", "music", "sound_name"))
        _line(lines, "Musik Author", _first(item, "music_author", "music_author_name"))
        _line(lines, "Music ID", _first(item, "music_id", "musicId"))
        _line(lines, "Thumbnail", _first(item, "cover", "cover_url", "thumbnail", "thumbnail_url"))
        _line(lines, "Download URL", _first(item, "download_url", "downloadUrl"))
        _line(lines, "Play URL", _first(item, "play_url", "playUrl"))
        _line(lines, "Hashtag", _first(item, "hashtags", "hash_tags"))
        _line(lines, "Mentions", _first(item, "mentions", "mention_list"))
        _line(lines, "Location", _first(item, "location", "location_name"))
        _line(lines, "Language", _first(item, "language", "lang"))
        _line(lines, "Status", _first(item, "status", "item_status"))

        # Other public fields commonly returned by scrapers.
        for key in (
            "category", "region_code", "country_code", "share_count", "comment_count",
            "collect_count", "download_count", "forward_count", "repost_count",
            "is_ad", "is_commerce", "is_original", "is_top", "is_private",
            "item_type", "aweme_id", "createTime", "timestamp", "updated_at",
        ):
            if key in item:
                _line(lines, key, item.get(key), limit=500)

        lines.append("────────────────────────")
        lines.append("")

    return "\n".join(lines)
