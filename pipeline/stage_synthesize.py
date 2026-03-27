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
