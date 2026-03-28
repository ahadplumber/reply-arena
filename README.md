# Reply Arena

AI-powered scorecard for [@eglyman's hiring tweet](https://x.com/eglyman/status/2037554997982871650).

Fetches all replies, runs them through a 5-stage AI pipeline, and presents a ranked leaderboard of the top builders.

**Live:** [reply-arena.ahad.nyc](https://reply-arena.ahad.nyc)

## Pipeline

```
Replies → FETCH → FILTER → EXTRACT → SYNTHESIZE → SCORE → ENRICH → Ranked leaderboard
```

| Stage | What it does |
|-------|-------------|
| **Fetch** | X API v2, paginated with media expansion |
| **Filter** | LLM classifies junk vs real project submissions |
| **Extract** | Recursive content resolution (GitHub API, X API, Firecrawl, multimodal) |
| **Synthesize** | LLM reads all evidence + images, produces structured project summaries |
| **Score** | One-at-a-time absolute scoring: Builder (.40), Creativity (.35), Quirkiness (.25) |
| **Enrich** | Dossier write-ups for top candidates |

Scores are **immutable** — once an entry is scored, it is never re-scored. The pipeline runs incrementally by default, only processing new replies.

## Scoring Criteria

Based on Eric's original tweet — "You'll be a good fit if you work best without permission, default to 'how could I automate this', and had weird teenage hobbies."

- **Builder** — Shipped something real. Works without permission. Evidence of velocity.
- **Creativity** — Novel or unexpected. Not another todo app. Original thinking.
- **Quirkiness** — Personality shines through. "Weird teenage hobbies" energy.

## Architecture

- **Layer isolation:** Each stage writes output to `pipeline/data/`. Resume from any stage with `--from-stage N`.
- **Tiered extraction:** GitHub → API. x.com self-links → X API (recursive). Other URLs → Firecrawl. Images → multimodal.
- **No backend:** Pipeline runs locally, outputs JSON. Static HTML reads JSON. Deployed to Vercel.

## Stack

Claude Code, Claude Opus 4.6, Anthropic SDK, X API v2, GitHub API, Firecrawl, HTML + Tailwind CSS, Vercel

## Run it yourself

```bash
cp .env.example .env
# Fill in your API keys

cd pipeline
pip install anthropic requests python-dotenv firecrawl-py

# Incremental run (default — only processes new replies)
python pipeline.py

# Full re-run (re-fetches and re-processes everything, but never re-scores)
python pipeline.py --full

# Resume from a specific stage
python pipeline.py --from-stage 3
```

## Built by

[@plumberahad](https://x.com/plumberahad) — idea to deployed in 3 hours using Claude Code primitives (Skills, Plugins, Subagents, Loops, Firecrawl).
