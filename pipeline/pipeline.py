#!/usr/bin/env python3
# pipeline/pipeline.py
"""Reply Arena Pipeline — orchestrates all 5 stages and writes output files."""
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


def _load_stage(name: str) -> dict:
    """Load prior stage output from data/."""
    path = DATA_DIR / f"{name}.json"
    if not path.exists():
        print(f"  ERROR: {path} not found. Run earlier stages first.")
        sys.exit(1)
    return json.loads(path.read_text())


def run_pipeline(from_stage: int = 0):
    """Run the pipeline from the given stage onwards."""
    started_at = datetime.now(timezone.utc)
    stages_log = []

    print("=" * 60)
    print("REPLY ARENA PIPELINE")
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
        print(f"  Got {raw['total']} replies in {duration}s")
        _save_stage("0_raw", raw)
        stages_log.append({"name": "fetch", "input": 0, "output": raw["total"], "duration_seconds": duration})
    else:
        raw = _load_stage("0_raw")
        print(f"\n[0/5] FETCH — Loaded {raw['total']} replies from cache")

    # --- STAGE 1: FILTER ---
    if from_stage <= 1:
        print(f"\n[1/5] FILTER — Classifying {raw['total']} replies...")
        t0 = time.time()
        filtered = filter_replies(raw["tweets"])
        duration = round(time.time() - t0, 1)
        print(f"  {filtered['total_output']} real projects, {filtered['dropped']} junk in {duration}s")
        _save_stage("1_filtered", filtered)
        stages_log.append({
            "name": "filter", "input": filtered["total_input"], "output": filtered["total_output"],
            "dropped": filtered["dropped"], "drop_reasons": filtered["drop_reasons"], "duration_seconds": duration,
        })
    else:
        filtered = _load_stage("1_filtered")
        print(f"\n[1/5] FILTER — Loaded {filtered['total_output']} filtered replies from cache")

    # --- STAGE 2: EXTRACT ---
    if from_stage <= 2:
        print(f"\n[2/5] EXTRACT — Resolving content for {filtered['total_output']} replies...")
        t0 = time.time()
        extracted = extract_content(filtered["filtered"])
        duration = round(time.time() - t0, 1)
        print(f"  {extracted['total_output']} extracted, {len(extracted['errors'])} errors in {duration}s")
        _save_stage("2_extracted", extracted)
        stages_log.append({
            "name": "extract", "input": extracted["total_input"], "output": extracted["total_output"],
            "errors": len(extracted["errors"]), "duration_seconds": duration,
        })
    else:
        extracted = _load_stage("2_extracted")
        print(f"\n[2/5] EXTRACT — Loaded {extracted['total_output']} extracted replies from cache")

    # --- STAGE 3: SYNTHESIZE ---
    if from_stage <= 3:
        print(f"\n[3/5] SYNTHESIZE — Analyzing {extracted['total_output']} projects...")
        t0 = time.time()
        synthesized = synthesize_projects(extracted["extracted"])
        duration = round(time.time() - t0, 1)
        print(f"  {synthesized['total_output']} substantive, {synthesized['dropped']} vapor in {duration}s")
        _save_stage("3_synthesized", synthesized)
        stages_log.append({
            "name": "synthesize", "input": synthesized["total_input"], "output": synthesized["total_output"],
            "dropped": synthesized["dropped"], "drop_reasons": synthesized["drop_reasons"], "duration_seconds": duration,
        })
    else:
        synthesized = _load_stage("3_synthesized")
        print(f"\n[3/5] SYNTHESIZE — Loaded {synthesized['total_output']} synthesized projects from cache")

    # --- STAGE 4: SCORE ---
    if from_stage <= 4:
        print(f"\n[4/5] SCORE — Scoring {synthesized['total_output']} projects...")
        t0 = time.time()
        scored = score_projects(synthesized["synthesized"])
        duration = round(time.time() - t0, 1)
        print(f"  Ranked {scored['total_output']} projects in {duration}s")
        _save_stage("4_scored", scored)
        stages_log.append({
            "name": "score", "input": scored["total_input"], "output": scored["total_output"],
            "duration_seconds": duration,
        })
    else:
        scored = _load_stage("4_scored")
        print(f"\n[4/5] SCORE — Loaded {scored['total_output']} scored projects from cache")

    # --- STAGE 5: ENRICH ---
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

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    scored_path = OUTPUT_DIR / "scored-replies.json"
    log_path = OUTPUT_DIR / "pipeline-log.json"

    scored_path.write_text(json.dumps(scored_output, indent=2, default=str))
    log_path.write_text(json.dumps(pipeline_log, indent=2, default=str))

    print(f"\n{'=' * 60}")
    print(f"PIPELINE COMPLETE in {total_duration}s")
    print(f"  Replies: {raw['total']} → {filtered['total_output']} → {synthesized['total_output']} → {elite_count} elite")
    print(f"  Output: {scored_path}")
    print(f"  Log:    {log_path}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reply Arena Pipeline")
    parser.add_argument("--from-stage", type=int, default=0, help="Resume from stage N (0=fetch, 1=filter, 2=extract, 3=synthesize, 4=score, 5=enrich)")
    args = parser.parse_args()
    run_pipeline(from_stage=args.from_stage)
