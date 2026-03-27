# pipeline/stage_enrich.py
"""Stage 5: Enrich top N candidates with full profiles and dossier write-ups."""
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
