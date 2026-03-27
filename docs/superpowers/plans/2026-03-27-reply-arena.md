# Reply Arena Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a live scorecard at ahad.nyc/reply-arena that fetches replies to Eric Glyman's hiring tweet, scores them through a 4-stage AI pipeline, and presents a ranked leaderboard of top builders.

**Architecture:** Local Python pipeline fetches X API replies, runs them through Filter → Synthesize → Score → Enrich stages using Claude API, outputs JSON. Static HTML site (Tailwind CDN) reads JSON and renders a green CRT terminal-themed leaderboard. Deploys to Vercel.

**Tech Stack:** Python 3.14, Anthropic SDK (anthropic 0.83.0), X API v2 (bearer token), HTML + Tailwind CSS CDN, Vercel

**Spec:** `docs/superpowers/specs/2026-03-27-reply-arena-design.md`

**Environment:**
- X API bearer token: `content/.env` → `X_BEARER_TOKEN`
- Anthropic API key: Already in environment (used by Claude CLI)
- Deploy target: Vercel (ahad.nyc)

---

## File Structure

```
website/reply-arena/
  ├── index.html              # Leaderboard page (CRT terminal theme)
  ├── how.html                # "How This Was Built" architecture page
  ├── scored-replies.json     # Pipeline output (generated, gitignored until first run)
  └── pipeline-log.json       # Pipeline stats (generated, gitignored until first run)

pipeline/
  ├── pipeline.py             # Orchestrator — sequences all 5 stages, supports --from-stage
  ├── fetch.py                # X API fetcher — paginate all replies
  ├── stage_filter.py         # Stage 1: LLM junk vs real project classification
  ├── stage_extract.py        # Stage 2: Follow links, fetch content, resolve recursively (I/O)
  ├── stage_synthesize.py     # Stage 3: LLM reads extracted content, produces structured summaries
  ├── stage_score.py          # Stage 4: LLM scoring on 3 dimensions
  ├── stage_enrich.py         # Stage 5: Profile enrichment for top N
  ├── prompts.py              # All LLM prompt templates
  ├── config.py               # Constants, API keys, file paths
  └── data/                   # Intermediate outputs (one JSON per stage)
      ├── 0_raw.json          # fetch output
      ├── 1_filtered.json     # filter output
      ├── 2_extracted.json    # extract output (raw artifacts per reply)
      ├── 3_synthesized.json  # synthesize output (structured project summaries)
      ├── 4_scored.json       # score output
      └── 5_enriched.json     # enrich output
```

**Design decisions:**
- Each pipeline stage is its own file — clear boundaries, testable independently
- **Layer isolation:** Each stage writes its output to `pipeline/data/`. The orchestrator supports `--from-stage N` to resume from any stage. Retuning scoring prompts doesn't require re-fetching or re-extracting.
- `prompts.py` centralizes all LLM prompts — easy to tune without touching logic
- `config.py` holds all env vars, paths, constants — single source of truth
- Pipeline outputs go directly into `website/reply-arena/` for Vercel deploy
- No test files — this is a time-sensitive one-shot project, not a library. We validate by running the pipeline and inspecting output.

**Extract + Synthesize strategy (informed by recon on actual replies):**

Content type breakdown of actual replies:
- 60% have URLs (7 GitHub, 21 x.com self-links, rest are product/portfolio sites)
- 40% plain text only (descriptions with no links)
- 11% have images (screenshots of apps, UIs)
- 5% have videos (demo recordings — we get preview thumbnails)

**Stage 2 — EXTRACT (I/O, deterministic):**
Tiered content resolution — recursive, depth-limited to 2 levels:
1. **GitHub links** → GitHub API (README, description, stars, languages, commit activity)
2. **x.com self-links** → X API to fetch linked tweet → then resolve ITS links/media recursively
3. **Product/portfolio URLs** → Jina Reader (`r.jina.ai/URL`) — renders JS, returns markdown
4. **Images** → Collect image URLs from X API media attachments
5. **Videos** → Collect preview thumbnail URLs from X API
6. **Plain text only** → No extraction needed, reply text + author bio passed through
7. **Unreachable links** → Flag as "not accessible", don't drop the candidate

Output: Raw artifacts per reply (fetched content, image URLs, GitHub data, linked tweets).

**Escape hatch:** The implementing agent runs inside Claude Code with full tool access. When deterministic resolvers fail (login walls, CAPTCHAs, App Store links, weird formats), the agent can use WebSearch, WebFetch, Playwright MCP, or its own reasoning to fill gaps. The plan handles the 80%; the agent's LLM capabilities handle the rest.

