# Reply Arena

AI-powered scorecard for [@eglyman's hiring tweet](https://x.com/eglyman/status/2037554997982871650).

Fetches all replies, runs them through a 5-stage AI pipeline, and presents a ranked leaderboard of the top builders.

**Live:** [ahad.nyc/reply-arena](https://www.ahad.nyc/reply-arena)

## Pipeline

```
311 replies → FETCH → FILTER → EXTRACT → SYNTHESIZE → SCORE → ENRICH → Top 10
```

| Stage | What it does | I/O |
|-------|-------------|-----|
| **Fetch** | X API v2, paginated with media expansion | 0 → 311 |
| **Filter** | LLM classifies junk vs real project submissions | 311 → 163 |
| **Extract** | Recursive content resolution (GitHub API, X API, Firecrawl) | 163 → 163 |
| **Synthesize** | LLM reads all evidence, produces structured project summaries | 163 → 79 |
| **Score** | 3-dimension scoring: Builder (.40), Creativity (.35), Quirkiness (.25) | 79 ranked |
| **Enrich** | Dossier write-ups for top 20 | 20 enriched |

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

# Full run
python pipeline.py

# Resume from a specific stage
python pipeline.py --from-stage 3
```

## Built by

[@plumberahad](https://x.com/plumberahad) — idea to deployed in 3 hours using Claude Code primitives (Skills, Plugins, Subagents, Loops, Firecrawl).
