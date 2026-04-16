"""
Signal Collector — fetches signals from external sources.

Supported source types:
- twitter: Twitter/X v2 API search
- exa: Exa web search
- firecrawl: Scrape a specific URL
"""

import json
import os
import time
import uuid
import logging
import urllib.request
import urllib.parse
import urllib.error
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


# ── Twitter ────────────────────────────────────────────────────────────

TWITTER_BASE = "https://api.x.com/2"
TWITTER_BLACKLIST = [
    "giveaway", "airdrop", "whitelist", "free mint", "join our",
    "follow and rt", "follow & retweet", "dm me", "dm for",
    "100x", "moonshot",
]


def fetch_twitter(config: Dict[str, Any], filter_text: str = "") -> List[Dict[str, Any]]:
    """Fetch tweets via Twitter v2 API. Config: {query: str, max_results: int (default 20)}."""
    bearer = os.environ.get("TWITTER_BEARER_TOKEN") or os.environ.get("X_BEARER_TOKEN")
    if not bearer:
        logger.warning("No Twitter bearer token configured")
        return []

    query = config.get("query", "").strip()
    if not query:
        return []

    # Normalize: convert comma-separated terms to OR expressions
    # "AI agents, evolutionary coding" → "(AI agents) OR (evolutionary coding)"
    if "," in query and " OR " not in query.upper() and " AND " not in query.upper():
        terms = [t.strip() for t in query.split(",") if t.strip()]
        if len(terms) > 1:
            query = " OR ".join(f"({t})" for t in terms)

    # Add common quality filters
    if "-is:retweet" not in query:
        query = f"{query} -is:retweet lang:en"

    params = {
        "query": query,
        "max_results": str(min(config.get("max_results", 20), 100)),
        "tweet.fields": "created_at,public_metrics,author_id",
        "user.fields": "username,public_metrics,verified",
        "expansions": "author_id",
    }
    url = f"{TWITTER_BASE}/tweets/search/recent?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {bearer}"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        logger.error("Twitter fetch failed: %s %s", e.code, e.read()[:200])
        return []
    except Exception as e:
        logger.error("Twitter fetch error: %s", e)
        return []

    tweets = data.get("data", [])
    users_map = {u["id"]: u for u in data.get("includes", {}).get("users", [])}

    signals = []
    for tweet in tweets:
        text = tweet.get("text", "")
        text_lower = text.lower()

        # Skip obvious noise
        if any(word in text_lower for word in TWITTER_BLACKLIST):
            continue

        author_id = tweet.get("author_id", "")
        user = users_map.get(author_id, {})
        user_metrics = user.get("public_metrics", {})
        followers = user_metrics.get("followers_count", 0)
        if followers < 50:  # very low signal
            continue

        metrics = tweet.get("public_metrics", {})
        reach = metrics.get("like_count", 0) + metrics.get("retweet_count", 0)

        signals.append({
            "title": text[:120],
            "body": text,
            "url": f"https://x.com/i/status/{tweet['id']}",
            "author": user.get("username", ""),
            "metadata": {
                "followers": followers,
                "likes": metrics.get("like_count", 0),
                "retweets": metrics.get("retweet_count", 0),
                "reach": reach,
                "verified": user.get("verified", False),
            },
            "external_created_at": _parse_twitter_time(tweet.get("created_at", "")),
        })

    return signals


def _parse_twitter_time(s: str) -> float:
    try:
        from datetime import datetime
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return time.time()


# ── Exa ────────────────────────────────────────────────────────────────

def fetch_exa(config: Dict[str, Any], filter_text: str = "") -> List[Dict[str, Any]]:
    """Fetch web results via Exa. Config: {query: str, num_results: int}."""
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        logger.warning("No Exa API key configured")
        return []

    query = config.get("query", "").strip()
    if not query:
        return []

    try:
        payload = json.dumps({
            "query": query,
            "numResults": min(config.get("num_results", 10), 25),
            "useAutoprompt": True,
            "type": "auto",
            "contents": {"text": {"maxCharacters": 1500, "includeHtmlTags": False}},
        }).encode()
        req = urllib.request.Request(
            "https://api.exa.ai/search",
            data=payload,
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.error("Exa fetch failed: %s", e)
        return []

    signals = []
    for r in data.get("results", []):
        signals.append({
            "title": r.get("title", "Untitled"),
            "body": r.get("text", "") or r.get("summary", ""),
            "url": r.get("url", ""),
            "author": r.get("author", "") or _domain(r.get("url", "")),
            "metadata": {
                "score": r.get("score", 0),
                "published_date": r.get("publishedDate", ""),
            },
            "external_created_at": _parse_iso(r.get("publishedDate", "")),
        })
    return signals


def _domain(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc
    except Exception:
        return ""


def _parse_iso(s: str) -> float:
    try:
        from datetime import datetime
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return time.time()


# ── Firecrawl ──────────────────────────────────────────────────────────

def fetch_firecrawl(config: Dict[str, Any], filter_text: str = "") -> List[Dict[str, Any]]:
    """Scrape a URL via Firecrawl. Config: {url: str}."""
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        logger.warning("No Firecrawl API key configured")
        return []

    url = config.get("url", "").strip()
    if not url:
        return []

    try:
        payload = json.dumps({"url": url, "formats": ["markdown"]}).encode()
        req = urllib.request.Request(
            "https://api.firecrawl.dev/v1/scrape",
            data=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.error("Firecrawl fetch failed: %s", e)
        return []

    d = data.get("data", {})
    content = d.get("markdown", "") or d.get("content", "")
    metadata = d.get("metadata", {})

    if not content:
        return []

    return [{
        "title": metadata.get("title", url),
        "body": content[:3000],
        "url": url,
        "author": _domain(url),
        "metadata": {
            "description": metadata.get("description", ""),
            "full_length": len(content),
        },
        "external_created_at": time.time(),
    }]


# ── Dispatch ───────────────────────────────────────────────────────────

FETCHERS = {
    "twitter": fetch_twitter,
    "exa": fetch_exa,
    "firecrawl": fetch_firecrawl,
}


def fetch_source(source_type: str, config: Dict[str, Any], filter_text: str = "") -> List[Dict[str, Any]]:
    fetcher = FETCHERS.get(source_type)
    if not fetcher:
        logger.warning("Unknown source type: %s", source_type)
        return []
    return fetcher(config, filter_text)
