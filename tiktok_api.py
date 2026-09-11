import html
import os
import re

import requests

TIKTOK_API_TOKEN = os.getenv("TIKTOK_API_TOKEN", "").strip()
TIKTOK_API_URL = os.getenv(
    "TIKTOK_API_URL",
    "https://api.apify.com/v2/actors/headlessagent~tiktok-profile-video-scraper/run-sync-get-dataset-items",
).strip()

_VIDEO_URL_RE = re.compile(r"https?://(?:www\.)?tiktok\.com/@([^/\s]+)/video/(\d+)/?", re.I)
_PROFILE_URL_RE = re.compile(r"https?://(?:www\.)?tiktok\.com/@([A-Za-z0-9._-]{1,50})/?(?:\?.*)?$", re.I)


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


def _nested(item, container, *keys):
    value = item.get(container)
    if not isinstance(value, dict):
        return None
    return _first(value, *keys)


def _number(value):
    if value is None or value == "":
        return None
    try:
        return f"{int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(value)


def _bool_label(value, yes="Yes", no="No"):
    if value is None or value == "":
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return yes
        if normalized in {"false", "0", "no", "n", "off"}:
            return no
    return yes if bool(value) else no


def _privacy_label(value, everyone="Everyone 🌎", restricted="Restricted/Friends 🚫"):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return everyone if value else restricted
    text = str(value).strip().lower()
    if text in {"everyone", "public", "1", "true", "yes", "all"}:
        return everyone
    if text in {"friends", "friend", "restricted", "private", "0", "false", "no"}:
        return restricted
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


def _stringify(value):
    if isinstance(value, list):
        return ", ".join(_stringify(x) for x in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}: {_stringify(v)}" for k, v in value.items())
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _add(lines, label, value, empty="None"):
    if value is None or value == "":
        value = empty
    lines.append(f"{label:<18} {html.unescape(_stringify(value))}")


def _section(lines, title):
    lines.append(f"--- [ {title} ] ---")


def _profile_fields(item, author):
    def pick(*keys):
        return _first(item, *keys) or _first(author, *keys)
    return pick