**Stage 3 — SYNTHESIZE (LLM reasoning):**
Takes the raw extracted artifacts and produces normalized, structured project summaries.
- Reads all collected evidence (text, GitHub data, page content, images via multimodal)
- Determines: "What did this person actually build? Is it real and substantive?"
- Outputs structured data: project name, summary, links, is_substantive flag
- Drops vaporware (empty evidence despite claims)
- Does NOT assess quality — that's the scorer's job

---

## Task 1: Pipeline Config and X API Fetcher

**Files:**
- Create: `pipeline/config.py`
- Create: `pipeline/fetch.py`

- [ ] **Step 1: Create config.py with all constants**

```python
# pipeline/config.py
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / "content" / ".env")

# X API
X_BEARER_TOKEN = os.environ.get("X_BEARER_TOKEN", "")
TWEET_ID = "2037554997982871650"
TWEET_AUTHOR = "eglyman"

# Claude API
CLAUDE_MODEL = "claude-sonnet-4-6"  # Fast + cheap for filter/score stages
CLAUDE_MODEL_DEEP = "claude-sonnet-4-6"  # For synthesis where quality matters

# Pipeline
TOP_N_ENRICH = 20  # How many to enrich with full profiles
OUTPUT_DIR = Path(__file__).parent.parent / "website" / "reply-arena"

# Score weights
SCORE_WEIGHTS = {
    "builder": 0.40,
    "creativity": 0.35,
    "quirkiness": 0.25,
}
```

- [ ] **Step 2: Create fetch.py — paginated X API fetcher**

```python
# pipeline/fetch.py
"""Fetch all replies to the target tweet via X API v2."""
import requests
from config import X_BEARER_TOKEN, TWEET_ID

API_URL = "https://api.x.com/2/tweets/search/recent"
HEADERS = {"Authorization": f"Bearer {X_BEARER_TOKEN}"}

TWEET_FIELDS = "created_at,public_metrics,text,author_id,in_reply_to_user_id"
USER_FIELDS = "name,username,description,public_metrics,profile_image_url,verified"
EXPANSIONS = "author_id"


def fetch_all_replies() -> dict:
    """Fetch all replies, paginating through results. Returns combined data."""
    all_tweets = []
    all_users = {}
    next_token = None

    while True:
        params = {
            "query": f"conversation_id:{TWEET_ID}",
            "max_results": 100,
            "tweet.fields": TWEET_FIELDS,
            "user.fields": USER_FIELDS,
            "expansions": EXPANSIONS,
        }
        if next_token:
            params["next_token"] = next_token

        resp = requests.get(API_URL, headers=HEADERS, params=params)
        resp.raise_for_status()
        data = resp.json()

        if "data" in data:
            all_tweets.extend(data["data"])
        if "includes" in data and "users" in data["includes"]:
            for user in data["includes"]["users"]:
                all_users[user["id"]] = user

        next_token = data.get("meta", {}).get("next_token")
        if not next_token:
            break

    # Attach user data to each tweet
    for tweet in all_tweets:
        tweet["author"] = all_users.get(tweet["author_id"], {})

    return {"tweets": all_tweets, "total": len(all_tweets)}


if __name__ == "__main__":
    result = fetch_all_replies()
    print(f"Fetched {result['total']} replies")
```

- [ ] **Step 3: Test the fetcher**

Run: `cd pipeline && python3 fetch.py`
Expected: "Fetched 176 replies" (or current count)

- [ ] **Step 4: Commit**

```bash
git add pipeline/config.py pipeline/fetch.py
git commit -m "feat: add pipeline config and X API reply fetcher"
```

---

## Task 2: Stage 1 — Filter (Junk vs Real Projects)

**Files:**
- Create: `pipeline/prompts.py`
- Create: `pipeline/stage_filter.py`

- [ ] **Step 1: Create prompts.py with filter prompt**

