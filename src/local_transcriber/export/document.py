from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PureWindowsPath

from local_transcriber.domain.entities import Project
from local_transcriber.domain.errors import ExportError
from local_transcriber.domain.timestamps import format_timestamp

LANGUAGES = ("ru", "en")
PRECISIONS = ("seconds", "milliseconds")


@dataclass(frozen=True)
class ExportOptions:
    show_timestamps: bool = True
    precision: str = "seconds"
    show_speakers: bool = True
    separate_phrases: bool = True
    bom: bool = False
    language: str = "ru"


@dataclass(frozen=True)
class ExportDocument:
    title: str
    metadata: tuple[str, ...]
    heading: str
    phrases: tuple[str, ...]


def build_document(project: Project, options: ExportOptions) -> ExportDocument:
    if options.language not in LANGUAGES or options.precision not in PRECISIONS:
        raise ExportError("INVALID_EXPORT_OPTIONS", "Check the document language and timestamp precision.")
    ru = options.language == "ru"
    source = PureWindowsPath(project.media_path)
    title = source.stem or ("Запись" if ru else "Recording")
    unavailable = "неизвестно" if ru else "unknown"
    labels = (
        ("Дата начала обработки (UTC)", "Исходный файл", "Длительность", "Язык", "Спикеры")
        if ru else ("Processing start date (UTC)", "Source file", "Duration", "Language", "Speakers")
    )
    values = (
        _utc_date(project.processing_started_at) or unavailable,
        source.name or unavailable, format_timestamp(project.duration_ms), project.language,
    )
    metadata = [f"{label}: {value}" for label, value in zip(labels, values)]
    speakers = {speaker.id: speaker.display_name for speaker in project.speakers}
    unknown = "Не определён" if ru else "Unknown"
    if options.show_speakers:
        names = list(speakers.values())
        if any(segment.speaker_id not in speakers for segment in project.segments):
            names.append(unknown)
        if names:
            metadata.append(f"{labels[4]}: {', '.join(dict.fromkeys(names))}")

    phrases = []
    for segment in sorted(project.segments, key=lambda value: value.start_ms):
        text = segment.text.replace("\r\n", "\n").replace("\r", "\n")
        if options.show_speakers:
            text = f"{speakers.get(segment.speaker_id, unknown)}: {text}"
        if options.show_timestamps:
            stamp = format_timestamp(segment.start_ms, show_milliseconds=options.precision == "milliseconds")
            text = f"[{stamp}] {text}"
        phrases.append(text)

    return ExportDocument(title, tuple(metadata), "Стенограмма" if ru else "Transcript", tuple(phrases))


def _utc_date(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        started = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    return started.astimezone(timezone.utc).date().isoformat() if started.tzinfo is not None else None
