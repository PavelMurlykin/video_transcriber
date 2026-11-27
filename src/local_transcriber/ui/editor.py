from pathlib import Path
import sqlite3

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QBrush, QKeySequence, QPalette, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QSlider, QSpinBox, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from local_transcriber.storage.editing import EditSession
from local_transcriber.storage.projects import ProjectStoreError

from .settings import absolute_local

EDIT_ERRORS = (OSError, ValueError, ProjectStoreError, sqlite3.Error)


def timestamp(milliseconds: int) -> str:
    seconds, milliseconds = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"


class TranscriptEditor(QWidget):
    def __init__(self, localize):
        super().__init__()
        self.t = localize
        self.session = None
        self.current_id = None
        self.loading = False
        self.playing_ids = set()
        t = self.t

        self.search = QLineEdit()
        self.search.setPlaceholderText(t("Поиск по тексту и спикерам", "Search phrases and speakers"))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            t("Начало", "Start"), t("Конец", "End"), t("Спикер", "Speaker"),
            t("Проверка", "Review"), t("Фраза", "Phrase"),
        ])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.currentCellChanged.connect(self._selection_changed)
        self.table.cellClicked.connect(self._seek_to_timestamp)
        self.search.textChanged.connect(self._filter)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.text = QPlainTextEdit()
        self.text.setAccessibleName(t("Текст фразы", "Phrase text"))
        self.text.setMinimumHeight(82)
        self.speaker = QComboBox()
        self.speaker.setAccessibleName(t("Спикер", "Speaker"))
        self.start_ms = QSpinBox()
        self.end_ms = QSpinBox()
        self.start_ms.setAccessibleName(t("Начало фразы", "Phrase start"))
        self.end_ms.setAccessibleName(t("Конец фразы", "Phrase end"))
        self.start_ms.setSuffix(" ms")
        self.end_ms.setSuffix(" ms")
        self.start_ms.setKeyboardTracking(False)
        self.end_ms.setKeyboardTracking(False)
        self.bounds = QPushButton(t("Сохранить интервал", "Save interval"))
        self.bounds.clicked.connect(self._set_bounds)
        self.rename = QPushButton(t("Переименовать спикера", "Rename speaker"))
        self.rename.clicked.connect(self._rename)
        self.split = QPushButton(t("Разделить…", "Split…"))
        self.split.clicked.connect(self._split)
        self.merge = QPushButton(t("Объединить со следующей", "Merge with next"))
        self.merge.clicked.connect(lambda: self._edit(self.session.merge_with_next, self.current_id))
        self.undo = QPushButton(t("Отменить правку", "Undo edit"))
        self.redo = QPushButton(t("Повторить правку", "Redo edit"))
        self.undo.clicked.connect(lambda: self._edit(self.session.undo))
        self.redo.clicked.connect(lambda: self._edit(self.session.redo))
        for keys, button in (("Ctrl+Alt+Z", self.undo), ("Ctrl+Alt+Y", self.redo)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(button.click)

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(300)
        self.save_timer.timeout.connect(self.flush)
        self.text.textChanged.connect(self._queue_save)
        self.speaker.activated.connect(self._set_speaker)

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.video = QVideoWidget()
        self.video.setMinimumHeight(120)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(lambda duration: self.seek.setMaximum(duration))
        self.player.playbackStateChanged.connect(self._playback_state)
        self.player.errorOccurred.connect(self._media_error)
        self.player.hasVideoChanged.connect(self.video.setVisible)
        self.video.hide()
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.setAccessibleName(t("Позиция воспроизведения", "Playback position"))
        self.seek.valueChanged.connect(self._seek)
        self.clock = QLabel(timestamp(0))
        self.play = QPushButton(t("Воспроизвести", "Play"))
        self.play.clicked.connect(self._toggle_play)
        self.rate = QComboBox()
        self.rate.setAccessibleName(t("Скорость воспроизведения", "Playback speed"))
        for rate in (0.75, 1, 1.25, 1.5):
            self.rate.addItem(f"{rate}×", rate)
        self.rate.setCurrentIndex(1)
        self.rate.currentIndexChanged.connect(lambda _: self.player.setPlaybackRate(self.rate.currentData()))
        self.media_status = QLabel()
        playback = QHBoxLayout()
        for widget in (self.play, self.seek, self.clock, self.rate):
            playback.addWidget(widget, 1 if widget is self.seek else 0)

        timing = QHBoxLayout()
        for widget in (QLabel(t("Начало", "Start")), self.start_ms, QLabel(t("Конец", "End")),
                       self.end_ms, self.bounds, self.speaker, self.rename):
            timing.addWidget(widget)
        actions = QHBoxLayout()
        for widget in (self.split, self.merge, self.undo, self.redo):
            actions.addWidget(widget)
        actions.addStretch()
        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.addLayout(timing)
        details_layout.addWidget(self.text)
        details_layout.addLayout(actions)
        details_layout.addWidget(self.status)
        workspace = QSplitter(Qt.Orientation.Vertical)
        workspace.addWidget(self.table)
        workspace.addWidget(details)
        workspace.setStretchFactor(0, 1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.video)
        layout.addLayout(playback)
        layout.addWidget(self.media_status)
        layout.addWidget(self.search)
        layout.addWidget(workspace, 1)
        self._populate_editor(None)
        self.play.setEnabled(False)

    def open_project(self, store, project_id: str) -> None:
        session = EditSession(store, project_id)
        self.player.stop()
        self.session = session
        self.current_id = None
        self.playing_ids.clear()
        self.status.setText(self.t("Проект открыт", "Project opened"))
        self.media_status.clear()
        self._render()
        try:
            source = absolute_local(session.saved.project.media_path)
        except EDIT_ERRORS:
            source = None
        playable = source is not None and source.is_file()
        self.play.setEnabled(playable)
        self.player.setSource(QUrl.fromLocalFile(str(source)) if playable else QUrl())
        if not playable:
            self.media_status.setText(self.t("Исходная запись недоступна. Правки можно сохранять.",
                                             "Source media is unavailable. Editing remains available."))

    def _filter(self):
        if self.flush():
            self._render()

    def _render(self):
        if self.session is None:
            return
        project = self.session.saved.project
        speakers = {speaker.id: speaker.display_name for speaker in project.speakers}
        query = self.search.text().strip().casefold()
        segments = [segment for segment in project.segments
                    if query in segment.text.casefold() or query in speakers.get(segment.speaker_id, "").casefold()]
        self.loading = True
        try:
            self.table.setRowCount(len(segments))
            selected = -1
            for row, segment in enumerate(segments):
                speaker = speakers.get(segment.speaker_id, self.t("Не определён", "Unknown"))
                review = self.t("Проверить", "Check") if segment.requires_review else ""
                values = (timestamp(segment.start_ms), timestamp(segment.end_ms), speaker, review, segment.text)
                for column, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if column == 0:
                        cell.setData(Qt.ItemDataRole.UserRole, segment.id)
                    if column == 3 and segment.requires_review:
                        cell.setToolTip(self._review_hint(segment.review_reasons))
                    self.table.setItem(row, column, cell)
                if segment.id == self.current_id:
                    selected = row
            if selected < 0 and segments:
                selected = 0
            self.table.setCurrentCell(selected, 0)
            self.playing_ids.clear()
            self._populate_editor(segments[selected] if selected >= 0 else None)
        finally:
            self.loading = False
        self._highlight(self.player.position())

    def _review_hint(self, reasons):
        labels = {
            "alignment_missing": self.t("Нет таймкода слова", "Missing word timestamp"),
            "alignment_pending": self.t("Выравнивание ещё не выполнено", "Alignment pending"),
            "alignment_incomplete": self.t("Неполное выравнивание", "Incomplete alignment"),
            "overlapping_speech": self.t("Перекрытие речи", "Overlapping speech"),
            "speaker_unknown": self.t("Спикер не определён", "Unknown speaker"),
            "text_edited": self.t("Текст исправлен вручную", "Text edited"),
        }
        return "\n".join(labels.get(reason, reason) for reason in reasons)

    def _segment(self, segment_id):
        return next((segment for segment in self.session.saved.project.segments if segment.id == segment_id), None)

    def _selection_changed(self, row, _column, previous_row, _previous_column):
        if self.loading or self.session is None:
            return
        if not self.flush():
            self.loading = True
            self.table.setCurrentCell(previous_row, 0)
            self.loading = False
            return
        cell = self.table.item(row, 0)
        self._populate_editor(self._segment(cell.data(Qt.ItemDataRole.UserRole)) if cell else None)

    def _populate_editor(self, segment):
        was_loading = self.loading
        self.loading = True
        try:
            self.current_id = segment.id if segment else None
            self.text.setPlainText(segment.text if segment else "")
            self.speaker.clear()
            self.speaker.addItem(self.t("Не определён", "Unknown"), "unknown")
            if self.session:
                project = self.session.saved.project
                for speaker in project.speakers:
                    self.speaker.addItem(speaker.display_name, speaker.id)
                for widget, bound in [(self.start_ms, "start_ms"), (self.end_ms, "end_ms")]:
                    widget.setRange(0, project.duration_ms)
                    widget.setValue(getattr(segment, bound, 0))
            self.speaker.setCurrentIndex(max(0, self.speaker.findData(segment.speaker_id)) if segment else 0)
            for widget in (self.text, self.speaker, self.start_ms, self.end_ms, self.bounds, self.split, self.merge):
                widget.setEnabled(segment is not None)
            self.rename.setEnabled(segment is not None and segment.speaker_id != "unknown")
            self._history_buttons()
        finally:
            self.loading = was_loading

    def _queue_save(self):
        if not self.loading and self.current_id is not None:
            self.save_timer.start()

    def flush(self) -> bool:
        self.save_timer.stop()
        if self.current_id is None:
            return True
        text = self.text.toPlainText()
        segment = self._segment(self.current_id)
        if text == segment.text:
            return True
        try:
            self.session.set_segment_text(self.current_id, text)
        except EDIT_ERRORS as error:
            self._edit_error(error)
            return False
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == self.current_id:
                self.table.item(row, 4).setText(text)
                review = self.table.item(row, 3)
                review.setText(self.t("Проверить", "Check"))
                review.setToolTip(self._review_hint(self._segment(self.current_id).review_reasons))
                break
        self._saved()
        return True

    def _history_buttons(self):
        self.undo.setEnabled(self.session is not None and self.session.can_undo)
        self.redo.setEnabled(self.session is not None and self.session.can_redo)

    def _saved(self):
        self.status.setText(self.t("Сохранено", "Saved"))
        self._history_buttons()

    def _edit_error(self, error):
        code = getattr(error, "code", type(error).__name__)
        hints = {
            "PROJECT_CHANGED": self.t("Проект изменился в другой сессии. Скопируйте несохранённый текст, прежде чем закрыть редактор.",
                                      "The project changed in another session. Copy any unsaved text before closing the editor."),
            "INVALID_SEGMENT_INTERVAL": self.t("Начало должно предшествовать концу в пределах записи.",
                                                "The start must precede the end within the recording."),
            "NO_NEXT_SEGMENT": self.t("После выбранной фразы нет другой.", "There is no phrase after the selected one."),
            "INVALID_SEGMENT_SPLIT": self.t("Укажите момент и границу слова внутри выбранной фразы.",
                                             "Choose a time and word boundary inside the selected phrase."),
        }
        hint = hints.get(code, self.t("Проверьте правку и доступ к папке результатов.",
                                       "Check the edit and access to the results folder."))
        self.status.setText(f"{hint} ({code})")

    def _edit(self, operation, *args):
        if not self.flush():
            return
        try:
            operation(*args)
        except EDIT_ERRORS as error:
            self._edit_error(error)
            return
        self._render()
        self._saved()

    def _set_speaker(self):
        self._edit(self.session.set_segment_speaker, self.current_id, self.speaker.currentData())

    def _set_bounds(self):
        self._edit(self.session.set_segment_bounds, self.current_id, self.start_ms.value(), self.end_ms.value())

    def _rename(self):
        speaker_id = self.speaker.currentData()
        text, ok = QInputDialog.getText(self, self.rename.text(), self.t("Имя", "Name"),
                                        text=self.speaker.currentText())
        if ok:
            self._edit(self.session.rename_speaker, speaker_id, text)

    def _split(self):
        if not self.flush():
            return
        segment = self._segment(self.current_id)
        maximum = len(segment.text.split()) - 1
        if maximum < 1 or segment.end_ms - segment.start_ms < 2:
            self._edit_error(ProjectStoreError("INVALID_SEGMENT_SPLIT"))
            return
        word, ok = QInputDialog.getInt(self, self.split.text(), self.t("Разделить после слова №", "Split after word #"),
                                       max(1, maximum // 2), 1, maximum)
        if not ok:
            return
        suggestion = segment.words[word - 1].end_ms if len(segment.words) == maximum + 1 else None
        if suggestion is None or not segment.start_ms < suggestion < segment.end_ms:
            suggestion = (segment.start_ms + segment.end_ms) // 2
        time, ok = QInputDialog.getInt(self, self.split.text(), self.t("Момент разделения (мс)", "Split time (ms)"),
                                       suggestion, segment.start_ms + 1, segment.end_ms - 1)
        if ok:
            self._edit(self.session.split_segment, self.current_id, time, word)

    def _toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _playback_state(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play.setText(self.t("Пауза", "Pause") if playing else self.t("Воспроизвести", "Play"))

    def _media_error(self, error, _description=""):
        self.media_status.setText(f"{self.t('Ошибка воспроизведения', 'Playback error')} ({error.name})")

    def _seek(self, position):
        if self.player.isSeekable():
            self.player.setPosition(position)

    def _seek_to_timestamp(self, row, column):
        if column in (0, 1):
            segment = self._segment(self.table.item(row, 0).data(Qt.ItemDataRole.UserRole))
            self._seek(segment.end_ms if column == 1 else segment.start_ms)

    def _position_changed(self, position):
        self.seek.blockSignals(True)
        self.seek.setValue(position)
        self.seek.blockSignals(False)
        self.clock.setText(timestamp(position))
        self._highlight(position)

    def _highlight(self, position):
        if self.session is None:
            return
        active = {segment.id for segment in self.session.saved.project.segments
                  if segment.start_ms <= position < segment.end_ms}
        changed = active ^ self.playing_ids
        self.playing_ids = active
        if not changed:
            return
        palette = self.palette()
        for row in range(self.table.rowCount()):
            segment_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if segment_id in changed:
                for column in range(self.table.columnCount()):
                    item = self.table.item(row, column)
                    item.setBackground(palette.brush(QPalette.ColorRole.Highlight) if segment_id in active else QBrush())
                    item.setForeground(palette.brush(QPalette.ColorRole.HighlightedText) if segment_id in active else QBrush())