```python
# pipeline/prompts.py
"""All LLM prompt templates for the pipeline."""

FILTER_SYSTEM = """You are classifying replies to a hiring tweet by Eric Glyman (CEO of Ramp).
The tweet asked people to reply with something they've built.

Your job: classify each reply as either a REAL PROJECT SUBMISSION or JUNK.

REAL PROJECT = the person describes or links to something they actually built.n
JUNK = memes, jokes, "hire me" with no substance, off-topic comments, bare links with zero context, complaints, questions, career advice.

Be generous with REAL PROJECT — if someone describes building something even briefly, include it.
Only filter obvious non-submissions."""

FILTER_USER = """Classify these replies. Return a JSON array where each element is:
{{"id": "<tweet_id>", "classification": "real_project" | "junk", "reason": "<brief reason>"}}

Replies to classify:
{replies_json}"""

SYNTHESIZE_SYSTEM = """You are analyzing project submissions to a hiring tweet by Eric Glyman (CEO of Ramp).
For each reply, you need to determine: what did this person actually build?

Extract structured information about each project. If the reply includes URLs, you will
receive fetched content from those URLs to help you understand the project.

Focus on FACTS about the project. Do NOT assess quality — that's a separate stage.
Your job is to answer: "Is this a real, verifiable project with enough substance for a CEO to review?"

If a project is vaporware (empty repos, dead links, no evidence of real work), mark it as not substantive."""

SYNTHESIZE_USER = """Analyze these project submissions. For each, return:
{{
  "id": "<tweet_id>",
  "is_substantive": true | false,
  "project_name": "<name or short description>",
  "project_summary": "<2-3 sentences about what was built, how, and evidence of quality>",
  "links_found": ["<url1>", ...],
  "drop_reason": "<if not substantive, why>"
}}

Return a JSON array.

Submissions:
{submissions_json}"""

SCORE_SYSTEM = """You are scoring project submissions to a hiring tweet by Eric Glyman (CEO of Ramp).
Eric said he's looking for people who:
- Work best without permission
- Default to "how could I automate this"
- Had weird teenage hobbies

Score each project on 3 dimensions (0-100):

BUILDER (40% weight): Did they ship something real? Do they work without permission?
Evidence of actually building and deploying, not just talking about it.
High scores: live in production, real users, solo-built, evidence of velocity.
Low scores: vague claims, "working on" without shipping, team projects where their role is unclear.

CREATIVITY (35% weight): Is this novel or unexpected? Not another todo app or ChatGPT wrapper.
Something that shows original thinking or an unusual approach to a real problem.
High scores: solves a problem nobody else noticed, unexpected tech choice, creative application.
Low scores: yet another AI wrapper, portfolio clone, well-trodden tutorial project.

QUIRKINESS (25% weight): Does the person have personality? "Weird teenage hobbies" energy.
Something memorable or distinctive about them or their project.
High scores: unusual backstory, project born from a weird obsession, personality shines through.
Low scores: generic professional tone, could be anyone, nothing memorable.
Be generous — the bar is "is there ANY personality here?"

Return scores as integers 0-100. Include a brief justification for each score."""

SCORE_USER = """Score these verified projects. For each, return:
{{
  "id": "<tweet_id>",
  "scores": {{
    "builder": <0-100>,
    "creativity": <0-100>,
    "quirkiness": <0-100>
  }},
  "justification": {{
    "builder": "<brief reason>",
    "creativity": "<brief reason>",
    "quirkiness": "<brief reason>"
  }}
}}

Return a JSON array.

Projects to score:
{projects_json}"""

ENRICH_SYSTEM = """You are writing a brief dossier for a top-scoring candidate who replied to
Eric Glyman's hiring tweet at Ramp. Given their X profile data and project information,
write a 2-3 sentence write-up that captures who they are and why they stand out.

Keep it punchy and specific. No corporate language. Sound like a sharp recruiter's note, not a LinkedIn summary."""

ENRICH_USER = """Write a dossier for this candidate:

Handle: @{handle}
Name: {name}
Bio: {bio}
Followers: {followers}
Project: {project_name}
Project Summary: {project_summary}

Return a JSON object:
{{
  "write_up": "<2-3 sentence dossier>",
  "github_url": "<if found in bio or links, else null>",
  "linkedin_url": "<if found in bio or links, else null>"
}}"""
```

- [ ] **Step 2: Create stage_filter.py**

```python
# pipeline/stage_filter.py
"""Stage 1: Filter junk replies from real project submissions."""
import json
import anthropic
from prompts import FILTER_SYSTEM, FILTER_USER
from config import CLAUDE_MODEL

client = anthropic.Anthropic()

BATCH_SIZE = 30  # Replies per LLM call


def filter_replies(tweets: list[dict]) -> dict:
    """Classify tweets as real_project or junk. Returns filtered list + stats."""
    results = []

    # Process in batches
    for i in range(0, len(tweets), BATCH_SIZE):
        batch = tweets[i : i + BATCH_SIZE]
        replies_for_llm = [
            {
                "id": t["id"],
                "text": t["text"],
                "author_handle": t["author"].get("username", "unknown"),
                "author_bio": t["author"].get("description", ""),
                "in_reply_to": t.get("in_reply_to_user_id", ""),
            }
            for t in batch
        ]

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=FILTER_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": FILTER_USER.format(
                        replies_json=json.dumps(replies_for_llm, indent=2)
                    ),
                }
            ],
        )

        # Parse response
        text = response.content[0].text
        # Extract JSON from response (handle markdown code blocks)
        if "```" in text:
            text = text.split("```json")[-1].split("```")[0] if "```json" in text else text.split("```")[1].split("```")[0]
        batch_results = json.loads(text.strip())
        results.extend(batch_results)

    # Split into real vs junk
    real_ids = {r["id"] for r in results if r["classification"] == "real_project"}
    junk_reasons = {}
    for r in results:
        if r["classification"] == "junk":
            reason = r.get("reason", "unknown")
            junk_reasons[reason] = junk_reasons.get(reason, 0) + 1

    filtered = [t for t in tweets if t["id"] in real_ids]

    return {
        "filtered": filtered,
        "total_input": len(tweets),
        "total_output": len(filtered),
        "dropped": len(tweets) - len(filtered),
        "drop_reasons": junk_reasons,
    }
