# pipeline/stage_extract.py
"""Stage 2: Recursive content extraction. Pure I/O — no LLM calls."""
import json
import os
import re
import requests
from config import X_BEARER_TOKEN

MAX_DEPTH = 2
GITHUB_REPO_PATTERN = re.compile(r"github\.com/([^/]+)/([^/\s?#]+)")
X_STATUS_PATTERN = re.compile(r"x\.com/\w+/status/(\d+)")
JINA_PREFIX = "https://r.jina.ai/"

# Firecrawl setup — preferred over Jina when available
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
_firecrawl_app = None

def _get_firecrawl():
    """Lazy init Firecrawl client."""
    global _firecrawl_app
    if _firecrawl_app is None and FIRECRAWL_API_KEY:
        try:
            from firecrawl import FirecrawlApp
            _firecrawl_app = FirecrawlApp(api_key=FIRECRAWL_API_KEY)
        except ImportError:
            pass
    return _firecrawl_app


def _resolve_tco(url: str) -> str:
    """Resolve t.co shortened URL to real destination."""
    try:
        resp = requests.head(url, allow_redirects=True, timeout=5)
        return resp.url
    except Exception:
        return url


def _fetch_github_repo(owner: str, repo: str) -> dict:
    """Fetch GitHub repo info via API."""
    try:
        headers = {"Accept": "application/vnd.github.v3+json"}
        meta = requests.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers, timeout=10).json()
        readme_resp = requests.get(f"https://api.github.com/repos/{owner}/{repo}/readme", headers=headers, timeout=10)
        readme_text = ""
        if readme_resp.ok:
            import base64
            readme_data = readme_resp.json()
            readme_text = base64.b64decode(readme_data.get("content", "")).decode("utf-8", errors="replace")[:2000]
        return {
            "type": "github_repo",
            "name": meta.get("full_name", f"{owner}/{repo}"),
            "description": meta.get("description", ""),
            "stars": meta.get("stargazers_count", 0),
            "language": meta.get("language", ""),
            "topics": meta.get("topics", []),
            "created_at": meta.get("created_at", ""),
            "updated_at": meta.get("pushed_at", ""),
            "readme_preview": readme_text[:1500],
        }
    except Exception as e:
        return {"type": "github_repo", "error": str(e)}


def _fetch_tweet(tweet_id: str) -> dict:
    """Fetch a tweet by ID via X API — returns text, URLs, media."""
    try:
        headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}"}
        params = {
            "tweet.fields": "text,entities,attachments,author_id",
            "expansions": "attachments.media_keys,author_id",
            "media.fields": "type,url,preview_image_url",
            "user.fields": "username",
        }
        resp = requests.get(f"https://api.x.com/2/tweets/{tweet_id}", headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        tweet = data.get("data", {})
        media = {m["media_key"]: m for m in data.get("includes", {}).get("media", [])}
        media_keys = tweet.get("attachments", {}).get("media_keys", [])
        return {
            "type": "tweet",
            "text": tweet.get("text", ""),
            "urls": [u.get("expanded_url", "") for u in tweet.get("entities", {}).get("urls", [])],
            "media": [{"type": media[mk]["type"], "url": media[mk].get("url", media[mk].get("preview_image_url", ""))} for mk in media_keys if mk in media],
        }
    except Exception as e:
        return {"type": "tweet", "error": str(e)}


def _fetch_via_firecrawl(url: str) -> dict:
    """Fetch URL via Firecrawl — renders JS, returns rich markdown."""
    fc = _get_firecrawl()
    if not fc:
        return _fetch_via_jina(url)
    try:
        result = fc.scrape(url, formats=["markdown"], timeout=30000, wait_for=5000)
        markdown = result.markdown or ""
        title = result.metadata.title if result.metadata else ""
        description = result.metadata.description if result.metadata else ""
        return {
            "type": "webpage_firecrawl",
            "url": url,
            "title": title,
            "description": description,
            "content": markdown[:4000],  # More generous limit with Firecrawl
        }
    except Exception as e:
        # Fall back to Jina if Firecrawl fails
        print(f"    Firecrawl failed for {url}: {e}, falling back to Jina")
        return _fetch_via_jina(url)


def _fetch_via_jina(url: str) -> dict:
    """Fetch URL content via Jina Reader — fallback if Firecrawl unavailable."""
    try:
        resp = requests.get(f"{JINA_PREFIX}{url}", timeout=15, headers={"Accept": "text/plain"})
        if resp.ok:
            return {"type": "webpage_jina", "url": url, "content": resp.text[:2000]}
        return {"type": "webpage_jina", "url": url, "content": f"[HTTP {resp.status_code}]"}
    except Exception as e:
        return {"type": "webpage_jina", "url": url, "error": str(e)}


def _resolve_content(url: str, depth: int = 0) -> dict:
    """Resolve a single URL. Recursive for x.com links."""
    if depth > MAX_DEPTH:
        return {"type": "max_depth", "url": url}

    gh_match = GITHUB_REPO_PATTERN.search(url)
    if gh_match:
        return _fetch_github_repo(gh_match.group(1), gh_match.group(2))

    x_match = X_STATUS_PATTERN.search(url)
    if x_match:
        tweet_data = _fetch_tweet(x_match.group(1))
        if "error" not in tweet_data:
            child_content = []
            for child_url in tweet_data.get("urls", []):
                if "x.com" not in child_url and "t.co" not in child_url:
                    child_content.append(_resolve_content(child_url, depth + 1))
            tweet_data["resolved_links"] = child_content
        return tweet_data

    return _fetch_via_firecrawl(url)


def _resolve_all_content(tweet: dict) -> dict:
    """Resolve all URLs and media in a tweet."""
    urls = [u.get("expanded_url", "") for u in tweet.get("entities", {}).get("urls", [])]
    resolved = []
    images = []

    for url in urls:
        if "t.co/" in url:
            url = _resolve_tco(url)
        resolved.append(_resolve_content(url))

    if tweet.get("media"):
        for m in tweet["media"]:
            if m.get("type") == "photo":
                images.append(m.get("url", m.get("preview_image_url", "")))
            elif m.get("type") == "video":
                preview = m.get("preview_image_url", "")
                if preview:
                    images.append(preview)

    return {
        **tweet,
        "resolved_content": resolved,
        "image_urls": images,
    }


def extract_content(tweets: list[dict]) -> dict:
    """Extract and resolve all content for filtered replies. Pure I/O."""
    print(f"  Extracting content for {len(tweets)} replies...")
    extracted = []
    errors = []
    for i, tweet in enumerate(tweets):
        try:
            result = _resolve_all_content(tweet)
            extracted.append(result)
            print(f"  [{i+1}/{len(tweets)}] @{tweet.get('author', {}).get('username', '?')} — {len(result['resolved_content'])} links, {len(result['image_urls'])} images")
        except Exception as e:
            print(f"  [{i+1}/{len(tweets)}] @{tweet.get('author', {}).get('username', '?')} — ERROR: {e}")
            # Don't drop — pass through with empty extraction
            extracted.append({**tweet, "resolved_content": [], "image_urls": [], "extraction_error": str(e)})
            errors.append(str(e))

    return {
        "extracted": extracted,
        "total_input": len(tweets),
        "total_output": len(extracted),
        "errors": errors,
    }
