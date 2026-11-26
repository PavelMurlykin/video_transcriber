import json
from pathlib import Path

import pytest

from local_transcriber.config import ConfigurationError, PATH_FIELDS, load_config
from local_transcriber.core.model_manager import MODEL_SPECS, inventory, verify_models


def test_reject_remote_model_alias(tmp_path):
    config = {key: str(tmp_path / key) for key in PATH_FIELDS}
    config["asr"] = "Systran/faster-whisper-large-v3"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ConfigurationError):
        load_config(path)


def test_lfs_pointer_is_not_a_model(tmp_path):
    (tmp_path / "model.bin").write_text("version https://git-lfs.github.com/spec/v1\noid sha256:example")
    with pytest.raises(ValueError, match="LFS_POINTER"):
        inventory(tmp_path)


def test_default_profile_is_explicit_after_config_load(tmp_path):
    config = {key: str(tmp_path / key) for key in PATH_FIELDS}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    loaded = load_config(path)
    assert (loaded["device"], loaded["compute_type"], loaded["batch_size"], loaded["num_speakers"]) == ("cuda", "float16", 4, 2)


def model_fixture(tmp_path):
    config = {key: str(tmp_path / key) for key in PATH_FIELDS}
    config["vad"] = str(tmp_path / "vad/weights.bin")
    config["manifest"] = str(tmp_path / "manifest.json")
    for name, spec in MODEL_SPECS.items():
        root = Path(config[name])
        root.mkdir()
        for file in spec["required"] + (["pytorch_model.bin"] if name != "asr" else []):
            (root / file).write_bytes(b"synthetic-test-data")
    Path(config["vad"]).parent.mkdir()
    Path(config["vad"]).write_bytes(b"synthetic-vad")
    for language in ("russian", "english"):
        directory = Path(config["nltk_data"]) / "tokenizers/punkt_tab" / language
        directory.mkdir(parents=True)
        for name in ("abbrev_types.txt", "collocations.tab", "ortho_context.tab", "sent_starters.txt"):
            (directory / name).write_bytes(b"synthetic-punkt")
    entries = {}
    for name in (*MODEL_SPECS, "vad", "nltk_data"):
        root = Path(config[name]).parent if name == "vad" else Path(config[name])
        entries[name] = {"revision": "synthetic", "license": "test", "files": inventory(root),
                         "source": MODEL_SPECS[name]["source"] if name in MODEL_SPECS else "synthetic"}
    Path(config["manifest"]).write_text(json.dumps({"schema_version": 1, "models": entries}))
    return config


def test_hash_verification_detects_same_size_corruption(tmp_path):
    config = model_fixture(tmp_path)
    assert verify_models(config) == []
    path = Path(config["asr"]) / "model.bin"
    path.write_bytes(b"x" * path.stat().st_size)
    assert "CORRUPT:asr/model.bin" in verify_models(config)


def test_asr_verifies_only_recognizer_and_vad_assets(tmp_path):
    config = model_fixture(tmp_path)
    settings = {key: config[key] for key in ("asr", "vad", "manifest")}
    (Path(config["alignment"]) / "config.json").unlink()
    assert verify_models(settings, asr_only=True) == []
    Path(config["vad"]).unlink()
    assert "MISSING:vad/weights" in verify_models(settings, asr_only=True)


def test_missing_component_and_path_escape_rejected(tmp_path):
    config = model_fixture(tmp_path)
    Path(config["vad"]).unlink()
    manifest_path = Path(config["manifest"])
    manifest = json.loads(manifest_path.read_text())
    manifest["models"]["asr"]["files"][0]["path"] = "../outside.bin"
    manifest_path.write_text(json.dumps(manifest))
    errors = verify_models(config)
    assert "MISSING:vad/weights" in errors
    assert "UNSAFE:manifest/asr" in errors