```

- [ ] **Step 3: Test filter stage standalone**

Run: `cd pipeline && python3 -c "from fetch import fetch_all_replies; from stage_filter import filter_replies; data = fetch_all_replies(); result = filter_replies(data['tweets']); print(f'Input: {result[\"total_input\"]}, Real projects: {result[\"total_output\"]}, Dropped: {result[\"dropped\"]}')"`
Expected: Input ~176, Real projects ~40-60, Dropped ~120-136

- [ ] **Step 4: Commit**

```bash
git add pipeline/prompts.py pipeline/stage_filter.py
git commit -m "feat: add filter stage and LLM prompt templates"
```

---

## Task 3: Stage 2 — Extract (Recursive Content Resolution)

**Files:**
- Create: `pipeline/stage_extract.py`

This is pure I/O — no LLM calls. Recursively resolves all content linked in each reply.

- [ ] **Step 1: Create stage_extract.py — recursive content resolver**

Tiered resolution with depth limit of 2:
- Resolve t.co → real URLs
- GitHub links → GitHub API (README, stars, languages, commit activity)
- x.com self-links → X API to fetch linked tweet → then resolve ITS links/media recursively
- Other URLs → Jina Reader for JS-rendered content
- Images → collect image URLs (for multimodal analysis in synthesize stage)
- Videos → collect preview thumbnail URLs
- Unreachable → flag, don't drop

```python
# pipeline/stage_extract.py
"""Stage 2: Recursive content extraction. Pure I/O — no LLM calls."""
import json
import re
import requests
from config import X_BEARER_TOKEN

MAX_DEPTH = 2
GITHUB_REPO_PATTERN = re.compile(r"github\.com/([^/]+)/([^/\s?#]+)")
X_STATUS_PATTERN = re.compile(r"x\.com/\w+/status/(\d+)")
JINA_PREFIX = "https://r.jina.ai/"


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


def _fetch_via_jina(url: str) -> dict:
    """Fetch URL content via Jina Reader — renders JS, returns markdown."""
    try:
        resp = requests.get(f"{JINA_PREFIX}{url}", timeout=15, headers={"Accept": "text/plain"})
        if resp.ok:
            return {"type": "webpage", "url": url, "content": resp.text[:2000]}
        return {"type": "webpage", "url": url, "content": f"[HTTP {resp.status_code}]"}
    except Exception as e:
        return {"type": "webpage", "url": url, "error": str(e)}


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

    return _fetch_via_jina(url)


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
```

- [ ] **Step 2: Test content resolver on real URLs**

Run: `cd pipeline && python3 -c "from stage_extract import _resolve_content; import json; print(json.dumps(_resolve_content('https://github.com/anthropics/claude-code'), indent=2))"`
Verify: Returns GitHub repo data with README, stars, language

Run: `cd pipeline && python3 -c "from stage_extract import _fetch_via_jina; print(_fetch_via_jina('https://example.com'))"`
Verify: Returns rendered page content via Jina

- [ ] **Step 3: Commit**

```bash
git add pipeline/stage_extract.py
git commit -m "feat: add extract stage — recursive content resolution (GitHub, X API, Jina)"
```

---

## Task 4: Stage 3 — Synthesize (LLM Reasoning Over Extracted Content)

**Files:**
- Create: `pipeline/stage_synthesize.py`
- Modify: `pipeline/prompts.py` (already has SYNTHESIZE prompts from Task 2)

Takes raw extracted artifacts and produces normalized, structured project summaries.
Uses multimodal Claude (Opus) to reason about all evidence: text, GitHub data, page content, images.

- [ ] **Step 1: Create stage_synthesize.py**

```python
# pipeline/stage_synthesize.py
"""Stage 3: LLM synthesis over extracted content. Produces structured project summaries."""
import json
import anthropic
from prompts import SYNTHESIZE_SYSTEM, SYNTHESIZE_USER
from config import CLAUDE_MODEL_DEEP

