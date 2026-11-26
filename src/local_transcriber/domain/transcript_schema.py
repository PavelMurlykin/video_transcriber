"""Serialization for the existing stage-0 transcript format."""
from dataclasses import asdict

from .entities import Project, Segment, Speaker, Word

SCHEMA_VERSION = 1


def project_from_dict(data: dict) -> Project:
    if type(data.get("schema_version")) is not int or data["schema_version"] != SCHEMA_VERSION:
        raise ValueError("UNSUPPORTED_TRANSCRIPT_SCHEMA")
    fields = {key: value for key, value in data.items() if key != "schema_version"}
    fields["speakers"] = [Speaker(**item) for item in data["speakers"]]
    fields["segments"] = [
        Segment(**{**item, "words": [Word(**word) for word in item.get("words", [])]})
        for item in data["segments"]
    ]
    return Project(**fields)


def project_to_dict(project: Project) -> dict:
    return {"schema_version": SCHEMA_VERSION, **{
        key: value for key, value in asdict(project).items() if value is not None
    }}
