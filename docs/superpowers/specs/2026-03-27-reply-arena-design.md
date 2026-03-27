# Reply Arena — Design Spec

## Overview

**Reply Arena** is a live scorecard that fetches all replies to [Eric Glyman's hiring tweet](https://x.com/eglyman/status/2037554997982871650), runs them through a 4-stage AI pipeline, and presents a ranked leaderboard of the top builders. Deployed at `ahad.nyc/reply-arena`.

**The pitch:** Instead of replying "here's what I built," Ahad replies with something he built *for Eric, right now* — proving the point by doing it.

## Deliverables

1. **Reply Arena** — the live scorecard (this spec)
2. **Portfolio website refresh** — content update on ahad.nyc (separate spec)
3. **Remotion marketing video** — short video showcasing the feature (separate spec)

## Architecture

```
Local pipeline (Claude Code + subagents)
  ├── Fetch: X API v2 → paginate all replies
  ├── Stage 1 — FILTER: LLM classifies junk vs real project submissions
  ├── Stage 2 — SYNTHESIZE: Follow links, verify projects, extract structured summary
  ├── Stage 3 — SCORE: LLM scores against criteria + quality/creativity/quirkiness
  ├── Stage 4 — ENRICH: Top N get full profiles (X bio, GitHub, LinkedIn, write-up)
  └── Output: scored-replies.json + pipeline-log.json

Static site (website/reply-arena/)
  ├── index.html — the leaderboard
  ├── how.html — "How This Was Built" architecture page
  ├── scored-replies.json
  └── pipeline-log.json

Deploy: Vercel (ahad.nyc/reply-arena)
Refresh: Re-run pipeline → redeploy (manual, /loop, or /schedule)
```

**No backend. No serverless functions. No database.** The pipeline runs locally, outputs JSON, the site is static.

## Pipeline

### Orchestrator

`pipeline.py` — a Python conductor script that sequences the 4 stages:

```
pipeline.py
  ├── fetch_replies()        → X API, paginate, return raw data
  ├── stage_1_filter()       → dispatch Claude subagent, return filtered list
  ├── stage_2_synthesize()   → dispatch subagent(s), follow links, return structured data
  ├── stage_3_score()        → dispatch subagent, return scored/ranked list
  ├── stage_4_enrich()       → dispatch parallel subagents, return enriched profiles
  └── write_output()         → write scored-replies.json + pipeline-log.json
```

The conductor is deterministic — it handles sequencing, error handling, retries. LLM work happens inside each stage via Claude API calls. The conductor never makes judgment calls.

### Stage 1 — FILTER

- **Input:** Raw replies from X API (176+)
- **Action:** LLM classifies each reply as `real_project` or `junk`
- **Junk criteria:** Memes, "hire me" with no substance, replies to other replies, off-topic, bare links with zero context
- **Output:** Array of real project submissions
- **Expected drop rate:** ~60-70%

### Stage 2 — EXTRACT

- **Input:** Filtered replies
- **Action:** Pure I/O. Recursively resolve all linked content: GitHub API for repos, X API for self-linked tweets (then resolve their links/media), Jina Reader for product/portfolio URLs, collect image URLs and video thumbnails.
- **Output:** Raw artifacts per reply (fetched content, image URLs, GitHub data, linked tweets)
- **Depth limit:** 2 levels (reply → linked tweet → linked project)
- **Escape hatch:** When deterministic resolvers fail (login walls, CAPTCHAs, weird formats), the implementing agent uses Claude Code tools (WebSearch, WebFetch, Playwright) to fill gaps.
- **Key constraint:** No LLM calls. No quality judgments. Just collect evidence.

### Stage 3 — SYNTHESIZE

- **Input:** Extracted artifacts from Stage 2
- **Action:** LLM (Opus) reads all collected evidence — text, GitHub data, rendered pages, images (multimodal) — and produces normalized, structured project summaries.
- **Output:** Structured object per reply:
  ```
  { handle, reply_text, project_name, project_summary, links_found, is_substantive }
  ```
- **Drop criteria:** Vaporware (empty evidence despite claims)
- **Key constraint:** Determines "is this a real project?" — does NOT assess quality. That's the scorer's job.

### Stage 3 — SCORE

- **Input:** Verified project corpus
- **Action:** LLM scores each on 3 dimensions (0-100):
  - **Builder** (40%) — matches "works without permission," shipped something real
  - **Creativity** (35%) — novel, unexpected, not cookie-cutter
  - **Quirkiness** (25%) — "weird teenage hobbies" energy, personality shows through
- **Output:** Composite score (weighted average) + ranked leaderboard

### Stage 4 — ENRICH

- **Input:** Top N scorers (15-20)
- **Action:** Pull X profile data (bio, followers, profile image), attempt to find GitHub/LinkedIn, generate short dossier write-up
- **Output:** Final `scored-replies.json` with everything the frontend needs
- **Depth decisions:** Deferred to implementation plan

## Frontend

### Design System

- **Background:** Matrix rain (canvas, low opacity, ambient only — visible in margins, not behind content)
- **Overlay:** CRT scanlines (subtle, no flicker)
- **Accents:** ASCII/pixel art characters in Claude Code tamagotchi terminal style — subtle, characterful, easter eggs not theme
- **Colors:** Green phosphor `#00ff41` primary, `#ffcc00` scores/highlights, `#ff0055` danger/accents, `#00c8ff` links
- **Typography:** Monospace everything (Courier New / system mono)
- **Panels:** Solid dark backgrounds (`rgba(8,8,8,0.97)`) over rain — content always readable
- **Responsive:** Mobile-first. Eric will open this from X on his phone.

### Page 1: `/reply-arena/index.html` — The Leaderboard

Top to bottom:
1. **Boot sequence** — one ambient line ("X API connected · 176 replies fetched · pipeline armed")
2. **Header panel** — "REPLY ARENA" title + "@eglyman hiring thread · builder scorecard" subtitle + last scan timestamp
3. **Hero stat** — "10 Elite out of 176" — the headline. Everything else demoted. Subtitle like "scanned and scored by AI"
4. **Leaderboard** — ranked entries, click/tap to expand dossier inline
5. **Dossier panel** (expanded) — project summary, bio, followers, links (GitHub/LinkedIn/portfolio), score breakdown (Builder/Creativity/Quirkiness), link to original reply on X
6. **Credits** — OPERATOR (@plumberahad), ENGINE (Claude Code + Opus), WEAPONS (Skills × Plugins × Subagents), "IDEA → DEPLOYED: X HOURS"
7. **"How This Was Built" link** → `/reply-arena/how`

### Page 2: `/reply-arena/how.html` — The Architecture Flex

- Pipeline diagram (4-stage funnel, visual)
- Stats from the actual run (counts at each stage, timing, drop reasons)
- Scoring rubric — what each dimension means
- Tech stack breakdown
- Build timeline
- Reads from `pipeline-log.json` for real numbers

## Data Model

### `scored-replies.json`

```json
{
  "meta": {
    "tweet_id": "2037554997982871650",
    "author": "eglyman",
    "scanned_at": "2026-03-27T18:42:00Z",
    "total_replies": 176,
    "after_filter": 48,
    "after_synthesize": 42,
    "elite_count": 10
  },
  "entries": [
    {
      "rank": 1,
      "reply_id": "2037596...",
      "reply_url": "https://x.com/handle/status/...",
      "author": {
        "handle": "craftsman_dev",
        "name": "Alex Chen",
        "bio": "Eng @ stealth. Previously infra at Stripe.",
        "followers": 3241,
        "profile_image_url": "https://pbs.twimg.com/..."
      },
      "project": {
        "name": "Real-time fraud detection engine",
        "summary": "Processes 50k events/sec. Solo built in 3 months. Live in prod.",
        "links": ["https://github.com/...", "https://fraudengine.dev"]
      },
      "scores": {
        "builder": 96,
        "creativity": 91,
        "quirkiness": 88,
        "composite": 93
      },
      "enrichment": {
        "github_url": "https://github.com/craftsman",
        "linkedin_url": "https://linkedin.com/in/...",
        "write_up": "Former Stripe infra engineer who..."
      }
    }
  ]
}
```

### `pipeline-log.json`

```json
{
  "run_id": "2026-03-27-001",
  "started_at": "2026-03-27T18:40:00Z",
  "completed_at": "2026-03-27T18:43:00Z",
  "duration_seconds": 180,
  "stages": [
    {
      "name": "fetch",
      "input": 0,
      "output": 176,
      "duration_seconds": 4
    },
    {
      "name": "filter",
      "input": 176,
      "output": 48,
      "dropped": 128,
      "drop_reasons": {"no_project": 89, "reply_to_reply": 24, "off_topic": 15},
      "duration_seconds": 30
    },
    {
      "name": "synthesize",
      "input": 48,
      "output": 42,
      "dropped": 6,
      "drop_reasons": {"dead_links": 3, "vaporware": 3},
      "duration_seconds": 60
    },
    {
      "name": "score",
      "input": 42,
      "output": 42,
      "duration_seconds": 45
    },
    {
      "name": "enrich",
      "input": 15,
      "output": 15,
      "duration_seconds": 40
    }
  ]
}
```

## Refresh Strategy

The tweet's replies are hot now and will taper in 24-48 hours. Options:
- **Manual:** Run `python3 pipeline.py` → redeploy
- **`/loop`:** Run in current session on interval (needs laptop open)
- **`/schedule`:** Remote agent on cron (no laptop needed)

Exact mechanism decided during implementation.

## Open Questions (for implementation plan)

- Synthesis depth: How deep to analyze linked projects?
- Score weights: Equal across 4 dimensions or weighted?
- Enrichment depth: Web search for LinkedIn/GitHub or just use available data?
- Which Claude model for each stage? (cost/quality tradeoff)
- How many parallel subagents for enrichment?
- Exact URL path: `ahad.nyc/reply-arena` vs other options?