client = anthropic.Anthropic()

BATCH_SIZE = 5  # Small batches — each has rich extracted content


def synthesize_projects(tweets: list[dict]) -> dict:
    """LLM reads extracted artifacts, produces structured project summaries."""
    results = []

    for i in range(0, len(tweets), BATCH_SIZE):
        batch = tweets[i : i + BATCH_SIZE]
        submissions = []
        for t in batch:
            sub = {
                "id": t["id"],
                "text": t["text"],
                "author_handle": t.get("author", {}).get("username", "unknown"),
                "author_bio": t.get("author", {}).get("description", ""),
                "resolved_content": t.get("resolved_content", []),
                "has_images": len(t.get("image_urls", [])) > 0,
                "image_urls": t.get("image_urls", []),
            }
            submissions.append(sub)

        # Build multimodal message — text + images
        message_content = []
        message_content.append({
            "type": "text",
            "text": SYNTHESIZE_USER.format(submissions_json=json.dumps(submissions, indent=2)),
        })
        # Attach images for visual analysis (cap at 5 per batch)
        all_images = []
        for s in submissions:
            for img_url in s.get("image_urls", [])[:2]:
                all_images.append(img_url)
        for img_url in all_images[:5]:
            message_content.append({
                "type": "image",
                "source": {"type": "url", "url": img_url},
            })

        response = client.messages.create(
            model=CLAUDE_MODEL_DEEP,
            max_tokens=4096,
            system=SYNTHESIZE_SYSTEM,
            messages=[{"role": "user", "content": message_content}],
        )

        text = response.content[0].text
        if "```" in text:
            text = text.split("```json")[-1].split("```")[0] if "```json" in text else text.split("```")[1].split("```")[0]
        batch_results = json.loads(text.strip())
        results.extend(batch_results)

    # Merge synthesis results back with tweet data
    synthesis_by_id = {r["id"]: r for r in results}
    substantive = []
    drop_reasons = {}

    for tweet in tweets:
        synth = synthesis_by_id.get(tweet["id"])
        if not synth:
            continue
        if synth.get("is_substantive"):
            tweet["synthesis"] = synth
            substantive.append(tweet)
        else:
            reason = synth.get("drop_reason", "unknown")
            drop_reasons[reason] = drop_reasons.get(reason, 0) + 1

    return {
        "synthesized": substantive,
        "total_input": len(tweets),
        "total_output": len(substantive),
        "dropped": len(tweets) - len(substantive),
        "drop_reasons": drop_reasons,
    }
```

**Escape hatch:** If the deterministic extractors in Stage 2 failed for a reply (login wall, CAPTCHA, weird format), the implementing agent can use Claude Code tools (WebSearch, WebFetch, Playwright MCP) to manually fill in gaps before running this stage. The `2_extracted.json` intermediate file can be edited/augmented between runs.

- [ ] **Step 2: Commit**

```bash
git add pipeline/stage_synthesize.py
git commit -m "feat: add synthesize stage — LLM reasoning over extracted content"
```

---

## Task 5: Stage 4 — Score (3-Dimension LLM Scoring)

**Files:**
- Create: `pipeline/stage_score.py`

- [ ] **Step 1: Create stage_score.py**

```python
# pipeline/stage_score.py
"""Stage 3: LLM-based scoring on Builder, Creativity, Quirkiness."""
import json
import anthropic
from prompts import SCORE_SYSTEM, SCORE_USER
from config import CLAUDE_MODEL, SCORE_WEIGHTS

client = anthropic.Anthropic()

BATCH_SIZE = 15  # Score in batches


def _compute_composite(scores: dict) -> int:
    """Weighted average of 3 dimensions."""
    total = sum(scores[k] * SCORE_WEIGHTS[k] for k in SCORE_WEIGHTS)
    return round(total)


