import os
import re
import requests

SHERLOCK_API_TOKEN = os.getenv("SHERLOCK_API_TOKEN", "").strip()
SHERLOCK_API_URL = os.getenv(
    "SHERLOCK_API_URL",
    "https://api.apify.com/v2/actors/Futurizerush~sherlock/run-sync-get-dataset-items",
).strip()


def query_username_api(username):
    username = username.strip().lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,50}", username):
        raise ValueError("Username tidak valid")
    if not SHERLOCK_API_TOKEN:
        raise RuntimeError("SHERLOCK_API_TOKEN belum dikonfigurasi")

    headers = {
        "Authorization": f"Bearer {SHERLOCK_API_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "usernames": [username],
        "siteList": [],
        "onlyFound": True,
        "includeNsfw": False,
        "timeout": 60,
    }
    response = requests.post(
        SHERLOCK_API_URL,
        json=payload,
        headers=headers,
        timeout=300,
    )
    response.raise_for_status()
    return response.json()
