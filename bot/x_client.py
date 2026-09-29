"""Minimal X (Twitter) API v2 client: posts with OAuth 1.0a user context.

Uses only `requests` + the standard library (no tweepy needed).
Needs in .env: X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
(from the X developer console; the app needs Read and Write permission).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Mapping
from urllib.parse import quote

import requests

from .config import secret

POST_URL = "https://api.x.com/2/tweets"


def _pct(value: str) -> str:
    return quote(str(value), safe="~-._")


def oauth1_header(method: str, url: str, params: Mapping[str, str], consumer_key: str,
                  consumer_secret: str, token: str, token_secret: str,
                  nonce: str | None = None, timestamp: str | None = None) -> str:
    """Build an OAuth 1.0a Authorization header (HMAC-SHA1)."""
    oauth = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp or str(int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    all_params = {**params, **oauth}
    param_str = "&".join(f"{k}={v}" for k, v in sorted((_pct(k), _pct(v)) for k, v in all_params.items()))
    base = "&".join([method.upper(), _pct(url), _pct(param_str)])
    key = f"{_pct(consumer_secret)}&{_pct(token_secret)}"
    sig = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    oauth["oauth_signature"] = sig
    return "OAuth " + ", ".join(f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(oauth.items()))


class XClient:
    def __init__(self) -> None:
        self.keys = {
            "consumer_key": secret("X_API_KEY"),
            "consumer_secret": secret("X_API_SECRET"),
            "token": secret("X_ACCESS_TOKEN"),
            "token_secret": secret("X_ACCESS_TOKEN_SECRET"),
        }
        missing = [k for k, v in self.keys.items() if not v]
        if missing:
            raise RuntimeError("X API keys missing from .env: X_API_KEY, X_API_SECRET, "
                               "X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET")

    def post(self, text: str) -> str:
        """Publish a post and return its id. JSON bodies are not part of the OAuth signature."""
        auth = oauth1_header("POST", POST_URL, {}, **self.keys)  # type: ignore[arg-type]
        resp = requests.post(POST_URL, json={"text": text},
                             headers={"Authorization": auth}, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"X API {resp.status_code}: {resp.text[:300]}")
        return str(resp.json()["data"]["id"])
