"""Persist each accepted edit while keeping undo/redo stacks for the session."""

from dataclasses import dataclass, replace
from uuid import uuid4

from local_transcriber.domain.entities import Segment, Speaker

from .projects import ProjectStore, ProjectStoreError


@dataclass(frozen=True)
class Edit:
    collection: str
    index: int
    before: tuple[Segment | Speaker, ...]
    after: tuple[Segment | Speaker, ...]


class EditSession:
    def __init__(self, store: ProjectStore, project_id: str):
        self.store = store
        self.saved = store.load(project_id)
        self._undo: list[Edit] = []
        self._redo: list[Edit] = []

    def rename_speaker(self, speaker_id: str, display_name: str) -> None:
        if not isinstance(display_name, str) or not display_name.strip():
            raise ProjectStoreError("INVALID_SPEAKER_NAME")
        index, speaker = self._find("speakers", speaker_id)
        edited = replace(speaker, display_name=display_name.strip())
        self._record(Edit("speakers", index, (speaker,), (edited,)))

    def set_segment_speaker(self, segment_id: str, speaker_id: str) -> None:
        if speaker_id != "unknown":
            self._find("speakers", speaker_id)
        index, segment = self._find("segments", segment_id)
        if segment.speaker_id != speaker_id:
            edited = replace(segment, speaker_id=speaker_id,
                             words=[replace(word, speaker_id=speaker_id) for word in segment.words])
            self._record(Edit("segments", index, (segment,), (edited,)))

    def set_segment_text(self, segment_id: str, text: str) -> None:
        if not isinstance(text, str):
            raise ProjectStoreError("INVALID_SEGMENT_TEXT")
        index, segment = self._find("segments", segment_id)
        if segment.text != text:
            edited = replace(segment, text=text, words=[], requires_review=True,
                             review_reasons=sorted({*segment.review_reasons, "text_edited"}))
            self._record(Edit("segments", index, (segment,), (edited,)))

    def set_segment_bounds(self, segment_id: str, start_ms: int, end_ms: int) -> None:
        self._validate_bounds(start_ms, end_ms)
        index, segment = self._find("segments", segment_id)
        edited = _with_bounds(segment, start_ms, end_ms)
        self._record(Edit("segments", index, (segment,), (edited,)))

    def split_segment(self, segment_id: str, at_ms: int, after_word: int) -> None:
        index, segment = self._find("segments", segment_id)
        tokens = segment.text.split()
        if not segment.start_ms < at_ms < segment.end_ms or not 1 <= after_word < len(tokens):
            raise ProjectStoreError("INVALID_SEGMENT_SPLIT")
        word_tokens = [word.text for word in segment.words]
        words = segment.words if word_tokens == tokens else []
        left = replace(segment, text=" ".join(tokens[:after_word]), words=words[:after_word])
        right = replace(segment, id=f"seg_{uuid4().hex}", text=" ".join(tokens[after_word:]), words=words[after_word:])
        self._record(Edit("segments", index, (segment,), (
            _with_bounds(left, segment.start_ms, at_ms),
            _with_bounds(right, at_ms, segment.end_ms),
        )))

    def merge_with_next(self, segment_id: str) -> None:
        index, segment = self._find("segments", segment_id)
        others = self.saved.project.segments
        if index + 1 >= len(others):
            raise ProjectStoreError("NO_NEXT_SEGMENT")
        following = others[index + 1]
        speaker = segment.speaker_id if segment.speaker_id == following.speaker_id else "unknown"
        reasons = set(segment.review_reasons + following.review_reasons)
        if speaker == "unknown":
            reasons.add("speaker_unknown")
        combined = replace(
            segment, start_ms=min(segment.start_ms, following.start_ms), end_ms=max(segment.end_ms, following.end_ms),
            text=" ".join((segment.text, following.text)).strip(), speaker_id=speaker,
            words=segment.words + following.words, requires_review=bool(reasons),
            review_reasons=sorted(reasons),
        )
        self._record(Edit("segments", index, (segment, following), (combined,)))

    def undo(self) -> None:
        if not self._undo:
            raise ProjectStoreError("NOTHING_TO_UNDO")
        edit = self._undo[-1]
        self._apply(edit, remove=len(edit.after), insert=edit.before)
        self._redo.append(self._undo.pop())

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def redo(self) -> None:
        if not self._redo:
            raise ProjectStoreError("NOTHING_TO_REDO")
        edit = self._redo[-1]
        self._apply(edit, remove=len(edit.before), insert=edit.after)
        self._undo.append(self._redo.pop())

    def _find(self, collection: str, item_id: str):
        for index, item in enumerate(getattr(self.saved.project, collection)):
            if item.id == item_id:
                return index, item
        raise ProjectStoreError("SPEAKER_NOT_FOUND" if collection == "speakers" else "SEGMENT_NOT_FOUND")

    def _validate_bounds(self, start_ms: int, end_ms: int) -> None:
        if not 0 <= start_ms < end_ms <= self.saved.project.duration_ms:
            raise ProjectStoreError("INVALID_SEGMENT_INTERVAL")

    def _record(self, edit: Edit) -> None:
        if edit.before == edit.after:
            return
        self._apply(edit, remove=len(edit.before), insert=edit.after)
        self._undo.append(edit)
        self._redo.clear()

    def _apply(self, edit: Edit, *, remove: int, insert: tuple[Segment | Speaker, ...]) -> None:
        items = list(getattr(self.saved.project, edit.collection))
        items[edit.index:edit.index + remove] = insert
        project = replace(self.saved.project, **{edit.collection: items})
        revision = self.store.save(project, status=self.saved.status, revision=self.saved.revision)
        self.saved = replace(self.saved, project=project, revision=revision)


def _with_bounds(segment: Segment, start_ms: int, end_ms: int) -> Segment:
    words = []
    reasons = set(segment.review_reasons)
    for word in segment.words:
        if word.start_ms is not None and word.end_ms is not None and not start_ms <= word.start_ms < word.end_ms <= end_ms:
            word = replace(word, start_ms=None, end_ms=None, alignment_missing=True,
                           review_reasons=sorted({*word.review_reasons, "alignment_missing"}))
            reasons.add("alignment_incomplete")
        words.append(word)
    return replace(segment, start_ms=start_ms, end_ms=end_ms, words=words,
                   requires_review=segment.requires_review or bool(reasons), review_reasons=sorted(reasons))
