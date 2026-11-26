import argparse
import json
import os
from pathlib import Path
import sys

from .config import ConfigurationError, load_asr_config, load_config, load_media_config
from .core.model_manager import verify_models
from .core.transcription import ASROptions, LANGUAGES, PROFILES
from .domain.errors import ASROutOfMemory, MediaError
from .storage.commands import add_project_commands, run_project_command
from .storage.projects import ProjectStoreError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local Transcriber - offline media preparation and transcription")
    parser.add_argument("--config", type=Path, default=Path("config.local.json"))
    parser.add_argument("--project-db", type=Path, help="path to the local SQLite project database")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_project_commands(subparsers)
    subparsers.add_parser("verify-models", help="verify all local resources and SHA-256 hashes")
    for name, help_text in (
        ("prepare-media", "extract a 16 kHz mono PCM WAV"),
        ("asr", "recognize speech offline and save a project JSON"),
        ("transcribe", "run offline Russian transcription and diarization"),
    ):
        run = subparsers.add_parser(name, help=help_text)
        run.add_argument("input", type=Path)
        run.add_argument("--run-dir", type=Path, required=True, help="new directory for private outputs and metrics")
        if name != "prepare-media":
            run.add_argument("--terms-file", type=Path, help="local UTF-8 text file, one suggested term per line")
            run.add_argument("--profile", choices=PROFILES, default="default", help="ASR memory profile")
        if name == "asr":
            run.add_argument("--language", choices=LANGUAGES, default="ru")
    args = parser.parse_args(argv)
    try:
        if args.command == "projects":
            return run_project_command(args)
        if args.command == "prepare-media":
            from .core.media import create_run_directory, prepare_audio
            from .core.offline_guard import block_network
            config = load_media_config(args.config)
            directory = create_run_directory(args.run_dir)
            with block_network():
                metadata = prepare_audio(args.input, directory / "audio.wav", config)
            print(json.dumps({"status": "completed", **metadata}))
            return 0
        asr_only = args.command == "asr"
        config = load_asr_config(args.config) if asr_only else load_config(args.config)
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
        options = ASROptions(getattr(args, "language", "ru"), args.profile, args.terms_file)
        with block_network():
            result = run_pipeline(
                args.config, config, args.input, args.run_dir, asr_only=asr_only, options=options,
                project_db=args.project_db,
                event=lambda message: print(message, flush=True),
            )
        keys = ("status", "project_id", "wall_seconds", "speaker_count", "segment_count", "recognized_language")
        print(json.dumps({key: result[key] for key in keys}))
        return 0
    except KeyboardInterrupt:
        print('{"status":"cancelled"}', file=sys.stderr)
        return 130
    except MediaError as error:
        print(json.dumps({"status": "failed", "error_code": error.code, "hint": error.hint}), file=sys.stderr)
        return error.exit_code
    except ASROutOfMemory as error:
        hint = ("Retry once with --profile memory and a new --run-dir." if args.profile != "memory"
                else "Use a new --run-dir and retry with batch_size=1 or a CPU int8 configuration.")
        print(json.dumps({"status": "failed", "error_code": error.code, "hint": hint}), file=sys.stderr)
        return 1
    except ConfigurationError as error:
        print(json.dumps({"status": "failed", "error_code": "INVALID_CONFIG", "hint": str(error)}), file=sys.stderr)
        return 2
    except ProjectStoreError as error:
        print(json.dumps({"status": "failed", "error_code": error.code}), file=sys.stderr)
        return 2
    except Exception as error:
        hints = {"prepare-media": "Check --config and the output directory.",
                 "projects": "Check the project database, JSON format and local file paths."}
        hint = hints.get(args.command, "Check config, verify-models and run-dir/metrics.json.")
        print(json.dumps({"status": "failed", "error_type": type(error).__name__,
                          "hint": hint}), file=sys.stderr)
        return 2 if isinstance(error, (ValueError, FileNotFoundError, FileExistsError)) else 1