def score_projects(tweets: list[dict]) -> dict:
    """Score each project on 3 dimensions. Returns ranked list."""
    results = []

    for i in range(0, len(tweets), BATCH_SIZE):
        batch = tweets[i : i + BATCH_SIZE]
        projects = [
            {
                "id": t["id"],
                "text": t["text"],
                "author_handle": t["author"].get("username", "unknown"),
                "author_bio": t["author"].get("description", ""),
                "project_name": t["synthesis"]["project_name"],
                "project_summary": t["synthesis"]["project_summary"],
                "links": t["synthesis"].get("links_found", []),
            }
            for t in batch
        ]

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=SCORE_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": SCORE_USER.format(
                        projects_json=json.dumps(projects, indent=2)
                    ),
                }
            ],
        )

        text = response.content[0].text
        if "```" in text:
            text = text.split("```json")[-1].split("```")[0] if "```json" in text else text.split("```")[1].split("```")[0]
        batch_results = json.loads(text.strip())
        results.extend(batch_results)

    # Merge scores with tweet data and compute composites
    scores_by_id = {r["id"]: r for r in results}
    scored = []
    for tweet in tweets:
        score_data = scores_by_id.get(tweet["id"])
        if score_data:
            tweet["scores"] = score_data["scores"]
            tweet["scores"]["composite"] = _compute_composite(score_data["scores"])
            tweet["justification"] = score_data.get("justification", {})
            scored.append(tweet)

    # Sort by composite score descending
    scored.sort(key=lambda t: t["scores"]["composite"], reverse=True)

    # Assign ranks
    for i, tweet in enumerate(scored):
        tweet["rank"] = i + 1

    return {
        "scored": scored,
        "total_input": len(tweets),
        "total_output": len(scored),
    }
```

- [ ] **Step 2: Commit**

```bash
git add pipeline/stage_score.py
git commit -m "feat: add scoring stage — 3-dimension LLM scoring with weighted composite"
```

---

## Task 6: Stage 5 — Enrich (Profile Buildout for Top N)

**Files:**
- Create: `pipeline/stage_enrich.py`

- [ ] **Step 1: Create stage_enrich.py**

```python
# pipeline/stage_enrich.py
"""Stage 4: Enrich top N candidates with full profiles and dossier write-ups."""
import json
import anthropic
from prompts import ENRICH_SYSTEM, ENRICH_USER
from config import CLAUDE_MODEL, TOP_N_ENRICH

client = anthropic.Anthropic()


def enrich_candidates(tweets: list[dict]) -> dict:
    """Enrich top N candidates with dossier write-ups and profile links."""
    top_n = tweets[:TOP_N_ENRICH]
    enriched = []

    for tweet in top_n:
        author = tweet.get("author", {})
        synthesis = tweet.get("synthesis", {})

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=ENRICH_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": ENRICH_USER.format(
                        handle=author.get("username", "unknown"),
                        name=author.get("name", "Unknown"),
                        bio=author.get("description", "No bio"),
                        followers=author.get("public_metrics", {}).get("followers_count", 0),
                        project_name=synthesis.get("project_name", "Unknown project"),
                        project_summary=synthesis.get("project_summary", "No summary"),
                    ),
                }
            ],
        )

        text = response.content[0].text
        if "```" in text:
            text = text.split("```json")[-1].split("```")[0] if "```json" in text else text.split("```")[1].split("```")[0]
        enrichment = json.loads(text.strip())

        tweet["enrichment"] = enrichment
        enriched.append(tweet)

    # Non-enriched entries (ranked but no dossier)
    rest = tweets[TOP_N_ENRICH:]

    return {
        "enriched": enriched,
        "rest": rest,
        "total_input": len(tweets),
        "total_enriched": len(enriched),
    }
