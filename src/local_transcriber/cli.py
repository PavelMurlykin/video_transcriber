import argparse
import json
import os
from pathlib import Path
import sys

from .config import ConfigurationError, load_config, load_media_config
from .core.model_manager import verify_models
from .domain.errors import MediaError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local Transcriber - offline media preparation and transcription")
    parser.add_argument("--config", type=Path, default=Path("config.local.json"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("verify-models", help="verify all local resources and SHA-256 hashes")
    for name, help_text in (
        ("prepare-media", "extract a 16 kHz mono PCM WAV"),
        ("transcribe", "run offline Russian transcription and diarization"),
    ):
        run = subparsers.add_parser(name, help=help_text)
        run.add_argument("input", type=Path)
        run.add_argument("--run-dir", type=Path, required=True, help="new directory for private outputs and metrics")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare-media":
            from .core.media import create_run_directory, prepare_audio
            from .core.offline_guard import block_network
            config = load_media_config(args.config)
            directory = create_run_directory(args.run_dir)
            with block_network():
                metadata = prepare_audio(args.input, directory / "audio.wav", config)
            print(json.dumps({"status": "completed", **metadata}))
            return 0
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
    except MediaError as error:
        print(json.dumps({"status": "failed", "error_code": error.code, "hint": error.hint}), file=sys.stderr)
        return error.exit_code
    except ConfigurationError as error:
        print(json.dumps({"status": "failed", "error_code": "INVALID_CONFIG", "hint": str(error)}), file=sys.stderr)
        return 2
    except Exception as error:
        hint = ("Check --config and the output directory." if args.command == "prepare-media"
                else "Check config, verify-models and run-dir/metrics.json.")
        print(json.dumps({"status": "failed", "error_type": type(error).__name__,
                          "hint": hint}), file=sys.stderr)
        return 2 if isinstance(error, (ValueError, FileNotFoundError, FileExistsError)) else 1
