import json
import os
from pathlib import Path


class ConfigurationError(ValueError):
    pass


MEDIA_PATH_FIELDS = ("ffmpeg", "ffprobe")
ASR_PATH_FIELDS = ("asr", "vad", "manifest", *MEDIA_PATH_FIELDS)
PATH_FIELDS = ("models_root", "asr", "alignment", "diarization", "vad", "nltk_data", "manifest", *MEDIA_PATH_FIELDS)


def _load_paths(path: Path, keys: tuple[str, ...]) -> dict:
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ConfigurationError("configuration must be a JSON object")
    for key in keys:
        if not isinstance(config.get(key), str):
            raise ConfigurationError(f"{key}: absolute local path required")
        value = Path(os.path.expandvars(config.get(key, ""))).expanduser()
        if not value.is_absolute() or str(value).startswith(("\\\\", "//")):
            raise ConfigurationError(f"{key}: absolute local path required")
        resolved = value.resolve()
        if str(resolved).startswith(("\\\\", "//")):
            raise ConfigurationError(f"{key}: absolute local path required")
        config[key] = str(resolved)
    return config


def load_media_config(path: Path) -> dict:
    return _load_paths(path, MEDIA_PATH_FIELDS)


def _load_inference_config(path: Path, keys: tuple[str, ...]) -> dict:
    config = _load_paths(path, keys)
    for key, default in (("device", "cuda"), ("compute_type", "float16"), ("batch_size", 4)):
        config.setdefault(key, default)
    if config["device"] not in ("cuda", "cpu"):
        raise ConfigurationError("device must be cuda or cpu")
    if config["compute_type"] not in ("float16", "float32", "int8", "int8_float16"):
        raise ConfigurationError("unsupported compute_type")
    if type(config["batch_size"]) is not int or config["batch_size"] < 1:
        raise ConfigurationError("batch_size must be a positive integer")
    return config


def load_asr_config(path: Path) -> dict:
    return _load_inference_config(path, ASR_PATH_FIELDS)


def speaker_count_options(config: dict) -> dict[str, int]:
    low, high = config.get("min_speakers"), config.get("max_speakers")
    ranged = low is not None or high is not None
    count = config.get("num_speakers", None if ranged else 2)
    if count is not None and (type(count) is not int or count < 1):
        raise ConfigurationError("num_speakers must be null or a positive integer")
    if ranged:
        if count is not None:
            raise ConfigurationError("set num_speakers to null or omit it when using a speaker range")
        if type(low) is not int or type(high) is not int or not 1 <= low <= high:
            raise ConfigurationError("speaker range requires positive integers min_speakers <= max_speakers")
        return {"min_speakers": low, "max_speakers": high}
    return {"num_speakers": count} if count is not None else {}


def load_config(path: Path) -> dict:
    config = _load_inference_config(path, PATH_FIELDS)
    config["num_speakers"] = speaker_count_options(config).get("num_speakers")
    return config
