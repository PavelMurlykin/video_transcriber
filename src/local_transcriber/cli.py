import argparse
import json
from pathlib import Path
import sys

from .config import ConfigurationError, load_asr_config, load_config, load_media_config
from .core.model_manager import verify_models
from .core.transcription import ASROptions, LANGUAGES, PROFILES
from .core.offline_guard import offline_runtime
from .domain.errors import ASROutOfMemory, ExportError, MediaError, PipelineError
from .storage.commands import add_project_commands, run_project_command
from .storage.projects import ProjectStoreError, local_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local Transcriber - offline media preparation and transcription")
    parser.add_argument("--config", type=Path, default=Path("config.local.json"))
    parser.add_argument("--project-db", type=Path, help="path to the local SQLite project database")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_project_commands(subparsers)
    subparsers.add_parser("inspect-media", help="inspect a local file").add_argument("input", type=Path)
    subparsers.add_parser("verify-models", help="verify all local resources and SHA-256 hashes")
    runtime = subparsers.add_parser("check-runtime", help="check local tools, models, compute device and output disk")
    runtime.add_argument("--results-dir", type=Path)
    runtime.add_argument("--asr-only", action="store_true")
    runtime.add_argument("--profile", choices=PROFILES, default="default")
    for name, help_text in (
        ("prepare-media", "extract a 16 kHz mono PCM WAV"),
        ("asr", "recognize speech offline and save a project JSON"),
        ("transcribe", "run offline Russian transcription and diarization"),
    ):
        run = subparsers.add_parser(name, help=help_text)
        run.add_argument("input", type=Path)
        run.add_argument("--run-dir", type=Path, required=True, help="new directory for private outputs and metrics")
        if name != "prepare-media":
            run.add_argument("--cancel-file", type=Path, help=argparse.SUPPRESS)
            run.add_argument("--terms-file", type=Path, help="local UTF-8 text file, one suggested term per line")
            run.add_argument("--profile", choices=PROFILES, default="default", help="ASR memory profile")
        if name == "asr":
            run.add_argument("--language", choices=LANGUAGES, default="ru")
    args = parser.parse_args(argv)
    try:
        with offline_runtime():
            return _dispatch(args)
    except KeyboardInterrupt:
        print('{"status":"cancelled"}', file=sys.stderr)
        return 130
    except MediaError as error:
        print(json.dumps({"status": "failed", "error_code": error.code, "hint": error.hint}), file=sys.stderr)
        return error.exit_code
    except ExportError as error:
        print(json.dumps({"status": "failed", "error_code": error.code, "hint": error.hint}), file=sys.stderr)
        return 2
    except PipelineError as error:
        print(json.dumps({"status": "failed", "error_code": error.code, "hint": error.hint,
                          "errors": error.errors}), file=sys.stderr)
        return 2 if error.code == "RUNTIME_CHECK_FAILED" else 1
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
                 "inspect-media": "Check --config and the media file.",
                 "projects": "Check the project database, JSON format and local file paths."}
        hint = hints.get(args.command, "Check config, verify-models and run-dir/metrics.json.")
        print(json.dumps({"status": "failed", "error_type": type(error).__name__,
                          "hint": hint}), file=sys.stderr)
        return 2 if isinstance(error, (ValueError, FileNotFoundError, FileExistsError)) else 1


def _dispatch(args):
    if args.command == "projects":
        return run_project_command(args)
    if args.command == "inspect-media":
        from .core.media import probe_media
        print(json.dumps(probe_media(args.input, load_media_config(args.config))))
        return 0
    if args.command == "prepare-media":
        from .core.media import create_run_directory, prepare_audio
        config = load_media_config(args.config)
        directory = create_run_directory(args.run_dir)
        metadata = prepare_audio(args.input, directory / "audio.wav", config)
        print(json.dumps({"status": "completed", **metadata}))
        return 0

    asr_only = args.command == "asr" or getattr(args, "asr_only", False)
    config = load_asr_config(args.config) if asr_only else load_config(args.config)
    if args.command == "verify-models":
        errors = verify_models(config)
        print(json.dumps({"status": "failed" if errors else "completed", "errors": errors}))
        return 2 if errors else 0

    options = ASROptions(getattr(args, "language", "ru"), args.profile, getattr(args, "terms_file", None))
    if args.command == "check-runtime":
        from .core.runtime import check_runtime
        directory = args.results_dir or local_path(args.config).parent / "artifacts"
        compute_type, _ = options.inference_settings(config)
        errors = check_runtime(config, directory, asr_only=asr_only, compute_type=compute_type)
        if errors:
            raise PipelineError("RUNTIME_CHECK_FAILED", "Check the listed local dependencies and output drive.", errors=errors)
        print(json.dumps({"status": "completed", "device": config["device"], "errors": []}))
        return 0

    from .core.pipeline import run_pipeline
    result = run_pipeline(
        args.config, config, args.input, args.run_dir, asr_only=asr_only, options=options,
        project_db=args.project_db,
        cancel_file=local_path(args.cancel_file) if args.cancel_file is not None else None,
        event=lambda message: print(message, flush=True),
    )
    keys = ("status", "project_id", "wall_seconds", "speaker_count", "segment_count", "recognized_language")
    print(json.dumps({key: result[key] for key in keys}))
    return 0
