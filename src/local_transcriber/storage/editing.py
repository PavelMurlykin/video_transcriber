"""Persist each accepted edit while keeping undo/redo stacks for the session."""

from dataclasses import dataclass, replace

from local_transcriber.domain.entities import Segment, Speaker

from .projects import ProjectStore, ProjectStoreError


@dataclass(frozen=True)
class Edit:
    collection: str
    index: int
    before: Segment | Speaker
    after: Segment | Speaker


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
        self._record(Edit("speakers", index, speaker, replace(speaker, display_name=display_name.strip())))

    def set_segment_speaker(self, segment_id: str, speaker_id: str) -> None:
        if speaker_id != "unknown":
            self._find("speakers", speaker_id)
        index, segment = self._find("segments", segment_id)
        if segment.speaker_id != speaker_id:
            edited = replace(segment, speaker_id=speaker_id,
                             words=[replace(word, speaker_id=speaker_id) for word in segment.words])
            self._record(Edit("segments", index, segment, edited))

    def set_segment_text(self, segment_id: str, text: str) -> None:
        if not isinstance(text, str):
            raise ProjectStoreError("INVALID_SEGMENT_TEXT")
        index, segment = self._find("segments", segment_id)
        if segment.text != text:
            edited = replace(segment, text=text, words=[], requires_review=True,
                             review_reasons=sorted({*segment.review_reasons, "text_edited"}))
            self._record(Edit("segments", index, segment, edited))

    def undo(self) -> None:
        if not self._undo:
            raise ProjectStoreError("NOTHING_TO_UNDO")
        edit = self._undo[-1]
        self._apply(edit, edit.before)
        self._redo.append(self._undo.pop())

    def redo(self) -> None:
        if not self._redo:
            raise ProjectStoreError("NOTHING_TO_REDO")
        edit = self._redo[-1]
        self._apply(edit, edit.after)
        self._undo.append(self._redo.pop())

    def _find(self, collection: str, item_id: str):
        for index, item in enumerate(getattr(self.saved.project, collection)):
            if item.id == item_id:
                return index, item
        raise ProjectStoreError("SPEAKER_NOT_FOUND" if collection == "speakers" else "SEGMENT_NOT_FOUND")

    def _record(self, edit: Edit) -> None:
        if edit.before == edit.after:
            return
        self._apply(edit, edit.after)
        self._undo.append(edit)
        self._redo.clear()

    def _apply(self, edit: Edit, item: Segment | Speaker) -> None:
        items = list(getattr(self.saved.project, edit.collection))
        items[edit.index] = item
        project = replace(self.saved.project, **{edit.collection: items})
        revision = self.store.save(project, status=self.saved.status, revision=self.saved.revision)
        self.saved = replace(self.saved, project=project, revision=revision)
