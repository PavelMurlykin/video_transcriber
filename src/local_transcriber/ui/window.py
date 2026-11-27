from dataclasses import replace
from pathlib import Path, PureWindowsPath
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from local_transcriber.config import PATH_FIELDS, ConfigurationError
from local_transcriber.domain.entities import TRANSCRIPTION_STAGES
from local_transcriber.domain.timestamps import format_timestamp
from local_transcriber.storage.projects import ProjectStore

from .editor import EDIT_ERRORS, TranscriptEditor
from .export_dialog import ExportDialog
from .process import CliProcess
from .settings import RunRequest, absolute_local


class MainWindow(QMainWindow):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.language = settings.language
        self.system_palette = QApplication.palette()
        self.source = None
        self.has_media = False
        self.task = None
        self.response = {}
        self.last_request = None
        self.job_files = ()
        self.finished_project_id = None
        self.cancel_pending = False
        self.close_pending = False
        self.setWindowTitle("Local Transcriber")
        self.resize(1080, 780)
        self.setAcceptDrops(True)

        self.cli = CliProcess(self)
        self.cli.message.connect(self._process_message)
        self.cli.done.connect(self._process_done)
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.import_page = self._import_page()
        self.processing_page = self._processing_page()
        self.editor = TranscriptEditor(self.t)
        self.editor.export_button.clicked.connect(self._export_project)
        self.settings_page = self._settings_page()
        self.tabs.addTab(self.import_page, self.t("Импорт и проекты", "Import and projects"))
        self.tabs.addTab(self.processing_page, self.t("Обработка", "Processing"))
        self.tabs.addTab(self.editor, self.t("Редактор", "Editor"))
        self.tabs.addTab(self.settings_page, self.t("Настройки", "Settings"))
        self._apply_theme()
        self._refresh_projects()
        self._update_actions()

    def t(self, ru, en):
        return en if self.language == "en" else ru

    def _import_page(self):
        t = self.t
        self.source_label = QLabel(t("Выберите или перетащите локальный медиафайл", "Choose or drop a local media file"))
        self.source_label.setTextFormat(Qt.TextFormat.PlainText)
        self.source_label.setWordWrap(True)
        self.choose = QPushButton(t("Выбрать файл…", "Choose file…"))
        self.choose.clicked.connect(self._choose_source)
        self.duration = QLabel("—")
        self.input_language = QComboBox()
        self.input_language.addItem(t("Русский — полный цикл", "Russian — full pipeline"), "ru")
        self.input_language.addItem(t("Авто — только распознавание", "Auto — recognition only"), "auto")
        self.input_language.addItem(t("Английский — только распознавание", "English — recognition only"), "en")
        self.input_language.currentIndexChanged.connect(self._update_actions)
        self.speakers = QSpinBox()
        self.speakers.setRange(0, 999)
        self.speakers.setSpecialValueText(t("Авто", "Auto"))
        self.speakers.setValue(self.settings.config["num_speakers"] or 0)
        self.profile = QComboBox()
        self.profile.addItem(t("Стандартный", "Standard"), "default")
        self.profile.addItem(t("Экономия памяти", "Low memory"), "memory")
        self.start = QPushButton(t("Начать", "Start"))
        self.start.clicked.connect(self._start)
        self.import_status = QLabel()
        self.import_status.setWordWrap(True)
        self.import_status.setTextFormat(Qt.TextFormat.PlainText)

        import_group = QGroupBox(t("Новая запись", "New recording"))
        form = QFormLayout(import_group)
        form.addRow(self.source_label, self.choose)
        form.addRow(t("Длительность", "Duration"), self.duration)
        form.addRow(t("Язык записи", "Recording language"), self.input_language)
        form.addRow(t("Число спикеров", "Speaker count"), self.speakers)
        form.addRow(t("Профиль распознавания", "Recognition profile"), self.profile)
        form.addRow(self.start)
        form.addRow(self.import_status)

        self.projects = QListWidget()
        self.projects.setAccessibleName(t("Проекты", "Projects"))
        self.projects.itemDoubleClicked.connect(self._open_item)
        self.projects.currentItemChanged.connect(self._update_actions)
        self.open_selected = QPushButton(t("Открыть проект", "Open project"))
        self.open_selected.clicked.connect(lambda: self._open_item(self.projects.currentItem()))
        project_group = QGroupBox(t("Сохранённые проекты", "Saved projects"))
        catalog = QVBoxLayout(project_group)
        catalog.addWidget(self.projects)
        catalog.addWidget(self.open_selected)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(import_group)
        layout.addWidget(project_group, 1)
        return page

    def _processing_page(self):
        t = self.t
        self.job_state = QLabel(t("Нет активной обработки", "No active processing"))
        self.stages = QListWidget()
        self.stages.setAccessibleName(t("Этапы обработки", "Processing stages"))
        self.stage_names = dict(zip(TRANSCRIPTION_STAGES, (
            t("Подготовка аудио", "Audio preparation"), t("Распознавание", "Recognition"),
            t("Выравнивание", "Alignment"), t("Диаризация", "Diarization"), t("Сборка проекта", "Project assembly"),
        )))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(100)
        self.log.setAccessibleName(t("Журнал обработки", "Processing log"))
        self.cancel = QPushButton(t("Отменить", "Cancel"))
        self.cancel.clicked.connect(self._cancel)
        self.retry = QPushButton(t("Повторить", "Retry"))
        self.retry.clicked.connect(lambda: self._launch(self.last_request))
        self.open_result = QPushButton(t("Открыть результат", "Open result"))
        self.open_result.clicked.connect(lambda: self._open_project(self.finished_project_id))
        controls = QHBoxLayout()
        for button in (self.cancel, self.retry, self.open_result):
            controls.addWidget(button)
        controls.addStretch()
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self.job_state)
        layout.addWidget(self.stages, 1)
        layout.addWidget(self.log, 2)
        layout.addLayout(controls)
        return page

    def _settings_page(self):
        t = self.t
        page = QWidget()
        form = QFormLayout(page)
        labels = (
            t("Папка моделей", "Model directory"), "Whisper ASR", "Wav2Vec2", "pyannote",
            "VAD", "NLTK data", t("Манифест моделей", "Model manifest"), "FFmpeg", "ffprobe",
        )
        self.paths = {}
        for key, label in zip(PATH_FIELDS, labels):
            field = QLineEdit(self.settings.config[key])
            self.paths[key] = field
            form.addRow(label, field)
            field.textEdited.connect(self._settings_changed)
        self.results = QLineEdit(str(self.settings.results))
        form.addRow(t("Папка результатов", "Results folder"), self.results)
        self.results.textEdited.connect(self._settings_changed)
        self.device = QComboBox()
        self.device.addItem("GPU (CUDA)", "cuda")
        self.device.addItem("CPU", "cpu")
        self.device.setCurrentIndex(self.device.findData(self.settings.config["device"]))
        self.device.currentIndexChanged.connect(self._settings_changed)
        form.addRow(t("Устройство", "Device"), self.device)
        self.batch = QSpinBox()
        self.batch.setRange(1, max(1024, self.settings.config["batch_size"]))
        self.batch.setValue(self.settings.config["batch_size"])
        self.batch.valueChanged.connect(self._settings_changed)
        form.addRow(t("Размер пакета ASR", "ASR batch size"), self.batch)
        self.theme = QComboBox()
        self.theme.addItem(t("Системная", "System"), "system")
        self.theme.addItem(t("Светлая", "Light"), "light")
        self.theme.addItem(t("Тёмная", "Dark"), "dark")
        self.theme.setCurrentIndex(max(0, self.theme.findData(self.settings.theme)))
        self.theme.currentIndexChanged.connect(self._settings_changed)
        form.addRow(t("Тема", "Theme"), self.theme)
        self.ui_language = QComboBox()
        self.ui_language.addItem("Русский", "ru")
        self.ui_language.addItem("English", "en")
        self.ui_language.setCurrentIndex(max(0, self.ui_language.findData(self.settings.language)))
        self.ui_language.currentIndexChanged.connect(self._settings_changed)
        form.addRow(t("Язык интерфейса (после перезапуска)", "Interface language (after restart)"), self.ui_language)
        self.save_settings = QPushButton(t("Сохранить", "Save"))
        self.save_settings.clicked.connect(self._save_preferences)
        self.verify = QPushButton(t("Проверить локальные файлы", "Verify local files"))
        self.verify.clicked.connect(self._verify)
        form.addRow(self.save_settings, self.verify)
        self.settings_status = QLabel(t("Ресурсы ещё не проверены", "Resources have not been checked"))
        self.settings_status.setWordWrap(True)
        self.settings_status.setTextFormat(Qt.TextFormat.PlainText)
        form.addRow(self.settings_status)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

    def _update_actions(self, *_):
        idle = self.task is None and not self.close_pending
        self.choose.setEnabled(idle)
        self.start.setEnabled(idle and self.has_media)
        self.speakers.setEnabled(self.input_language.currentData() == "ru")
        self.cancel.setEnabled(self.task == "run" and not self.cancel_pending)
        self.retry.setEnabled(idle and self.last_request is not None and self.finished_project_id is None)
        self.open_result.setEnabled(idle and self.finished_project_id is not None)
        self.open_selected.setEnabled(idle and self.projects.currentItem() is not None)
        self.save_settings.setEnabled(idle)
        self.verify.setEnabled(idle)
        self.editor.export_button.setEnabled(idle and self.editor.session is not None)

    def _choose_source(self):
        source, _ = QFileDialog.getOpenFileName(self, self.t("Выбрать запись", "Choose recording"))
        if source:
            self.select_source(source)

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if self.task is None and len(urls) == 1 and urls[0].isLocalFile():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if self.task is None and len(urls) == 1 and urls[0].isLocalFile():
            self.select_source(urls[0].toLocalFile())
            event.acceptProposedAction()

    def select_source(self, path):
        if self.task is not None:
            return
        self.has_media = False
        self.duration.setText("—")
        self.tabs.setCurrentWidget(self.import_page)
        try:
            self.source = absolute_local(path)
            if not self.source.is_file():
                raise ConfigurationError("INPUT_NOT_FILE")
        except EDIT_ERRORS as error:
            self.source_label.setText(self.t("Запись не выбрана", "No recording selected"))
            self.import_status.setText(self._error_hint({"error_code": getattr(error, "code", "INPUT_NOT_FILE")}))
            self._update_actions()
            return
        self.source_label.setText(self.source.name)
        self.import_status.setText(self.t("Чтение метаданных…", "Reading metadata…"))
        self._begin("inspect", ["--config", str(self.settings.active_config), "inspect-media", str(self.source)])

    def _start(self):
        if self.has_media:
            self._launch(RunRequest(self.source, self.input_language.currentData(), self.speakers.value(),
                                    self.profile.currentData()))

    def _launch(self, request):
        if self.task is not None or request is None:
            return
        self.last_request = request
        self.finished_project_id = None
        self.cancel_pending = False
        self.tabs.setCurrentWidget(self.processing_page)
        self.stages.clear()
        self.log.clear()
        try:
            args, *self.job_files = request.prepare(self.settings)
        except EDIT_ERRORS:
            self.job_state.setText(self.t("Папка результатов недоступна", "Results folder is unavailable"))
            self._update_actions()
            return
        names = TRANSCRIPTION_STAGES if request.full_pipeline else TRANSCRIPTION_STAGES[:2]
        self.stage_rows = {stage: row for row, stage in enumerate(names)}
        self.stage_updates = {}
        for stage in names:
            self.stages.addItem(self.stage_names[stage])
            self._stage_state(stage, self.t("ожидание", "waiting"))
        self.job_state.setText(self.t("Проверка локальных моделей…", "Checking local models…"))
        self._begin("run", args)

    def _begin(self, task, arguments):
        self.task = task
        self.response = {}
        self._update_actions()
        self.cli.start(arguments)

    def _process_message(self, payload):
        stage = payload.get("stage")
        if stage is None:
            self.response = payload
        if self.task != "run":
            return
        if stage not in self.stage_rows:
            return
        status = payload.get("status")
        self.stage_updates[stage] = status
        if status == "started":
            self._stage_state(stage, self.t("выполняется", "running"))
            self.job_state.setText(self.stage_names[stage])
        if status == "completed":
            self._stage_state(stage, self.t("готово", "done"))
            seconds = payload.get("wall_seconds")
            if isinstance(seconds, (int, float)):
                self.log.appendPlainText(f"{self.stage_names[stage]} · {seconds:.2f} s")

    def _stage_state(self, stage, state):
        self.stages.item(self.stage_rows[stage]).setText(f"{self.stage_names[stage]} · {state}")

    def _process_done(self, exit_code):
        task, self.task = self.task, None
        if task == "inspect":
            self.has_media = exit_code == 0
            duration = self.response.get("estimated_duration_ms")
            self.duration.setText(format_timestamp(duration) if duration is not None else "—")
            self.import_status.setText("" if self.has_media else self._error_hint(self.response))
        elif task == "verify":
            state = self.t("Локальные ресурсы проверены", "Local resources verified") if exit_code == 0 else self._error_hint(self.response)
            errors = self.response.get("errors", [])
            self.settings_status.setText("\n".join([state, *map(str, errors)]))
        elif task == "run":
            self._finish_run(exit_code)
        elif task == "export":
            self.editor.setEnabled(True)
            success = self.response.get("status") == "exported" and exit_code == 0
            self.editor.status.setText(
                self.t("Стенограмма сохранена", "Transcript saved") if success else self._error_hint(self.response),
            )
        self._update_actions()
        if self.close_pending:
            QTimer.singleShot(0, self.close)

    def _finish_run(self, exit_code):
        for path in self.job_files:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                self.log.appendPlainText(self.t("Не удалось удалить служебный файл.", "A temporary job file could not be removed."))
        self.job_files = ()
        if exit_code == 0 and self.response.get("project_id"):
            self.finished_project_id = self.response["project_id"]
            for stage in self.stage_rows:
                self._stage_state(stage, self.t("готово", "done"))
            self.job_state.setText(self.t("Обработка завершена", "Processing completed"))
        elif exit_code == 130:
            self.job_state.setText(self.t("Обработка отменена", "Processing cancelled"))
        else:
            self.job_state.setText(self.t("Обработка остановилась с ошибкой", "Processing failed"))
            self.log.appendPlainText(self._error_hint(self.response))
        if exit_code != 0:
            for stage, status in self.stage_updates.items():
                if status != "completed":
                    self._stage_state(stage, self.t("отменено", "cancelled") if exit_code == 130 else self.t("ошибка", "failed"))
        self.cancel_pending = False
        self._refresh_projects()

    def _cancel(self):
        if self.task != "run" or self.cancel_pending:
            return
        try:
            self.job_files[1].touch()
        except OSError:
            self.close_pending = False
            self.log.appendPlainText(self.t("Не удалось отправить запрос отмены. Проверьте доступ к папке результатов.",
                                            "Unable to request cancellation. Check access to the results folder."))
            self._update_actions()
            return
        self.cancel_pending = True
        self.job_state.setText(self.t("Отмена…", "Cancelling…"))
        self._update_actions()

    def _refresh_projects(self):
        self.projects.clear()
        try:
            if not self.settings.database.exists():
                return
            rows = ProjectStore(self.settings.database).list_projects()
        except EDIT_ERRORS as error:
            self.import_status.setText(self._error_hint({"error_code": getattr(error, "code", "PROJECT_STORE_ERROR")}))
            return
        statuses = {
            "completed": self.t("Готово", "Ready"), "incomplete": self.t("Не завершено", "Incomplete"),
            "cancelled": self.t("Отменено", "Cancelled"), "failed": self.t("Ошибка", "Failed"),
        }
        for row in rows:
            item = QListWidgetItem(f"{row['source_name']}   ·   {statuses[row['status']]}")
            item.setData(Qt.ItemDataRole.UserRole, row["project_id"])
            self.projects.addItem(item)

    def _open_item(self, item, *_):
        if self.task is None and item:
            self._open_project(item.data(Qt.ItemDataRole.UserRole))

    def _open_project(self, project_id):
        if project_id is None or not self.editor.flush():
            return
        try:
            self.editor.open_project(ProjectStore(self.settings.database), project_id)
        except EDIT_ERRORS as error:
            QMessageBox.warning(self, "Local Transcriber", self._error_hint({"error_code": getattr(error, "code", "PROJECT_STORE_ERROR")}))
            return
        self.tabs.setCurrentWidget(self.editor)
        self._update_actions()

    def _export_project(self):
        if self.task is not None or self.editor.session is None or not self.editor.flush():
            return
        dialog = ExportDialog(self, self.t)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        session = self.editor.session
        file_format = dialog.file_format.currentData()
        default_name = PureWindowsPath(session.saved.project.media_path).stem or "transcript"
        filename, _ = QFileDialog.getSaveFileName(
            self, self.t("Сохранить стенограмму", "Save transcript"),
            str(self.settings.results / f"{default_name}.{file_format}"), f"{file_format.upper()} (*.{file_format})",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not filename:
            return
        suffix = f".{file_format}"
        try:
            target = absolute_local(filename if Path(filename).suffix else filename + suffix)
        except EDIT_ERRORS as error:
            self.editor.status.setText(self._error_hint({"error_code": getattr(error, "code", "EXPORT_WRITE_FAILED")}))
            return
        if target.suffix.lower() != suffix:
            self.editor.status.setText(self._error_hint({"error_code": "INVALID_EXPORT_FORMAT"}))
            return

        options = dialog.arguments(target, self.language)
        if target.exists():
            response = QMessageBox.question(
                self, "Local Transcriber", self.t("Заменить существующий файл?", "Replace the existing file?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
            )
            if response != QMessageBox.StandardButton.Yes:
                return
            options.append("--overwrite")
        self.editor.status.setText(self.t("Экспорт стенограммы…", "Exporting transcript…"))
        self.editor.setEnabled(False)
        self._begin("export", ["--project-db", str(session.store.path), "projects", "export",
                               session.saved.project.project_id, "--revision", str(session.saved.revision), *options])

    def _settings_changed(self, *_):
        self.settings_status.setText(self.t("Есть несохранённые настройки", "Unsaved settings"))

    def _save_preferences(self):
        if self.task is not None:
            return False
        try:
            config = dict(self.settings.config)
            config.update({key: str(absolute_local(field.text().strip())) for key, field in self.paths.items()})
            device = self.device.currentData()
            if device != config["device"]:
                config["compute_type"] = "float16" if device == "cuda" else "int8"
            config.update(device=device, batch_size=self.batch.value())
            results = absolute_local(self.results.text().strip())
            new = replace(self.settings, config=config, results=results, language=self.ui_language.currentData(),
                          theme=self.theme.currentData())
            new.save()
        except EDIT_ERRORS as error:
            self.settings_status.setText(f"{self.t('Проверьте локальные пути и права записи', 'Check local paths and write permissions')} ({type(error).__name__})")
            return False
        changed_results = new.results != self.settings.results
        if changed_results:
            self.finished_project_id = None
        self.settings = new
        self._apply_theme()
        self._refresh_projects()
        self._update_actions()
        self.settings_status.setText(self.t("Сохранено. Ресурсы ещё не проверены.", "Saved. Resources have not been checked."))
        return True

    def _verify(self):
        if self._save_preferences():
            self.settings_status.setText(self.t("Проверка файлов и контрольных сумм…", "Checking files and checksums…"))
            self._begin("verify", ["--config", str(self.settings.preferences), "verify-models"])

    def _apply_theme(self):
        theme = self.settings.theme
        app = QApplication.instance()
        if theme == "system":
            app.setPalette(self.system_palette)
            return
        palette = QPalette()
        if theme == "dark":
            colors = ("#202228", "#16181d", "#f0f1f5", "#2c2f37", "#3d71c8", "#9a9eaa")
        else:
            colors = ("#f3f4f7", "#ffffff", "#171921", "#eaecf1", "#2e5fb2", "#646a77")
        window, base, text, button, highlight, disabled = map(QColor, colors)
        roles = QPalette.ColorRole
        for role, color in (
            (roles.Window, window), (roles.Base, base), (roles.AlternateBase, button), (roles.WindowText, text),
            (roles.Text, text), (roles.ButtonText, text), (roles.Button, button), (roles.Highlight, highlight),
            (roles.HighlightedText, QColor("white")), (roles.PlaceholderText, disabled),
        ):
            palette.setColor(role, color)
        for role in (roles.WindowText, roles.Text, roles.ButtonText):
            palette.setColor(QPalette.ColorGroup.Disabled, role, disabled)
        app.setPalette(palette)

    def _error_hint(self, payload):
        code = payload.get("error_code") or payload.get("error_type")
        t = self.t
        hints = {
            "INPUT_NOT_FOUND": t("Проверьте путь к записи.", "Check the recording path."),
            "INPUT_NOT_FILE": t("Выберите локальный аудио- или видеофайл.", "Choose a local audio or video file."),
            "INPUT_NOT_LOCAL": t("Выберите запись на локальном диске.", "Choose a recording on a local drive."),
            "INPUT_UNREADABLE": t("Проверьте права на чтение записи.", "Check read access to the recording."),
            "PROJECT_PATH_NOT_LOCAL": t("Выберите путь на локальном диске.", "Choose a path on a local drive."),
            "INVALID_MEDIA": t("Файл не удалось прочитать. Проверьте целостность и формат.",
                               "The file could not be read. Check its integrity and format."),
            "NO_AUDIO_STREAM": t("В файле нет аудиодорожки.", "The file has no audio track."),
            "MEDIA_TOOL_UNAVAILABLE": t("Проверьте пути к FFmpeg и ffprobe.", "Check the FFmpeg and ffprobe paths."),
            "INSUFFICIENT_DISK_SPACE": t("Освободите место или выберите другой диск.", "Free some space or select another drive."),
            "ASR_GPU_OUT_OF_MEMORY": t("Не хватило памяти. Выберите профиль экономии памяти или уменьшите размер пакета.",
                                   "Insufficient memory. Use the low-memory profile or reduce the batch size."),
            "INVALID_CONFIG": t("Проверьте настройки моделей и устройства.", "Check model and device settings."),
            "PROJECT_STORE_ERROR": t("Проверьте доступ к базе проектов.", "Check access to the project database."),
            "PROJECT_CHANGED": t("Проект изменился в другой сессии. Откройте его заново.",
                                 "The project changed in another session. Reopen it."),
            "EXPORT_FILE_EXISTS": t("Выберите другое имя или подтвердите замену.",
                                    "Choose a different name or confirm replacement."),
            "EXPORT_WRITE_FAILED": t("Проверьте права на папку и закройте файл в других приложениях.",
                                      "Check folder access and close the file in other apps."),
            "INVALID_EXPORT_FORMAT": t("Расширение файла должно соответствовать выбранному формату.",
                                        "Use the file extension for the selected format."),
            "EXPORT_DEPENDENCIES_MISSING": t("Установите зависимости из requirements-export.lock.",
                                             "Install the packages from requirements-export.lock."),
            "PDF_UNSUPPORTED_CHARACTER": t("В тексте есть символы вне шрифта PDF. Выберите TXT или DOCX.",
                                           "The PDF font lacks some characters. Use TXT or DOCX."),
            "PDF_FONT_MISSING": t("Восстановите шрифты DejaVu Sans из проекта.",
                                  "Restore the bundled DejaVu Sans fonts."),
        }
        hint = hints.get(code, payload.get("hint") or t("Проверьте настройки, локальные файлы и папку результатов.",
                                                       "Check settings, local files, and the results folder."))
        return f"{hint} ({code})" if code else hint

    def closeEvent(self, event):
        if not self.close_pending and not self.editor.flush():
            discard = QMessageBox.question(
                self, "Local Transcriber",
                self.t("Закрыть окно и потерять несохранённый текст?", "Close the window and discard the unsaved text?"),
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if discard != QMessageBox.StandardButton.Discard:
                event.ignore()
                return
        if self.task is None:
            self.editor.player.stop()
            event.accept()
            return
        self.close_pending = True
        if self.task == "run":
            self._cancel()
        self._update_actions()
        event.ignore()
