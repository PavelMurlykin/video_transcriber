"""Validate a completed real run without printing or logging its transcript."""
import argparse
import json
from pathlib import Path


def check(directory: Path, expected_speakers: int | None = None, *,
          asr_only: bool = False, expected_language: str | None = None) -> dict:
    project = json.loads((directory / "transcript.json").read_text(encoding="utf-8"))
    metrics = json.loads((directory / "metrics.json").read_text(encoding="utf-8"))
    errors = []
    if metrics["status"] != "completed":
        errors.append("PIPELINE_NOT_COMPLETED")
    expected_stages = ["audio", "asr"] if asr_only else ["audio", "asr", "alignment", "diarization", "merge"]
    if project["completed_stages"] != expected_stages:
        errors.append("INCOMPLETE_STAGES")
    if project["schema_version"] != 1:
        errors.append("INVALID_SCHEMA_VERSION")
    if expected_language is not None and project["language"] != expected_language:
        errors.append("LANGUAGE_MISMATCH")
    duration = project["duration_ms"]
    assigned = set()
    timed_words = 0
    missing_words = 0
    cyrillic = False
    valid_speakers = {s["id"] for s in project["speakers"]} | {"unknown"}
    for segment in project["segments"]:
        if not 0 <= segment["start_ms"] < segment["end_ms"] <= duration:
            errors.append("INVALID_SEGMENT_INTERVAL")
        if segment["speaker_id"] not in valid_speakers:
            errors.append("INVALID_SPEAKER_ID")
        assigned.add(segment["speaker_id"])
        cyrillic |= any("А" <= c <= "я" or c in "Ёё" for c in segment["text"])
        if segment["review_reasons"] and not segment["requires_review"]:
            errors.append("REVIEW_FLAG_MISSING")
        for word in segment["words"]:
            if word["alignment_missing"]:
                missing_words += 1
                if word["start_ms"] is not None or word["end_ms"] is not None:
                    errors.append("FABRICATED_WORD_TIMES")
                if not segment["requires_review"] or "alignment_incomplete" not in segment["review_reasons"]:
                    errors.append("ALIGNMENT_REVIEW_FLAG_MISSING")
            else:
                timed_words += 1
                if not segment["start_ms"] <= word["start_ms"] < word["end_ms"] <= segment["end_ms"]:
                    errors.append("INVALID_WORD_INTERVAL")
    assigned.discard("unknown")
    if expected_speakers is not None and (len(project["speakers"]) != expected_speakers or len(assigned) != expected_speakers):
        errors.append("SPEAKER_COUNT_MISMATCH")
    if asr_only:
        if assigned or project["speakers"] or timed_words or missing_words:
            errors.append("UNEXPECTED_SPEAKERS_OR_WORD_TIMES")
        if not any(s["text"].strip() for s in project["segments"]) or (expected_language == "ru" and not cyrillic):
            errors.append("ASR_TRANSCRIPT_MISSING")
        if project.get("original_asr", {}).get("language") != project["language"]:
            errors.append("ASR_LANGUAGE_MISMATCH")
    elif not cyrillic or not timed_words:
        errors.append("RUSSIAN_ALIGNED_TRANSCRIPT_MISSING")
    summary = {"status": "failed" if errors else "completed", "errors": sorted(set(errors)), "duration_ms": duration,
               "speakers": len(project["speakers"]), "assigned_speakers": len(assigned), "segments": len(project["segments"]),
               "timed_words": timed_words, "unaligned_words": missing_words,
               "requires_review": sum(s["requires_review"] for s in project["segments"]),
               "os_network_block_verified": metrics.get("os_network_block_verified", False),
               "language": project["language"]}
    (directory / "validation.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--expected-speakers", type=int)
    parser.add_argument("--asr-only", action="store_true")
    parser.add_argument("--expected-language")
    args = parser.parse_args()
    if args.asr_only and args.expected_speakers is not None:
        parser.error("--expected-speakers is for the full pipeline")
    result = check(args.run_dir, args.expected_speakers,
                   asr_only=args.asr_only, expected_language=args.expected_language)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "completed" else 1)
