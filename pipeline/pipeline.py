#!/usr/bin/env python3
# pipeline/pipeline.py
"""Reply Arena Pipeline — orchestrates all 5 stages with incremental support."""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from config import TWEET_ID, TWEET_AUTHOR, OUTPUT_DIR, TOP_N_ENRICH, DATA_DIR
from fetch import fetch_all_replies
from stage_filter import filter_replies
from stage_extract import extract_content
from stage_synthesize import synthesize_projects
from stage_score import score_projects
from stage_enrich import enrich_candidates


def _save_stage(name: str, data: dict):
    """Save stage output to data/ for layer isolation."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str))
    print(f"  Saved: {path}")


def _load_stage(name: str) -> dict | None:
    """Load prior stage output from data/. Returns None if not found."""
    path = DATA_DIR / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _get_processed_ids(stage_data: dict | None, id_key: str = "id") -> set:
    """Extract already-processed tweet IDs from a stage's output."""
    if not stage_data:
        return set()
    # Different stages store entries under different keys
    for key in ["filtered", "extracted", "synthesized", "scored"]:
        if key in stage_data:
            return {t[id_key] for t in stage_data[key]}
    return set()


def run_pipeline(from_stage: int = 0, full: bool = False):
    """Run the pipeline. Incremental by default — only processes new replies."""
    started_at = datetime.now(timezone.utc)
    stages_log = []
    mode = "FULL" if full else "INCREMENTAL"

    print("=" * 60)
    print(f"REPLY ARENA PIPELINE ({mode})")
    print(f"Started: {started_at.isoformat()}")
    if from_stage > 0:
        print(f"Resuming from stage {from_stage}")
    print("=" * 60)

    # --- STAGE 0: FETCH ---
    if from_stage <= 0:
        print("\n[0/5] FETCH — Getting replies from X API...")
        t0 = time.time()
        raw = fetch_all_replies()
        duration = round(time.time() - t0, 1)

        if not full:
            existing_raw = _load_stage("0_raw")
            if existing_raw:
                existing_ids = {t["id"] for t in existing_raw["tweets"]}
                new_tweets = [t for t in raw["tweets"] if t["id"] not in existing_ids]
                # Merge: keep all existing + add new
                raw["tweets"] = existing_raw["tweets"] + new_tweets
                raw["total"] = len(raw["tweets"])
                print(f"  {len(new_tweets)} new replies (total: {raw['total']}) in {duration}s")
            else:
                print(f"  Got {raw['total']} replies in {duration}s")
        else:
            print(f"  Got {raw['total']} replies in {duration}s")

        _save_stage("0_raw", raw)
        stages_log.append({"name": "fetch", "input": 0, "output": raw["total"], "duration_seconds": duration})
    else:
        raw = _load_stage("0_raw")
        if not raw:
            print("  ERROR: No raw data found. Run full pipeline first.")
            sys.exit(1)
        print(f"\n[0/5] FETCH — Loaded {raw['total']} replies from cache")

    # --- STAGE 1: FILTER ---
    if from_stage <= 1:
        existing_filtered = _load_stage("1_filtered") if not full else None
        already_filtered_ids = _get_processed_ids(existing_filtered)

        # Only filter new tweets
        tweets_to_filter = [t for t in raw["tweets"] if t["id"] not in already_filtered_ids] if not full else raw["tweets"]

        if tweets_to_filter:
            print(f"\n[1/5] FILTER — Classifying {len(tweets_to_filter)} {'new ' if not full else ''}replies...")
            t0 = time.time()
            new_filtered = filter_replies(tweets_to_filter)
            duration = round(time.time() - t0, 1)
            print(f"  {new_filtered['total_output']} real projects, {new_filtered['dropped']} junk in {duration}s")

            # Merge with existing
            if existing_filtered and not full:
                merged_filtered = existing_filtered["filtered"] + new_filtered["filtered"]
                filtered = {
                    "filtered": merged_filtered,
                    "total_input": len(raw["tweets"]),
                    "total_output": len(merged_filtered),
                    "dropped": len(raw["tweets"]) - len(merged_filtered),
                    "drop_reasons": {**existing_filtered.get("drop_reasons", {}), **new_filtered.get("drop_reasons", {})},
                }
            else:
                filtered = new_filtered
        else:
            print(f"\n[1/5] FILTER — No new replies to filter")
            filtered = existing_filtered
            duration = 0

        _save_stage("1_filtered", filtered)
        stages_log.append({
            "name": "filter", "input": len(tweets_to_filter), "output": filtered["total_output"],
            "dropped": filtered["dropped"], "drop_reasons": filtered.get("drop_reasons", {}), "duration_seconds": duration if tweets_to_filter else 0,
        })
    else:
        filtered = _load_stage("1_filtered")
        if not filtered:
            print("  ERROR: No filtered data found. Run from earlier stage.")
            sys.exit(1)
        print(f"\n[1/5] FILTER — Loaded {filtered['total_output']} filtered replies from cache")

    # --- STAGE 2: EXTRACT ---
    if from_stage <= 2:
        existing_extracted = _load_stage("2_extracted") if not full else None
        already_extracted_ids = _get_processed_ids(existing_extracted)

        tweets_to_extract = [t for t in filtered["filtered"] if t["id"] not in already_extracted_ids] if not full else filtered["filtered"]

        if tweets_to_extract:
            print(f"\n[2/5] EXTRACT — Resolving content for {len(tweets_to_extract)} {'new ' if not full else ''}replies...")
            t0 = time.time()
            new_extracted = extract_content(tweets_to_extract)
            duration = round(time.time() - t0, 1)
            print(f"  {new_extracted['total_output']} extracted, {len(new_extracted['errors'])} errors in {duration}s")

            if existing_extracted and not full:
                merged_extracted = existing_extracted["extracted"] + new_extracted["extracted"]
                extracted = {
                    "extracted": merged_extracted,
                    "total_input": len(filtered["filtered"]),
                    "total_output": len(merged_extracted),
                    "errors": existing_extracted.get("errors", []) + new_extracted.get("errors", []),
                }
            else:
                extracted = new_extracted
        else:
            print(f"\n[2/5] EXTRACT — No new replies to extract")
            extracted = existing_extracted
            duration = 0

        _save_stage("2_extracted", extracted)
        stages_log.append({
            "name": "extract", "input": len(tweets_to_extract), "output": extracted["total_output"],
            "errors": len(extracted.get("errors", [])), "duration_seconds": duration if tweets_to_extract else 0,
        })
    else:
        extracted = _load_stage("2_extracted")
        if not extracted:
            print("  ERROR: No extracted data found. Run from earlier stage.")
            sys.exit(1)
        print(f"\n[2/5] EXTRACT — Loaded {extracted['total_output']} extracted replies from cache")

    # --- STAGE 3: SYNTHESIZE ---
    if from_stage <= 3:
        existing_synthesized = _load_stage("3_synthesized") if not full else None
        already_synthesized_ids = set()
        if existing_synthesized:
            already_synthesized_ids = {t["id"] for t in existing_synthesized.get("synthesized", [])}
            # Also count dropped IDs so we don't re-synthesize those
            # (they were already judged as not substantive)

        tweets_to_synthesize = [t for t in extracted["extracted"] if t["id"] not in already_synthesized_ids] if not full else extracted["extracted"]

        if tweets_to_synthesize:
            print(f"\n[3/5] SYNTHESIZE — Analyzing {len(tweets_to_synthesize)} {'new ' if not full else ''}projects...")
            t0 = time.time()
            new_synthesized = synthesize_projects(tweets_to_synthesize)
            duration = round(time.time() - t0, 1)
            print(f"  {new_synthesized['total_output']} substantive, {new_synthesized['dropped']} vapor in {duration}s")

            if existing_synthesized and not full:
                merged_synth = existing_synthesized["synthesized"] + new_synthesized["synthesized"]
                synthesized = {
                    "synthesized": merged_synth,
                    "total_input": extracted["total_output"],
                    "total_output": len(merged_synth),
                    "dropped": extracted["total_output"] - len(merged_synth),
                    "drop_reasons": {**existing_synthesized.get("drop_reasons", {}), **new_synthesized.get("drop_reasons", {})},
                }
            else:
                synthesized = new_synthesized
        else:
            print(f"\n[3/5] SYNTHESIZE — No new projects to synthesize")
            synthesized = existing_synthesized
            duration = 0

        _save_stage("3_synthesized", synthesized)
        stages_log.append({
            "name": "synthesize", "input": len(tweets_to_synthesize), "output": synthesized["total_output"],
            "dropped": synthesized.get("dropped", 0), "drop_reasons": synthesized.get("drop_reasons", {}),
            "duration_seconds": duration if tweets_to_synthesize else 0,
        })
    else:
        synthesized = _load_stage("3_synthesized")
        if not synthesized:
            print("  ERROR: No synthesized data found. Run from earlier stage.")
            sys.exit(1)
        print(f"\n[3/5] SYNTHESIZE — Loaded {synthesized['total_output']} synthesized projects from cache")

    # --- STAGE 4: SCORE ---
    if from_stage <= 4:
        existing_scored = _load_stage("4_scored")  # Always preserve existing scores
        already_scored_ids = set()
        already_scored_entries = []
        if existing_scored:
            already_scored_ids = {t["id"] for t in existing_scored.get("scored", [])}
            already_scored_entries = existing_scored["scored"]

        tweets_to_score = [t for t in synthesized["synthesized"] if t["id"] not in already_scored_ids]  # Scores are immutable — never re-score

        if tweets_to_score:
            print(f"\n[4/5] SCORE — Scoring {len(tweets_to_score)} {'new ' if not full else ''}projects (one at a time)...")
            t0 = time.time()
            new_scored = score_projects(tweets_to_score)
            duration = round(time.time() - t0, 1)
            print(f"  Scored {new_scored['total_output']} projects in {duration}s")

            # Merge: existing locked scores + new scores
            all_scored = already_scored_entries + new_scored["scored"]

            # Re-sort and re-rank the full set
            all_scored.sort(key=lambda t: t.get("scores", {}).get("composite", 0), reverse=True)

            # Deduplicate
            seen = set()
            deduped = []
            for t in all_scored:
                tid = t.get("id", t.get("reply_id", ""))
                if tid not in seen:
                    seen.add(tid)
                    deduped.append(t)

            # Store previous ranks for movement indicators
            old_ranks = {t.get("id", ""): t.get("rank", 999) for t in already_scored_entries}
            for i, t in enumerate(deduped):
                t["previous_rank"] = old_ranks.get(t.get("id", ""))
                t["rank"] = i + 1

            scored = {
                "scored": deduped,
                "total_input": synthesized["total_output"],
                "total_output": len(deduped),
            }
        else:
            print(f"\n[4/5] SCORE — No new projects to score")
            scored = existing_scored
            duration = 0

        _save_stage("4_scored", scored)
        stages_log.append({
            "name": "score", "input": len(tweets_to_score), "output": scored["total_output"],
            "duration_seconds": duration if tweets_to_score else 0,
        })
    else:
        scored = _load_stage("4_scored")
        if not scored:
            print("  ERROR: No scored data found. Run from earlier stage.")
            sys.exit(1)
        print(f"\n[4/5] SCORE — Loaded {scored['total_output']} scored projects from cache")

    # --- STAGE 5: ENRICH ---
    # Always re-enrich top N (cheap, and top N may have changed)
    top_count = min(TOP_N_ENRICH, len(scored["scored"]))
    print(f"\n[5/5] ENRICH — Building dossiers for top {top_count}...")
    t0 = time.time()
    enriched = enrich_candidates(scored["scored"])
    duration = round(time.time() - t0, 1)
    print(f"  {enriched['total_enriched']} dossiers complete in {duration}s")
    _save_stage("5_enriched", enriched)
    stages_log.append({
        "name": "enrich", "input": scored["total_output"], "output": enriched["total_enriched"],
        "duration_seconds": duration,
    })

    # --- WRITE FINAL OUTPUT ---
    completed_at = datetime.now(timezone.utc)
    total_duration = round((completed_at - started_at).total_seconds(), 1)

    all_entries = enriched["enriched"] + enriched["rest"]
    elite_count = len([e for e in all_entries if e.get("rank", 999) <= 10])

    output_entries = []
    for entry in all_entries:
        author = entry.get("author", {})
        synthesis = entry.get("synthesis", {})
        scores = entry.get("scores", {})
        enrichment_data = entry.get("enrichment", {})

        output_entries.append({
            "rank": entry.get("rank", 999),
            "reply_id": entry.get("id", entry.get("reply_id", "")),
            "reply_url": f"https://x.com/{author.get('username', author.get('handle', 'unknown'))}/status/{entry.get('id', entry.get('reply_id', ''))}",
            "previous_rank": entry.get("previous_rank"),
            "author": {
                "handle": author.get("username", author.get("handle", "unknown")),
                "name": author.get("name", "Unknown"),
                "bio": author.get("description", author.get("bio", "")),
                "followers": author.get("public_metrics", {}).get("followers_count", author.get("followers", 0)),
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

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    scored_path = OUTPUT_DIR / "scored-replies.json"
    log_path = OUTPUT_DIR / "pipeline-log.json"

    scored_path.write_text(json.dumps(scored_output, indent=2, default=str))
    log_path.write_text(json.dumps(pipeline_log, indent=2, default=str))

    print(f"\n{'=' * 60}")
    print(f"PIPELINE COMPLETE ({mode}) in {total_duration}s")
    print(f"  Replies: {raw['total']} → {filtered['total_output']} → {synthesized['total_output']} → {elite_count} elite")
    print(f"  Output: {scored_path}")
    print(f"  Log:    {log_path}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reply Arena Pipeline")
    parser.add_argument("--from-stage", type=int, default=0, help="Resume from stage N")
    parser.add_argument("--full", action="store_true", help="Full re-run (ignore cached data, reprocess everything)")
    args = parser.parse_args()
    run_pipeline(from_stage=args.from_stage, full=args.full)
