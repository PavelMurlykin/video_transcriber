import json
import os
from pathlib import Path


class ConfigurationError(ValueError):
    pass


PATH_FIELDS = ("models_root", "asr", "alignment", "diarization", "vad", "nltk_data", "manifest", "ffmpeg", "ffprobe")


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ConfigurationError("configuration must be a JSON object")
    for key in PATH_FIELDS:
        if not isinstance(config.get(key), str):
            raise ConfigurationError(f"{key}: absolute local path required")
        value = Path(os.path.expandvars(config.get(key, ""))).expanduser()
        if not value.is_absolute() or str(value).startswith(("\\\\", "//")):
            raise ConfigurationError(f"{key}: absolute local path required")
        config[key] = str(value.resolve())
    for key, default in (("device", "cuda"), ("compute_type", "float16"), ("batch_size", 4), ("num_speakers", 2)):
        config.setdefault(key, default)
    if config.get("device", "cuda") not in ("cuda", "cpu"):
        raise ConfigurationError("device must be cuda or cpu")
    if config.get("compute_type", "float16") not in ("float16", "float32", "int8", "int8_float16"):
        raise ConfigurationError("unsupported compute_type")
    if type(config.get("batch_size", 4)) is not int or config.get("batch_size", 4) < 1:
        raise ConfigurationError("batch_size must be a positive integer")
    count = config.get("num_speakers")
    if count is not None and (type(count) is not int or count < 1):
        raise ConfigurationError("num_speakers must be null or a positive integer")
    return config
