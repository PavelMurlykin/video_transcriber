from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import time
import wave

import pytest

from local_transcriber.ui.__main__ import configure_media_environment

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
configure_media_environment()
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QMimeData, QPointF, QTimer, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtMultimedia import QAudioBufferOutput, QMediaDevices, QMediaPlayer
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog

from local_transcriber.config import PATH_FIELDS
from local_transcriber.domain.entities import Project, Segment, Speaker
from local_transcriber.domain.transcript_schema import write_json
from local_transcriber.storage.projects import ProjectStore
from local_transcriber.ui.export_dialog import ExportDialog
from local_transcriber.ui.settings import Settings
from local_transcriber.ui.window import MainWindow


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    base = tmp_path / "config.json"
    config = {key: str(tmp_path / key) for key in PATH_FIELDS}
    tools = Path(".tools/ffmpeg-install.json")
    if tools.exists():
        media = json.loads(tools.read_text(encoding="utf-8-sig"))
        config.update({key: media[key] for key in ("ffmpeg", "ffprobe")})
    base.write_text(json.dumps(config), encoding="utf-8")
    widget = MainWindow(Settings.load(base, tmp_path / "config.ui.local.json"))
    yield app, widget
    widget.close()
    app.processEvents()


def wait_for(app, condition, seconds=5):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert condition()


def test_editor_autosaves_on_timer_and_reopens_project(window, tmp_path):
    app, widget = window
    store = ProjectStore(widget.settings.database)
    project = Project("fixture", str(tmp_path / "missing.wav"), "ru", 2000,
                      [Speaker("spk_1", "Speaker")], [Segment("s1", 0, 1000, "spk_1", "Тест")], ["merge"])
    store.create(project, status="completed")
    widget._refresh_projects()
    widget.projects.setCurrentRow(0)
    widget.open_selected.click()
    widget.editor.text.setPlainText("Исправленный текст")
    widget.tabs.setCurrentWidget(widget.settings_page)
    wait_for(app, lambda: store.load("fixture").revision == 2)
    widget._open_project("fixture")
    assert widget.editor.text.toPlainText() == "Исправленный текст"
    assert widget.tabs.currentWidget() is widget.editor


