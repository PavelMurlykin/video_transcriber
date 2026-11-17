import argparse
import json
import os
from pathlib import Path
import sys

from .config import load_config
from .core.model_manager import verify_models


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local Transcriber - stage 0 offline CLI prototype (Russian)")
    parser.add_argument("--config", type=Path, default=Path("config.local.json"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("verify-models", help="verify all local resources and SHA-256 hashes")
    run = subparsers.add_parser("transcribe")
    run.add_argument("input", type=Path)
    run.add_argument("--run-dir", type=Path, required=True, help="new directory for private outputs and metrics")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "verify-models":
            errors = verify_models(config)
            print(json.dumps({"status": "failed" if errors else "completed", "errors": errors}))
            return 2 if errors else 0
        from .core.offline_guard import offline_environment, block_network
        from .core.pipeline import run_pipeline
        env = offline_environment()
        for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN"):
            os.environ.pop(key, None)
        os.environ.update(env)
        with block_network():
            result = run_pipeline(args.config, config, args.input, args.run_dir, event=lambda message: print(message, flush=True))
        print(json.dumps({key: result[key] for key in ("status", "wall_seconds", "speaker_count", "segment_count")}))
        return 0
    except KeyboardInterrupt:
        print('{"status":"cancelled"}', file=sys.stderr)
        return 130
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__,
                          "hint": "Check config, verify-models and run-dir/metrics.json; transcript contents are not logged."}), file=sys.stderr)
        return 2 if isinstance(error, (ValueError, FileNotFoundError, FileExistsError)) else 1