```

- [ ] **Step 2: Commit**

```bash
git add pipeline/stage_enrich.py
git commit -m "feat: add enrichment stage — dossier write-ups for top candidates"
```

---

## Task 7: Pipeline Orchestrator

**Files:**
- Create: `pipeline/pipeline.py`

- [ ] **Step 1: Create pipeline.py — the conductor**

```python
# pipeline/pipeline.py
"""Reply Arena Pipeline — orchestrates all 4 stages and writes output files."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from config import TWEET_ID, TWEET_AUTHOR, OUTPUT_DIR, TOP_N_ENRICH
from fetch import fetch_all_replies
from stage_filter import filter_replies
from stage_synthesize import synthesize_projects
from stage_score import score_projects
from stage_enrich import enrich_candidates


def run_pipeline():
    """Run the full 4-stage pipeline and write output files."""
    started_at = datetime.now(timezone.utc)
    stages_log = []

    print("=" * 60)
    print("REPLY ARENA PIPELINE")
    print("=" * 60)

    # --- FETCH ---
    print("\n[FETCH] Fetching replies from X API...")
    t0 = time.time()
    raw = fetch_all_replies()
    fetch_duration = round(time.time() - t0, 1)
    print(f"[FETCH] Got {raw['total']} replies in {fetch_duration}s")
    stages_log.append({
        "name": "fetch",
        "input": 0,
        "output": raw["total"],
        "duration_seconds": fetch_duration,
    })

    # --- STAGE 1: FILTER ---
    print(f"\n[FILTER] Classifying {raw['total']} replies...")
    t0 = time.time()
    filtered = filter_replies(raw["tweets"])
    filter_duration = round(time.time() - t0, 1)
    print(f"[FILTER] {filtered['total_output']} real projects, {filtered['dropped']} junk dropped in {filter_duration}s")
    stages_log.append({
        "name": "filter",
        "input": filtered["total_input"],
        "output": filtered["total_output"],
        "dropped": filtered["dropped"],
        "drop_reasons": filtered["drop_reasons"],
        "duration_seconds": filter_duration,
    })

    # --- STAGE 2: SYNTHESIZE ---
    print(f"\n[SYNTHESIZE] Analyzing {filtered['total_output']} projects...")
    t0 = time.time()
    synthesized = synthesize_projects(filtered["filtered"])
    synth_duration = round(time.time() - t0, 1)
    print(f"[SYNTHESIZE] {synthesized['total_output']} verified, {synthesized['dropped']} vapor in {synth_duration}s")
    stages_log.append({
        "name": "synthesize",
        "input": synthesized["total_input"],
        "output": synthesized["total_output"],
        "dropped": synthesized["dropped"],
        "drop_reasons": synthesized["drop_reasons"],
        "duration_seconds": synth_duration,
    })

    # --- STAGE 3: SCORE ---
    print(f"\n[SCORE] Scoring {synthesized['total_output']} projects...")
    t0 = time.time()
    scored = score_projects(synthesized["synthesized"])
    score_duration = round(time.time() - t0, 1)
    print(f"[SCORE] Ranked {scored['total_output']} projects in {score_duration}s")
    stages_log.append({
        "name": "score",
        "input": scored["total_input"],
        "output": scored["total_output"],
        "duration_seconds": score_duration,
    })

    # --- STAGE 4: ENRICH ---
    top_count = min(TOP_N_ENRICH, len(scored["scored"]))
    print(f"\n[ENRICH] Building dossiers for top {top_count}...")
    t0 = time.time()
    enriched = enrich_candidates(scored["scored"])
    enrich_duration = round(time.time() - t0, 1)
    print(f"[ENRICH] {enriched['total_enriched']} dossiers complete in {enrich_duration}s")
    stages_log.append({
        "name": "enrich",
        "input": scored["total_output"],
        "output": enriched["total_enriched"],
        "duration_seconds": enrich_duration,
    })

    # --- WRITE OUTPUT ---
    completed_at = datetime.now(timezone.utc)
    total_duration = round((completed_at - started_at).total_seconds(), 1)

    # Build scored-replies.json
    all_entries = enriched["enriched"] + enriched["rest"]
    elite_count = len([e for e in all_entries if e["rank"] <= 10])

    output_entries = []
    for entry in all_entries:
        author = entry.get("author", {})
        synthesis = entry.get("synthesis", {})
        scores = entry.get("scores", {})
        enrichment_data = entry.get("enrichment", {})

        output_entries.append({
            "rank": entry["rank"],
            "reply_id": entry["id"],
            "reply_url": f"https://x.com/{author.get('username', 'unknown')}/status/{entry['id']}",
            "author": {
                "handle": author.get("username", "unknown"),
                "name": author.get("name", "Unknown"),
                "bio": author.get("description", ""),
                "followers": author.get("public_metrics", {}).get("followers_count", 0),
                "profile_image_url": author.get("profile_image_url", ""),
            },
            "project": {
                "name": synthesis.get("project_name", ""),
                "summary": synthesis.get("project_summary", ""),
                "links": synthesis.get("links_found", []),
            },
            "scores": scores,
            "enrichment": enrichment_data if enrichment_data else None,
        })

    scored_output = {
        "meta": {
            "tweet_id": TWEET_ID,
            "author": TWEET_AUTHOR,
            "scanned_at": started_at.isoformat(),
            "total_replies": raw["total"],
            "after_filter": filtered["total_output"],
            "after_synthesize": synthesized["total_output"],
            "elite_count": elite_count,
        },
        "entries": output_entries,
    }

    pipeline_log = {
        "run_id": started_at.strftime("%Y-%m-%d-%H%M"),
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": total_duration,
        "stages": stages_log,
    }

    # Ensure output dir exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    scored_path = OUTPUT_DIR / "scored-replies.json"
    log_path = OUTPUT_DIR / "pipeline-log.json"

    scored_path.write_text(json.dumps(scored_output, indent=2))
    log_path.write_text(json.dumps(pipeline_log, indent=2))

    print(f"\n{'=' * 60}")
    print(f"PIPELINE COMPLETE in {total_duration}s")
    print(f"  Replies: {raw['total']} → {filtered['total_output']} → {synthesized['total_output']} → {elite_count} elite")
    print(f"  Output: {scored_path}")
    print(f"  Log:    {log_path}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    run_pipeline()
```

- [ ] **Step 2: Run the full pipeline end-to-end**

Run: `cd pipeline && python3 pipeline.py`
Expected: Full pipeline runs, prints stage-by-stage progress, writes JSON to `website/reply-arena/`

- [ ] **Step 3: Inspect output**

Run: `cat website/reply-arena/scored-replies.json | python3 -m json.tool | head -30`
Verify: JSON is well-formed, has meta + entries, entries are ranked

- [ ] **Step 4: Commit**

```bash
git add pipeline/pipeline.py
git commit -m "feat: add pipeline orchestrator — full 4-stage funnel"
```

---

## Task 8: Frontend — Leaderboard Page

**Files:**
- Create: `website/reply-arena/index.html`

**Note:** Use @frontend-design skill for this task. The design system is:
- Green CRT terminal + Matrix rain background
- Mobile-first responsive
- Monospace typography
- ASCII/tamagotchi accents (Claude Code terminal style)
- Solid dark panels for readability
- Colors: `#00ff41` primary, `#ffcc00` scores, `#ff0055` accents, `#00c8ff` links

- [ ] **Step 1: Create index.html with full leaderboard UI**

The page structure (top to bottom):
1. Boot sequence — one ambient line
2. Header panel — "REPLY ARENA" + subtitle + last scan timestamp
3. Hero stat — "X Elite out of Y" as the headline
4. Leaderboard — ranked entries, click/tap to expand dossier inline
5. Dossier panel — project summary, bio, score breakdown, link to original reply
6. Credits — operator, engine, weapons, build time
7. "How This Was Built" link → how.html

Technical requirements:
- Reads `scored-replies.json` via fetch() on page load
- Matrix rain canvas (low opacity, behind content)
- CRT scanlines overlay (subtle, no flicker)
- Inline dossier expand/collapse on entry click
- Mobile breakpoint at 600px
- All data rendered from JSON — no hardcoded content
- Fallback for missing profile images (terminal-style placeholder)
- `<meta viewport>` for mobile

Use Tailwind CDN + inline styles for the CRT/Matrix effects that Tailwind can't handle.

- [ ] **Step 2: Test locally**

Run: `cd website/reply-arena && python3 -m http.server 8080`
Open: http://localhost:8080
Verify: Leaderboard renders with real data, dossiers expand, mobile works (Chrome DevTools responsive mode)

- [ ] **Step 3: Commit**

```bash
git add website/reply-arena/index.html
git commit -m "feat: add Reply Arena leaderboard page"
```

---

## Task 9: Frontend — "How This Was Built" Page

**Files:**
- Create: `website/reply-arena/how.html`

**Note:** Use @frontend-design skill. Same design system as index.html.

- [ ] **Step 1: Create how.html**

The page structure:
1. Header — "HOW THIS WAS BUILT" title, link back to leaderboard
2. Pipeline diagram — visual 4-stage funnel with actual numbers from pipeline-log.json
3. Stage breakdown — for each stage: what it does, input/output counts, duration, drop reasons
4. Scoring rubric — what Builder, Creativity, Quirkiness mean
5. Tech stack — Claude Code, Opus, Skills, Plugins, Subagents
6. Build timeline — "Idea → Deployed: X hours"

Technical requirements:
- Reads `pipeline-log.json` via fetch()
- Same CRT terminal aesthetic
- Mobile responsive

- [ ] **Step 2: Test locally**

Open: http://localhost:8080/how.html
Verify: Pipeline stats render from JSON, all sections readable

- [ ] **Step 3: Commit**

```bash
git add website/reply-arena/how.html
git commit -m "feat: add 'How This Was Built' architecture page"
```

---

## Task 10: Run Pipeline + Deploy

- [ ] **Step 1: Run the full pipeline with real data**

Run: `cd pipeline && python3 pipeline.py`
Verify: Both JSON files written to `website/reply-arena/`

- [ ] **Step 2: Test the complete site locally**

Run: `cd website/reply-arena && python3 -m http.server 8080`
Open both pages, test on mobile viewport, verify all data renders correctly.

- [ ] **Step 3: Deploy to Vercel**

The website/ directory is already a Vercel project. Push to trigger deploy.

```bash
git add website/reply-arena/scored-replies.json website/reply-arena/pipeline-log.json
git commit -m "data: initial pipeline run — scored replies"
git push
```

Verify: `ahad.nyc/reply-arena` loads with real data

- [ ] **Step 4: Update credits with actual build time**

Once deployed, update the "IDEA → DEPLOYED" time in the credits to reflect the real duration from brainstorm to live.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: Reply Arena v1 — live on ahad.nyc/reply-arena"
```