def format_tiktok_result(value, result):
    """Create a detailed plain-text report of public TikTok profile/video fields."""
    items = _extract_items(result)
    if not items:
        return (
            "================ TIKTOK SCRAPER ================\n"
            f"Input: {value}\n\n"
            "Tidak ada data publik yang ditemukan."
        )

    lines = [
        "==============================================================",
        "                    TIKTOK SCRAPER",
        "==============================================================",
        f"Input: {value}",
        f"Total item API: {len(items)}",
        "",
    ]

    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue

        author = _public_author(item)
        pick = _profile_fields(item, author)

        if len(items) > 1:
            _section(lines, f"ITEM {index}")

        _section(lines, "BASIC IDENTITY")
        _add(lines, "Username:", pick("username", "unique_id", "uniqueId"))
        _add(lines, "Nickname:", pick("nickname", "display_name"))
        _add(lines, "Account ID:", pick("uid", "user_id", "userId", "account_id", "id") if not _first(item, "id", "video_id", "videoId", "aweme_id") else pick("uid", "user_id", "userId", "account_id"))
        _add(lines, "Secret UID:", pick("secUid", "sec_uid"))
        _add(lines, "Region/Country:", pick("region", "region_code", "country", "country_code"))
        _add(lines, "Language:", pick("language", "lang"))
        _add(lines, "Verified:", _bool_label(pick("verified", "is_verified", "verified_account"), yes="Yes ✅", no="No ❌"))
        lines.append("")

        _section(lines, "BIOGRAPHY & LINKS")
        _add(lines, "Signature:", pick("signature", "bio", "description"))
        _add(lines, "Bio Link:", pick("bio_link", "bioLink", "bio_url", "link", "website", "website_url"))
        _add(lines, "Avatar (HD):", pick("avatarLarger", "avatar_hd", "avatar_hd_url", "avatar_url", "avatar"))
        _add(lines, "Profile URL:", pick("profile_url", "profileUrl", "author_url", "url"))
        lines.append("")

        _section(lines, "TIMESTAMPS")
        _add(lines, "Creation Time:", pick("create_time", "createTime", "created_at", "creation_time", "account_created_at"))
        _add(lines, "Nick-Modified:", pick("nick_name_modified", "nickname_modified", "nickname_modified_at", "nick_modified_at"), empty="Not Set/None")
        _add(lines, "Updated At:", pick("updated_at", "updatedAt"))
        lines.append("")

        _section(lines, "CORE STATS")
        _add(lines, "Followers:", _number(pick("follower_count", "followers", "fans", "fans_count")))
        _add(lines, "Following:", _number(pick("following_count", "following")))
        _add(lines, "Friend Count:", _number(pick("friend_count", "friends", "friends_count")))
        _add(lines, "Total Likes:", _number(pick("heart_count", "total_likes", "likes")))
        _add(lines, "Video Count:", _number(pick("video_count", "videos_count")))
        _add(lines, "Digg Count:", _number(pick("digg_count", "liked_videos_count", "digg_count_total")))
        lines.append("")

        _section(lines, "PRIVACY SETTINGS")
        _add(lines, "Private Account:", _bool_label(pick("is_private", "private"), yes="Yes 🔒", no="No 🔓"))
        _add(lines, "Download:", _privacy_label(pick("download_permission", "download_setting", "allow_download", "download")))
        _add(lines, "Duet:", _privacy_label(pick("duet_permission", "duet_setting", "allow_duet", "duet")))
        _add(lines, "Stitch:", _privacy_label(pick("stitch_permission", "stitch_setting", "allow_stitch", "stitch")))
        _add(lines, "Comment:", _privacy_label(pick("comment_permission", "comment_setting", "allow_comment", "comment")))
        lines.append("")

        _section(lines, "ADVANCED DISCOVERY")
        _add(lines, "Suggest Account:", _bool_label(pick("suggest_account", "suggest_account_for_others", "can_be_suggested"), yes="Yes ❌", no="No ❌"))
        _add(lines, "Show Music Tab:", _bool_label(pick("show_music_tab", "music_tab_visible", "has_music_tab"), yes="Yes ❌", no="No ❌"))
        _add(lines, "Show Playlist:", _bool_label(pick("show_playlist", "playlist_visible", "has_playlist"), yes="Yes ❌", no="No ❌"))
        _add(lines, "Commerce User:", _bool_label(pick("commerce_user", "is_commerce", "commerce_user_info"), yes="Yes 👤", no="No 👤"))
        _add(lines, "Profile Locked:", _bool_label(pick("profile_locked", "is_profile_locked", "profile_lock"), yes="Yes 🔒", no="No ❌"))
        lines.append("")

        _section(lines, "VIDEO / CONTENT")
        _add(lines, "Video ID:", _first(item, "id", "video_id", "videoId", "aweme_id"))
        _add(lines, "Video URL:", _first(item, "video_url", "webVideoUrl", "share_url", "shareUrl"))
        _add(lines, "Caption:", _first(item, "description", "content_desc", "desc", "title", "text"))
        _add(lines, "Views:", _number(_first(item, "play_count", "view_count", "views") or _nested(item, "stats", "playCount", "play_count", "views")))
        _add(lines, "Likes:", _number(_first(item, "digg_count", "like_count", "likes_count") or _nested(item, "stats", "diggCount", "digg_count", "likes")))
        _add(lines, "Komentar:", _number(_first(item, "comment_count", "comments_count") or _nested(item, "stats", "commentCount", "comment_count", "comments")))
        _add(lines, "Shares:", _number(_first(item, "share_count", "shares_count") or _nested(item, "stats", "shareCount", "share_count", "shares")))
        _add(lines, "Saves:", _number(_first(item, "collect_count", "save_count", "saves_count") or _nested(item, "stats", "collectCount", "collect_count", "saves")))
        _add(lines, "Download Count:", _number(_first(item, "download_count", "downloads")))
        _add(lines, "Duration:", _first(item, "duration", "video_duration") or _nested(item, "video", "duration", "duration_ms"))
        _add(lines, "Published:", _first(item, "published_at", "date", "timestamp", "create_time", "createTime"))
        _add(lines, "Thumbnail:", _first(item, "cover", "cover_url", "thumbnail", "thumbnail_url"))
        _add(lines, "Play URL:", _first(item, "play_url", "playUrl"))
        _add(lines, "Item Type:", _first(item, "item_type", "type"))
        lines.append("")

        _section(lines, "MUSIC")
        _add(lines, "Music:", _first(item, "music_name", "sound_name") or _nested(item, "music", "title", "music_name", "name"))
        _add(lines, "Music Author:", _first(item, "music_author", "music_author_name") or _nested(item, "music", "author", "music_author", "authorName"))
        _add(lines, "Music ID:", _first(item, "music_id", "musicId") or _nested(item, "music", "id", "music_id", "musicId"))
        lines.append("")

        _section(lines, "PUBLIC METADATA")
        for key in (
            "hashtags", "hash_tags", "hashtag_list", "mentions", "mention_list",
            "location", "location_name", "category", "region_code", "country_code",
            "forward_count", "repost_count", "is_ad", "is_commerce", "is_original", "is_top",
        ):
            if key in item:
                _add(lines, f"{key}:", item.get(key))

        lines.append("==============================================================")
        lines.append("")

    return "\n".join(lines).rstrip()