def test_media_probe_leaves_tabs_responsive(window, tmp_path):
    if not Path(".tools/ffmpeg-install.json").exists():
        pytest.skip("local FFmpeg not prepared")
    app, widget = window
    source = tmp_path / "Импорт записи.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * 16000)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source))])
    drag = QDragEnterEvent(QPointF(20, 20), Qt.DropAction.CopyAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    drop = QDropEvent(QPointF(20, 20), Qt.DropAction.CopyAction, mime,
                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, drag)
    assert drag.isAccepted()
    QApplication.sendEvent(widget, drop)
    assert drop.isAccepted()
    assert widget.task == "inspect"
    widget.tabs.setCurrentWidget(widget.settings_page)
    wait_for(app, lambda: widget.task is None)
    assert widget.tabs.currentWidget() is widget.settings_page
    assert widget.duration.text() == "00:00:01.000" and widget.start.isEnabled()


def test_editor_controls_update_saved_segments(window, tmp_path, monkeypatch):
    _, widget = window
    store = ProjectStore(widget.settings.database)
    project = Project(
        "fixture", str(tmp_path / "missing.wav"), "ru", 2000,
        [Speaker("a", "First"), Speaker("b", "Second")],
        [Segment("s1", 0, 1000, "a", "Одна фраза"), Segment("s2", 1000, 2000, "a", "Другая фраза")], ["merge"],
    )
    store.create(project, status="completed")
    widget._open_project("fixture")
    editor = widget.editor
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Ведущий", True))
    editor.rename.click()
    assert [editor.table.item(row, 2).text() for row in range(2)] == ["Ведущий", "Ведущий"]
    editor.search.setText("Другая")
    assert editor.current_id == "s2" and editor.table.rowCount() == 1
    editor.speaker.setCurrentIndex(editor.speaker.findData("b"))
    editor.speaker.activated.emit(editor.speaker.currentIndex())
    assert store.load("fixture").project.segments[1].speaker_id == "b"
    editor.undo.click()
    assert store.load("fixture").project.segments[1].speaker_id == "a"
    editor.redo.click()
    assert store.load("fixture").project.segments[1].speaker_id == "b"
    editor.end_ms.setValue(1900)
    editor.bounds.click()
    assert store.load("fixture").project.segments[1].end_ms == 1900


def test_settings_form_persists_device_batch_theme_and_results(window, tmp_path):
    _, widget = window
    directory = tmp_path / "Новые результаты"
    widget.device.setCurrentIndex(widget.device.findData("cpu"))
    widget.batch.setValue(7)
    widget.theme.setCurrentIndex(widget.theme.findData("dark"))
    widget.ui_language.setCurrentIndex(widget.ui_language.findData("en"))
    widget.results.setText(str(directory))
    widget.save_settings.click()
    saved = Settings.load(widget.settings.base_config, widget.settings.preferences)
    assert saved.results == directory and directory.is_dir()
    assert (saved.config["device"], saved.config["compute_type"], saved.config["batch_size"]) == ("cpu", "int8", 7)
    assert (saved.theme, saved.language) == ("dark", "en")


def test_startup_failure_explains_missing_dependencies(window):
    app, widget = window
    widget.check_startup()
    assert widget.task == "startup"
    wait_for(app, lambda: widget.task is None)
    assert widget.response["error_code"] == "RUNTIME_CHECK_FAILED"
    assert "MISSING:manifest" in widget.runtime_status.text()
    assert widget.choose.isEnabled()


def test_export_uses_current_edit_and_chosen_txt_path(window, tmp_path, monkeypatch):
    app, widget = window
    store = ProjectStore(widget.settings.database)
    project = Project(
        "fixture", str(tmp_path / "Синтетическая запись.wav"), "ru", 2000,
        [Speaker("a", "Ведущий")], [Segment("s1", 20, 1000, "a", "Черновик")], ["merge"],
    )
    store.create(project, status="completed")
    widget._open_project(project.project_id)
    widget.editor.text.setPlainText("Проверка экспорта")

    def choose_options(dialog):
        dialog.file_format.setCurrentIndex(dialog.file_format.findData("pdf"))
        assert not dialog.bom.isEnabled()
        dialog.file_format.setCurrentIndex(dialog.file_format.findData("txt"))
        dialog.bom.setChecked(True)
        dialog.precision.setCurrentIndex(dialog.precision.findData("milliseconds"))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ExportDialog, "exec", choose_options)
    name = tmp_path / "Стенограмма"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(name), ""))
    widget.editor.export_button.click()
    assert widget.task == "export"
    wait_for(app, lambda: widget.task is None)
    assert widget.response == {"status": "exported", "format": "txt", "revision": 2}
    target = name.with_suffix(".txt")
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")
    assert "[00:00:00.020] Ведущий: Проверка экспорта" in target.read_text(encoding="utf-8-sig")
    assert widget.editor.export_button.isEnabled()


def check_playback(app, editor, *, video_expected):
    player = editor.player
    buffers, frames = [], []
    receiver = QAudioBufferOutput(player)
    player.setAudioBufferOutput(receiver)

    def receive_buffer(buffer):
        if buffer.isValid() and buffer.frameCount() > 0:
            buffers.append(buffer.frameCount())

    def receive_frame(frame):
        if frame.isValid():
            frames.append(frame.size())

    receiver.audioBufferReceived.connect(receive_buffer)
    sink = editor.video.videoSink()
    sink.videoFrameChanged.connect(receive_frame)
    try:
        wait_for(app, lambda: player.isSeekable() and player.duration() > 3000, seconds=10)
        assert player.hasAudio() and player.hasVideo() == video_expected
        segment = next(s for s in editor.session.saved.project.segments if s.end_ms - s.start_ms > 300)
        row = next(row for row in range(editor.table.rowCount())
                   if editor.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == segment.id)
        editor.table.cellClicked.emit(row, 1)
        wait_for(app, lambda: abs(player.position() - segment.end_ms) < 100)
        editor.seek.setValue(segment.start_ms + 100)
        wait_for(app, lambda: segment.id in editor.playing_ids)
        editor.rate.setCurrentIndex(editor.rate.findData(1.25))
        assert player.playbackRate() == pytest.approx(1.25)
        position = player.position()
        editor.play.click()
        wait_for(app, lambda: player.position() > position and buffers and (frames or not video_expected), seconds=10)
        editor.play.click()
        wait_for(app, lambda: player.playbackState() == QMediaPlayer.PlaybackState.PausedState)
        assert player.error() == QMediaPlayer.Error.NoError
        return {
            "duration_ms": player.duration(),
            "audio_frames": sum(buffers),
            "video_frames": len(frames),
            "audio_device_available": not QMediaDevices.defaultAudioOutput().isNull(),
        }
    finally:
        player.stop()
        sink.videoFrameChanged.disconnect(receive_frame)
        player.setAudioBufferOutput(None)
        receiver.deleteLater()


