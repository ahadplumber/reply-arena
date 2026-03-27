# pipeline/stage_score.py
"""Stage 4: LLM-based scoring on Builder, Creativity, Quirkiness."""
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
