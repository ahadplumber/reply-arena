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