@pytest.mark.integration
def test_full_desktop_run_in_windows_appcontainer(capfd, monkeypatch):
    if "LOCAL_TRANSCRIBER_UI_ACCEPTANCE" not in os.environ:
        pytest.skip("Set LOCAL_TRANSCRIBER_UI_ACCEPTANCE to a new private artifacts directory")
    from scripts.verify_offline import probe_network, windows_network_isolation
    from ctypes import windll
    from docx import Document
    from psutil import Process, Error

    output = Path(os.environ["LOCAL_TRANSCRIBER_UI_ACCEPTANCE"]).resolve()
    output.mkdir(parents=True, exist_ok=False)
    isolation = windows_network_isolation()
    probes = probe_network()
    verified = isolation["verified"] and all(probe["blocked"] for probe in probes)
    admin = bool(windll.shell32.IsUserAnAdmin())
    write_json(output / "network.json", {"verified": verified, "administrator": admin,
                                        "os_isolation": isolation, "unguarded_probes": probes})
    assert verified and not admin

    mp4, mp3 = (next(Path("sample").glob(f"*.{extension}")).resolve() for extension in ("mp4", "mp3"))
    source_dir = output / "Media_Запись"
    source_dir.mkdir()
    source = source_dir / "Sample_Кириллица.mp4"
    shutil.copyfile(mp4, source)
    settings = Settings.load(Path("config.local.json").resolve(), output / "desktop.local.json")
    settings = replace(settings, results=output)
    settings.save()
    token_canary = "synthetic-unused-hub-token"
    monkeypatch.setenv("HF_TOKEN", token_canary)
    monkeypatch.setenv("HF_TOKEN_PATH", str(output / "synthetic-token"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow(settings)
    child_env = window.cli.process.processEnvironment()
    assert not child_env.contains("HF_TOKEN") and not child_env.contains("HF_TOKEN_PATH")
    window.show()
    timer = QTimer(window)
    timer.setInterval(50)
    ticks = []
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    reopened = None
    try:
        startup_started = time.perf_counter()
        window.check_startup()
        wait_for(app, lambda: window.task is None, seconds=75)
        startup_seconds = time.perf_counter() - startup_started
        assert window.response.get("status") == "completed"
        window.select_source(str(source))
        wait_for(app, lambda: window.start.isEnabled())
        window.speakers.setValue(2)
        window.start.click()
        wait_for(app, lambda: window.stage_updates.get("asr") == "started", seconds=90)
        requested = time.perf_counter()
        window.cancel.click()
        wait_for(app, lambda: window.task is None, seconds=30)
        cancellation_seconds = time.perf_counter() - requested
        assert window.response.get("status") == "cancelled" and window.retry.isEnabled()
        store = ProjectStore(settings.database)
        cancelled, = store.list_projects()
        assert cancelled["status"] == "cancelled" and cancelled["last_stage"] == "audio"

        window.retry.click()
        wait_for(app, lambda: window.stage_updates.get("asr") == "started", seconds=90)
        worker = None

        def find_worker():
            nonlocal worker
            try:
                for process in Process(window.cli.process.processId()).children(recursive=True):
                    if ("local_transcriber.workers.transcription_worker" in process.cmdline()
                            and not process.children()):
                        worker = process
                        return True
            except Error:
                pass
            return False

        wait_for(app, find_worker, seconds=15)
        worker.kill()
        wait_for(app, lambda: window.task is None, seconds=30)
        assert window.response.get("error_code") == "INFERENCE_STAGE_FAILED"
        failed, = [item for item in store.list_projects() if item["status"] == "failed"]
        assert failed["last_stage"] == "audio" and window.retry.isEnabled()
        window._open_project(failed["project_id"])
        assert window.editor.session.saved.project.completed_stages == ["audio"]

        launched = time.perf_counter()
        timer.start()
        window.retry.click()
        wait_for(app, lambda: window.stage_updates.get("asr") == "started", seconds=90)
        window.tabs.setCurrentWidget(window.settings_page)
        wait_for(app, lambda: len(ticks) >= 5)
        assert window.task == "run" and window.tabs.currentWidget() is window.settings_page
        wait_for(app, lambda: window.task is None, seconds=240)
        timer.stop()
        elapsed = time.perf_counter() - launched
        max_gap = max(right - left for left, right in zip(ticks, ticks[1:]))
        assert max_gap < 1.0
        assert window.open_result.isEnabled() and all(status == "completed" for status in window.stage_updates.values())
        assert len(window.stage_updates) == 5
        assert len(list(output.glob("desktop-*/metrics.json"))) == 3
        window.open_result.click()
        assert window.tabs.currentWidget() is window.editor
        project = window.editor.session.saved.project
        assert len(project.speakers) == 2 and project.segments and project.overlap_regions
        started_at = datetime.fromisoformat(project.processing_started_at)
        assert started_at.tzinfo is not None and started_at <= datetime.now(timezone.utc)
        video = check_playback(app, window.editor, video_expected=True)

        window.editor.text.setPlainText("Синтетическая правка для проверки")
        edited_id = window.editor.current_id
        window.close()
        reopened = MainWindow(Settings.load(settings.base_config, settings.preferences))
        assert reopened.settings.database == settings.database
        reopened.show()
        reopened._open_project(project.project_id)
        edited = next(segment for segment in reopened.editor.session.saved.project.segments if segment.id == edited_id)
        assert edited.text == "Синтетическая правка для проверки"
        assert reopened.task is None
        export_sizes = {}
        for extension in ("txt", "docx", "pdf"):
            destination = output / f"transcript.{extension}"

            def configure_dialog(dialog):
                dialog.file_format.setCurrentIndex(dialog.file_format.findData(extension))
                return QDialog.DialogCode.Accepted

            with monkeypatch.context() as scoped:
                scoped.setattr(ExportDialog, "exec", configure_dialog)
                scoped.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(destination), ""))
                reopened.editor.export_button.click()
            wait_for(app, lambda: reopened.task is None)
            assert reopened.response.get("status") == "exported"
            export_sizes[extension] = destination.stat().st_size
            assert export_sizes[extension] > 0
        assert edited.text in (output / "transcript.txt").read_text(encoding="utf-8")
        assert any(edited.text in p.text for p in Document(output / "transcript.docx").paragraphs)
        assert (output / "transcript.pdf").read_bytes().startswith(b"%PDF-")
        audio_project = replace(project, project_id="audio-player-check", media_path=str(mp3))
        store.create(audio_project, status="completed")
        reopened._open_project(audio_project.project_id)
        audio = check_playback(app, reopened.editor, video_expected=False)

        captured = capfd.readouterr()
        log = captured.out + captured.err + window.log.toPlainText()
        for run_metrics in output.glob("desktop-*/metrics.json"):
            log += run_metrics.read_text(encoding="utf-8")
        assert not any(value in log for value in ("Input #0", source.name, edited.text, token_canary))
        write_json(output / "desktop-metrics.json", {
            "qt_platform": app.platformName(),
            "startup_seconds": startup_seconds,
            "cancel_seconds": cancellation_seconds, "ui_full_run_seconds": elapsed,
            "worker_crash_recovered": True, "administrator": admin, "exports_bytes": export_sizes,
            "ui_timer_ticks": len(ticks), "ui_timer_max_gap_seconds": max_gap,
            "speakers": len(project.speakers), "segments": len(project.segments),
            "overlap_regions": len(project.overlap_regions), "mp4": video, "mp3": audio,
        })
    finally:
        timer.stop()
        window.close()
        if reopened is not None:
            reopened.close()
        if window.task is not None:
            wait_for(app, lambda: window.task is None, seconds=30)
        app.processEvents()
