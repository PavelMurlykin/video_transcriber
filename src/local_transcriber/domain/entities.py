from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from uuid import uuid4


@dataclass
class Speaker:
    id: str
    display_name: str


@dataclass
class Word:
    text: str
    start_ms: int | None
    end_ms: int | None
    speaker_id: str
    alignment_missing: bool = False
    review_reasons: list[str] = field(default_factory=list)


@dataclass
class Segment:
    id: str
    start_ms: int
    end_ms: int
    speaker_id: str
    text: str
    words: list[Word] = field(default_factory=list)
    requires_review: bool = False
    review_reasons: list[str] = field(default_factory=list)


@dataclass
class Project:
    project_id: str
    media_path: str
    language: str
    duration_ms: int
    speakers: list[Speaker]
    segments: list[Segment]
    completed_stages: list[str]
    sample_rate: int | None = None
    channels: int | None = None
    diarization_turns: list[dict] | None = None
    original_asr: dict | None = None
    original_alignment: dict | None = None
    models_manifest_sha256: str | None = None
    exclusive_diarization_turns: list[dict] | None = None
    overlap_regions: list[dict] | None = None
    original_diarization: dict | None = None


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TRANSCRIPTION_STAGES = ("audio", "asr", "alignment", "diarization", "merge")


@dataclass
class TranscriptionJob:
    media_path: Path
    run_dir: Path
    project_id: str = field(default_factory=lambda: str(uuid4()))
    stages: dict[str, StageStatus] = field(
        default_factory=lambda: dict.fromkeys(TRANSCRIPTION_STAGES, StageStatus.PENDING)
    )

    @contextmanager
    def stage(self, name: str):
        self.stages[name] = StageStatus.RUNNING
        try:
            yield
        except KeyboardInterrupt:
            self.stages[name] = StageStatus.CANCELLED
            raise
        except Exception:
            self.stages[name] = StageStatus.FAILED
            raise
        else:
            self.stages[name] = StageStatus.COMPLETED

    @property
    def completed_stages(self) -> list[str]:
        return [name for name, status in self.stages.items() if status == StageStatus.COMPLETED]
