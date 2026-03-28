# pipeline/stage_score.py
"""Stage 4: LLM-based scoring on Builder, Creativity, Quirkiness. One project at a time."""
import json
import anthropic
from prompts import SCORE_SYSTEM, SCORE_USER
from config import CLAUDE_MODEL, SCORE_WEIGHTS

client = anthropic.Anthropic()


def _compute_composite(scores: dict) -> int:
    """Weighted average of 3 dimensions."""
    total = sum(scores[k] * SCORE_WEIGHTS[k] for k in SCORE_WEIGHTS)
    return round(total)


def _score_single(tweet: dict) -> dict:
    """Score a single project. No batch comparison — absolute scoring."""
    synthesis = tweet.get("synthesis", {})

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=SCORE_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": SCORE_USER.format(
                    project_id=tweet["id"],
                    author_handle=tweet["author"].get("username", "unknown"),
                    author_bio=tweet["author"].get("description", ""),
                    project_name=synthesis.get("project_name", ""),
                    project_summary=synthesis.get("project_summary", ""),
                    project_links=json.dumps(synthesis.get("links_found", [])),
                ),
            }
        ],
    )

    text = response.content[0].text
    if "```" in text:
        text = text.split("```json")[-1].split("```")[0] if "```json" in text else text.split("```")[1].split("```")[0]
    return json.loads(text.strip())


def score_projects(tweets: list[dict]) -> dict:
    """Score each project individually. Returns ranked list."""
    scored = []

    for i, tweet in enumerate(tweets):
        try:
            result = _score_single(tweet)
            tweet["scores"] = result["scores"]
            tweet["scores"]["composite"] = _compute_composite(result["scores"])
            tweet["justification"] = result.get("justification", {})
            scored.append(tweet)
            print(f"  [{i+1}/{len(tweets)}] @{tweet['author'].get('username', '?')} — {tweet['scores']['composite']} pts")
        except Exception as e:
            print(f"  [{i+1}/{len(tweets)}] @{tweet['author'].get('username', '?')} — SCORE ERROR: {e}")
            # Don't drop — assign zero scores
            tweet["scores"] = {"builder": 0, "creativity": 0, "quirkiness": 0, "composite": 0}
            tweet["justification"] = {"error": str(e)}
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
