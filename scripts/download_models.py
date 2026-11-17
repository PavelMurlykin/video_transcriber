"""ONLINE PREPARATION ONLY. Never imported by inference. Does not save or print tokens."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from local_transcriber.core.model_manager import MODEL_SPECS, inventory, sha256


def save_entry(path, name, entry):
    from filelock import FileLock
    with FileLock(str(path) + ".lock"):
        latest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version": 1, "models": {}}
        latest["models"][name] = entry
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-root", type=Path, required=True)
    parser.add_argument("--reuse-asr", type=Path)
    parser.add_argument("--only", choices=[*MODEL_SPECS, "resources"])
    parser.add_argument("--inventory-existing", action="store_true", help="hash already prepared files; no network calls")
    args = parser.parse_args()
    root = args.models_root.expanduser()
    if not root.is_absolute():
        parser.error("--models-root must be absolute")
    root.mkdir(parents=True, exist_ok=True)
    names = {"asr": "whisper-large-v3", "alignment": "wav2vec2-ru", "diarization": "pyannote-community-1"}
    manifest_path = root / "models-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"schema_version": 1, "models": {}}
    from huggingface_hub import HfApi, snapshot_download
    for key, spec in MODEL_SPECS.items():
        if args.only and args.only != key:
            continue
        destination = root / names[key]
        # A cached token is deliberately not read: preparation accepts a temporary environment variable only.
        token = os.environ.get("HF_TOKEN") if key == "diarization" else False
        if args.inventory_existing:
            if not destination.is_dir():
                raise ValueError("MODEL_DIRECTORY_MISSING")
            existing = manifest.get("models", {}).get(key, {})
            if existing.get("revision"):
                revision = existing["revision"]
            else:
                metadata = list((destination / ".cache/huggingface/download").rglob("*.metadata"))
                if not metadata:
                    raise ValueError("REVISION_NOT_RECORDED")
                revisions = {p.read_text(encoding="utf-8").splitlines()[0] for p in metadata}
                if len(revisions) != 1:
                    raise ValueError("MIXED_MODEL_REVISIONS")
                revision = revisions.pop()
        elif key == "asr" and args.reuse_asr:
            source = args.reuse_asr.resolve(strict=True)
            if any(not (source / item).is_file() for item in spec["required"]):
                raise ValueError("INCOMPLETE_ASR_CACHE")
            if not destination.exists():
                # Materialize HF symlinks; moving the snapshot would break references to cache blobs.
                shutil.copytree(source, destination, symlinks=False)
            if inventory(source) != inventory(destination):
                raise ValueError("ASR_CACHE_COPY_MISMATCH")
            revision = source.name
        else:
            if key == "diarization" and not token:
                print("NEEDS_HF_TOKEN: accept Community-1 terms and set temporary HF_TOKEN; no token is saved.")
                return 3
            requested_revision = manifest.get("models", {}).get(key, {}).get("revision") or spec["revision"]
            info = HfApi().model_info(spec["source"], revision=requested_revision, token=token)
            revision = info.sha
            patterns = ["*.json", "*.bin", "*.safetensors", "README.md", "LICENSE*"] if key == "alignment" else None
            snapshot_download(spec["source"], revision=revision, local_dir=str(destination), token=token, allow_patterns=patterns)
        manifest["models"][key] = {"source": spec["source"], "revision": revision, "license": spec["license"],
                                    "required_files": spec["required"], "files": inventory(destination)}
        save_entry(manifest_path, key, manifest["models"][key])
        print(f"PREPARED:{key}:{revision}", flush=True)
    if not args.only or args.only == "resources":
        import nltk
        import whisperx
        resource_dir = root / "nltk_data"
        if not args.inventory_existing and not nltk.download("punkt_tab", download_dir=str(resource_dir), quiet=True, raise_on_error=True):
            raise RuntimeError("PUNKT_DOWNLOAD_FAILED")
        vad_source = Path(whisperx.__file__).parent / "assets/pytorch_model.bin"
        vad_dir = root / "vad"
        vad_dir.mkdir(exist_ok=True)
        shutil.copy2(vad_source, vad_dir / "pytorch_model.bin")
        for name, directory, source, revision, license_name in (
            ("vad", vad_dir, "https://github.com/m-bain/whisperX/tree/v3.8.6/whisperx/assets", importlib.metadata.version("whisperx"), "LicenseRef-WhisperX-VAD-see-upstream"),
            ("nltk_data", resource_dir, "https://github.com/nltk/nltk_data/tree/gh-pages/packages/tokenizers", "punkt_tab-sha256:" + sha256(resource_dir / "tokenizers/punkt_tab.zip"), "LicenseRef-Punkt-see-upstream"),
        ):
            manifest["models"][name] = {"source": source, "revision": revision, "license": license_name, "files": inventory(directory)}
            save_entry(manifest_path, name, manifest["models"][name])
        print("PREPARED:vad,nltk_data", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # Hub errors can contain authorization details; report their type and HTTP status only.
        response = getattr(error, "response", None)
        print(json.dumps({"status": "failed", "error_type": type(error).__name__, "http_status": getattr(response, "status_code", None)}))
        raise SystemExit(1)
