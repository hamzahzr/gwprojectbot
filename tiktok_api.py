import os
import re

import requests

TIKTOK_API_TOKEN = os.getenv("TIKTOK_API_TOKEN", "").strip()
TIKTOK_API_URL = os.getenv(
    "TIKTOK_API_URL",
    "https://api.apify.com/v2/actors/headlessagent~tiktok-profile-video-scraper/run-sync-get-dataset-items",
).strip()


def _is_video_url(value):
    return bool(re.fullmatch(r"https?://(www\.)?tiktok\.com/@[^/\s]+/video/\d+/?", value.strip(), re.I))


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

    if _is_video_url(value):
        payload = {"usernames": [], "videoUrls": [value]}
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


def format_tiktok_result(value, result):
    items = result if isinstance(result, list) else result.get("data", result.get("items", [])) if isinstance(result, dict) else []
    if isinstance(items, dict):
        items = [items]
    if not items:
        return f"🎵 <b>TIKTOK SCRAPER</b>\n\nInput: <code>{value}</code>\n\nTidak ada data publik yang ditemukan."

    lines = ["🎵 <b>TIKTOK SCRAPER</b>", f"\nInput: <code>{value}</code>", ""]
    shown = 0
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        username = item.get("username") or item.get("unique_id") or item.get("author")
        nickname = item.get("nickname") or item.get("display_name")
        profile_url = item.get("profile_url") or item.get("author_url")
        video_url = item.get("video_url") or item.get("play_url") or item.get("webVideoUrl")
        description = item.get("description") or item.get("content_desc") or item.get("title")
        views = item.get("play_count") or item.get("view_count")
        likes = item.get("digg_count") or item.get("like_count")

        block = []
        if username:
            block.append(f"👤 <b>{username}</b>")
        if nickname and nickname != username:
            block.append(f"Nama: {nickname}")
        if profile_url:
            block.append(f"Profil: {profile_url}")
        if description:
            block.append(f"📝 {str(description)[:300]}")
        if views is not None:
            block.append(f"▶️ Views: {views}")
        if likes is not None:
            block.append(f"❤️ Likes: {likes}")
        if video_url:
            block.append(f"🎬 Video: {video_url}")
        if block:
            lines.extend(block + [""])
            shown += 1

    if not shown:
        return f"🎵 <b>TIKTOK SCRAPER</b>\n\nInput: <code>{value}</code>\n\nAPI merespons, tetapi tidak ada field publik yang dikenali."
    lines.append(f"📊 Hasil ditampilkan: <b>{shown}</b>")
    return "\n".join(lines)[:3900]
