import hashlib
import json
from pathlib import Path

from local_transcriber.domain.paths import NonLocalPath, resolve_local


MODEL_SPECS = {
    "asr": {"source": "Systran/faster-whisper-large-v3", "license": "MIT", "revision": "edaa852ec7e145841d8ffdb056a99866b5f0a478",
            "required": ["config.json", "model.bin", "tokenizer.json", "preprocessor_config.json", "vocabulary.json"]},
    "alignment": {"source": "jonatasgrosman/wav2vec2-large-xlsr-53-russian", "license": "Apache-2.0", "revision": "2329100508896c6d9b157019803ab5601e6f3406",
                  "required": ["config.json", "preprocessor_config.json", "vocab.json", "special_tokens_map.json"]},
    "diarization": {"source": "pyannote/speaker-diarization-community-1", "license": "CC-BY-4.0", "revision": "3533c8cf8e369892e6b79ff1bf80f7b0286a54ee",
                    "required": ["config.yaml"]},
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory(root: Path) -> list[dict]:
    result = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".cache" in path.relative_to(root).parts or ".git" in path.relative_to(root).parts:
            continue
        with path.open("rb") as stream:
            if stream.read(80).startswith(b"version https://git-lfs.github.com/spec/v1"):
                raise ValueError("LFS_POINTER: " + str(path.relative_to(root)))
        result.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size, "sha256": sha256(path)})
    return result


def verify_models(config: dict, *, hashes: bool = True, asr_only: bool = False) -> list[str]:
    errors = []
    model_names = ("asr",) if asr_only else tuple(MODEL_SPECS)
    for name in model_names:
        spec = MODEL_SPECS[name]
        root = Path(config[name])
        for required in spec["required"]:
            if not (root / required).is_file():
                errors.append(f"MISSING:{name}/{required}")
        if name == "alignment" and not any((root / p).is_file() for p in ("pytorch_model.bin", "model.safetensors")):
            errors.append("MISSING:alignment/weights")
        if name == "diarization" and not any(root.rglob("*.bin")) and not any(root.rglob("*.safetensors")):
            errors.append("MISSING:diarization/weights")
    if not Path(config["vad"]).is_file():
        errors.append("MISSING:vad/weights")
    if not asr_only:
        for language in ("russian", "english"):
            for filename in ("abbrev_types.txt", "collocations.tab", "ortho_context.tab", "sent_starters.txt"):
                if not (Path(config["nltk_data"]) / "tokenizers/punkt_tab" / language / filename).is_file():
                    errors.append(f"MISSING:punkt_tab/{language}/{filename}")
    manifest_path = Path(config["manifest"])
    if not manifest_path.is_file():
        return errors + ["MISSING:manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        return errors + ["INVALID:manifest/schema_version"]
    resources = ("asr", "vad") if asr_only else (*model_names, "vad", "nltk_data")
    for name in resources:
        entry = manifest.get("models", {}).get(name, {})
        if not entry.get("files") or not entry.get("revision") or not entry.get("license"):
            errors.append(f"INVALID:manifest/{name}")
            continue
        if name in MODEL_SPECS and entry.get("source") != MODEL_SPECS[name]["source"]:
            errors.append(f"WRONG_SOURCE:manifest/{name}")
        root = Path(config[name]) if name != "vad" else Path(config["vad"]).parent
        declared = set()
        for file in entry["files"]:
            relative = Path(file["path"])
            if relative.anchor or ".." in relative.parts:
                errors.append(f"UNSAFE:manifest/{name}")
                continue
            try:
                target = resolve_local(root / relative)
            except NonLocalPath:
                errors.append(f"UNSAFE:manifest/{name}")
                continue
            if not target.is_relative_to(root):
                errors.append(f"UNSAFE:manifest/{name}")
                continue
            declared.add(relative.as_posix())
            if not target.is_file():
                errors.append(f"MISSING:{name}/{relative.as_posix()}")
            elif target.stat().st_size != file["size"] or (hashes and sha256(target) != file["sha256"]):
                errors.append(f"CORRUPT:{name}/{relative.as_posix()}")
        if root.is_dir():
            actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".cache" not in p.relative_to(root).parts and ".git" not in p.relative_to(root).parts}
            if actual != declared:
                errors.append(f"UNMANIFESTED:{name}")
        if name == "vad" and Path(config["vad"]).name not in declared:
            errors.append("UNMANIFESTED:vad/weights")
    return errors
