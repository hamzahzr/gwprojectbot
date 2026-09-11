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
    if isinstance(author, dict):
        return author
    return {}


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
    shown = 0

    for item in items[:50]:
        if not isinstance(item, dict):
            continue

        author = _public_author(item)
        username = _first(item, "username", "unique_id", "uniqueId") or _first(
            author, "username", "unique_id", "uniqueId"
        )
        nickname = _first(item, "nickname", "display_name", "nickname") or _first(
            author, "nickname", "display_name"
        )
        profile_url = _first(item, "profile_url", "author_url", "profileUrl") or _first(
            author, "profile_url", "url", "profileUrl"
        )
        video_url = _first(item, "video_url", "webVideoUrl", "share_url", "shareUrl")
        description = _first(item, "description", "content_desc", "desc", "title", "text")
        create_time = _first(item, "create_time", "createTime", "published_at", "date")
        verified = _first(item, "verified", "is_verified", "verified_account")
        followers = _first(item, "follower_count", "followers", "fans", "fans_count") or _first(
            author, "follower_count", "followers", "fans", "fans_count"
        )
        following = _first(item, "following_count", "following") or _first(
            author, "following_count", "following"
        )
        likes_total = _first(item, "heart_count", "total_likes", "likes") or _first(
            author, "heart_count", "total_likes", "likes"
        )
        videos = _first(item, "video_count", "videos_count") or _first(
            author, "video_count", "videos_count"
        )
        views = _first(item, "play_count", "view_count", "views")
        likes = _first(item, "digg_count", "like_count", "likes_count")
        comments = _first(item, "comment_count", "comments_count")
        shares = _first(item, "share_count", "shares_count")
        saves = _first(item, "collect_count", "save_count", "saves_count")
        duration = _first(item, "duration", "video_duration")
        music = _first(item, "music_name", "music", "sound_name")
        region = _first(item, "region", "region_code", "country")
        hashtags = _first(item, "hashtags", "hash_tags")

        block = []
        if username:
            block.append(f"👤 <b>{html.escape(str(username))}</b>")
        if nickname and str(nickname) != str(username):
            block.append(f"Nama: {html.escape(str(nickname))}")
        if verified is not None:
            block.append(f"✓ Terverifikasi: <b>{'Ya' if bool(verified) else 'Tidak'}</b>")
        if profile_url:
            block.append(f"🔗 Profil: {html.escape(str(profile_url))}")
        if followers is not None:
            block.append(f"👥 Followers: <b>{html.escape(_number(followers))}</b>")
        if following is not None:
            block.append(f"➕ Following: <b>{html.escape(_number(following))}</b>")
        if likes_total is not None:
            block.append(f"❤️ Total likes: <b>{html.escape(_number(likes_total))}</b>")
        if videos is not None:
            block.append(f"🎞️ Total video: <b>{html.escape(_number(videos))}</b>")
        if description:
            block.append(f"📝 <b>Caption:</b> {html.escape(str(description)[:500])}")
        if video_url:
            block.append(f"🎬 Video: {html.escape(str(video_url))}")
        if views is not None:
            block.append(f"▶️ Views: <b>{html.escape(_number(views))}</b>")
        if likes is not None:
            block.append(f"❤️ Likes: <b>{html.escape(_number(likes))}</b>")
        if comments is not None:
            block.append(f"💬 Komentar: <b>{html.escape(_number(comments))}</b>")
        if shares is not None:
            block.append(f"↗️ Shares: <b>{html.escape(_number(shares))}</b>")
        if saves is not None:
            block.append(f"🔖 Saves: <b>{html.escape(_number(saves))}</b>")
        if duration is not None:
            block.append(f"⏱️ Durasi: <b>{html.escape(str(duration))}</b>")
        if music:
            block.append(f"🎵 Musik: {html.escape(str(music)[:250])}")
        if create_time:
            block.append(f"🗓️ Waktu: <b>{html.escape(str(create_time))}</b>")
        if region:
            block.append(f"🌍 Region: <b>{html.escape(str(region))}</b>")
        if hashtags:
            if isinstance(hashtags, list):
                hashtags = " ".join(str(x) for x in hashtags[:30])
            block.append(f"#️⃣ Hashtag: {html.escape(str(hashtags)[:500])}")

        if block:
            lines.extend(block + ["────────────────", ""])
            shown += 1

    if not shown:
        return (
            "🎵 <b>TIKTOK SCRAPER</b>\n\n"
            f"Input: <code>{html.escape(str(value))}</code>\n\n"
            "API merespons, tetapi field publik yang dikenali tidak tersedia."
        )

    lines.append(f"📊 <b>Hasil ditampilkan: {shown}</b>")
    return "\n".join(lines)[:3900]
