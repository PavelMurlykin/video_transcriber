"""Produce a shareable technical summary from whitelisted fields, without transcript text."""
import argparse
import json
from pathlib import Path


def summarize(directory: Path) -> dict:
    metrics = json.loads((directory / "metrics.json").read_text(encoding="utf-8"))
    return {key: metrics[key] for key in ("status", "duration_ms", "wall_seconds", "speaker_count", "segment_count",
                                         "segments_requiring_review", "os_network_block_verified", "versions", "profile", "stages") if key in metrics}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = {directory.name: summarize(directory) for directory in args.runs}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("Saved technical summary; transcript text excluded")
