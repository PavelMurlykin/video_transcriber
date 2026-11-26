"""Serialization for the existing stage-0 transcript format."""
from dataclasses import asdict
import json
from pathlib import Path

from .entities import Project, Segment, Speaker, Word

SCHEMA_VERSION = 1


def segment_from_dict(data: dict) -> Segment:
    return Segment(**{**data, "words": [Word(**word) for word in data.get("words", [])]})


def project_from_dict(data: dict) -> Project:
    if type(data.get("schema_version")) is not int or data["schema_version"] != SCHEMA_VERSION:
        raise ValueError("UNSUPPORTED_TRANSCRIPT_SCHEMA")
    fields = {key: value for key, value in data.items() if key != "schema_version"}
    fields["speakers"] = [Speaker(**item) for item in data["speakers"]]
    fields["segments"] = [segment_from_dict(item) for item in data["segments"]]
    return Project(**fields)


def project_to_dict(project: Project) -> dict:
    return {"schema_version": SCHEMA_VERSION, **{
        key: value for key, value in asdict(project).items() if value is not None
    }}


def write_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
