from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from local_transcriber.config import ConfigurationError, PATH_FIELDS, load_config
from local_transcriber.domain.transcript_schema import write_json
from local_transcriber.storage.projects import DATABASE_FILENAME, local_path

INFERENCE_FIELDS = (*PATH_FIELDS, "device", "compute_type", "batch_size", "num_speakers", "min_speakers", "max_speakers")


def absolute_local(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ConfigurationError("Absolute local path required")
    return local_path(path)


@dataclass
class Settings:
    base_config: Path
    preferences: Path
    config: dict
    results: Path
    language: str = "ru"
    theme: str = "system"

    @classmethod
    def load(cls, config: Path, preferences: Path):
        has_preferences = preferences.is_file()
        data = load_config(preferences if has_preferences else config)
        results = data.get("results") if has_preferences else str(config.parent / "artifacts")
        if not isinstance(results, str):
            raise ConfigurationError("The results folder must be an absolute local path")
        return cls(
            config, preferences, {key: data[key] for key in INFERENCE_FIELDS if key in data},
            absolute_local(results), data.get("ui_language", "ru"), data.get("theme", "system"),
        )

    @property
    def active_config(self) -> Path:
        return self.preferences if self.preferences.is_file() else self.base_config

    @property
    def database(self) -> Path:
        return self.results / DATABASE_FILENAME

    def save(self) -> None:
        for key in PATH_FIELDS:
            absolute_local(self.config[key])
        self.results.mkdir(parents=True, exist_ok=True)
        self.preferences.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.preferences, {
            **self.config, "results": str(self.results), "ui_language": self.language, "theme": self.theme,
        })


@dataclass(frozen=True)
class RunRequest:
    source: Path
    language: str
    speaker_count: int
    profile: str

    @property
    def full_pipeline(self) -> bool:
        return self.language == "ru"

    def prepare(self, settings: Settings) -> tuple[list[str], Path, Path]:
        settings.results.mkdir(parents=True, exist_ok=True)
        name = f"desktop-{uuid4().hex}"
        output = settings.results / name
        snapshot = output.with_suffix(".config.json")
        cancel = output.with_suffix(".cancel")
        config = dict(settings.config)
        if self.full_pipeline:
            config.pop("min_speakers", None)
            config.pop("max_speakers", None)
            config["num_speakers"] = self.speaker_count or None
        write_json(snapshot, config)
        args = ["--config", str(snapshot), "--project-db", str(settings.database),
                "transcribe" if self.full_pipeline else "asr", str(self.source),
                "--run-dir", str(output), "--profile", self.profile, "--cancel-file", str(cancel)]
        if not self.full_pipeline:
            args += ["--language", self.language]
        return args, snapshot, cancel
