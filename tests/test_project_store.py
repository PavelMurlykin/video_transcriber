import json
import sqlite3
import subprocess
import sys

import pytest

from local_transcriber.cli import main
from local_transcriber.core import pipeline
from local_transcriber.domain.entities import Project, Segment, Speaker, Word
from local_transcriber.domain.transcript_schema import project_from_dict, project_to_dict
from local_transcriber.storage.editing import EditSession
from local_transcriber.storage.projects import DATABASE_FILENAME, ProjectStore, ProjectStoreError


def sample_project():
    return Project(
        "fixture", "C:/Media/Тест.wav", "ru", 2000, [Speaker("spk_0", "Спикер 1"), Speaker("spk_1", "Спикер 2")],
        [Segment("seg_1", 0, 1000, "spk_0", "Пример",
                 [Word("Пример", 50, 900, "spk_0")])],
        ["audio", "asr", "alignment", "diarization", "merge"],
        original_asr={"segments": [{"text": "Пример"}]},
        original_alignment={"segments": []},
    )


@pytest.fixture
def store(tmp_path):
    result = ProjectStore(tmp_path / DATABASE_FILENAME)
    result.create(sample_project(), status="completed")
    return result


def test_edits_autosave_immediately_and_undo_redo_restore_words(store):
    session = EditSession(store, "fixture")
    session.rename_speaker("spk_0", "  Ведущий ")
    session.set_segment_speaker("seg_1", "spk_1")
    session.set_segment_text("seg_1", "Исправлено")
    saved = ProjectStore(store.path).load("fixture")
    assert saved.project.speakers[0].display_name == "Ведущий"
    assert saved.project.segments[0].text == "Исправлено"
    assert saved.project.segments[0].words == []
    assert saved.project.original_asr == sample_project().original_asr
    session.undo()
    restored = store.load("fixture").project.segments[0]
    assert (restored.text, restored.speaker_id, restored.words[0].speaker_id) == ("Пример", "spk_1", "spk_1")
    session.redo()
    assert store.load("fixture").project.segments[0].text == "Исправлено"


def test_new_edit_clears_redo_and_stale_session_cannot_overwrite(store):
    active = EditSession(store, "fixture")
    concurrent = EditSession(store, "fixture")
    active.rename_speaker("spk_0", "Старое имя")
    active.undo()
    active.rename_speaker("spk_0", "Новое имя")
    with pytest.raises(ProjectStoreError, match="NOTHING_TO_REDO"):
        active.redo()
    with pytest.raises(ProjectStoreError, match="PROJECT_CHANGED"):
        concurrent.set_segment_text("seg_1", "Другая правка")
    assert store.load("fixture").project.speakers[0].display_name == "Новое имя"
    assert store.load("fixture").project.segments[0].text == "Пример"


def test_forced_exit_rolls_back_uncommitted_write(store):
    program = """
import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
db.execute('BEGIN IMMEDIATE')
db.execute("UPDATE projects SET transcript_json = '{}', revision = 99")
os._exit(73)
"""
    result = subprocess.run([sys.executable, "-c", program, str(store.path)], timeout=15)
    assert result.returncode == 73
    recovered = ProjectStore(store.path).load("fixture")
    assert recovered.project == sample_project()
    assert recovered.revision == 1
    assert recovered.status == "completed"


def test_unrelated_database_is_not_changed(tmp_path):
    path = tmp_path / "other.sqlite3"
    db = sqlite3.connect(path)
    try:
        db.execute("CREATE TABLE unrelated (value TEXT)")
        db.execute("INSERT INTO unrelated VALUES ('kept')")
        db.commit()
    finally:
        db.close()
    with pytest.raises(ProjectStoreError, match="NOT_A_PROJECT_DATABASE"):
        ProjectStore(path)
    db = sqlite3.connect(path)
    try:
        assert db.execute("SELECT value FROM unrelated").fetchone() == ("kept",)
        assert db.execute("PRAGMA user_version").fetchone() == (0,)
    finally:
        db.close()


def test_project_cli_reopens_latest_edit_without_model_config(tmp_path, capsys):
    source = tmp_path / "legacy.json"
    source.write_text(json.dumps(project_to_dict(sample_project()), ensure_ascii=False), encoding="utf-8")
    settings = ["--config", str(tmp_path / "missing.json"), "--project-db", str(tmp_path / DATABASE_FILENAME), "projects"]
    assert main([*settings, "import", str(source)]) == 0
    assert main([*settings, "import", str(source)]) == 2
    assert json.loads(capsys.readouterr().err)["error_code"] == "PROJECT_ALREADY_EXISTS"
    commands = tmp_path / "edit.jsonl"
    commands.write_text(json.dumps({"op": "rename_speaker", "speaker_id": "spk_0", "display_name": "Ведущая"}),
                        encoding="utf-8")
    assert main([*settings, "edit", "fixture", "--commands", str(commands)]) == 0
    output = tmp_path / "reopened.json"
    assert main([*settings, "open", "fixture", "--output", str(output)]) == 0
    saved = project_from_dict(json.loads(output.read_text(encoding="utf-8")))
    assert saved.speakers[0].display_name == "Ведущая"
    assert saved.original_asr == sample_project().original_asr
    assert "Ведущая" not in capsys.readouterr().out
    assert main([*settings, "open", "fixture", "--output", str(source)]) == 2
    assert json.loads(capsys.readouterr().err)["error_code"] == "PROJECT_OUTPUT_ALREADY_EXISTS"
    assert project_from_dict(json.loads(source.read_text(encoding="utf-8"))) == sample_project()


def test_pipeline_saves_alignment_and_diarization_before_failed_merge(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    settings = {"device": "cpu", "batch_size": 1, "compute_type": "int8", "manifest": str(manifest)}
    run = tmp_path / "run"
    actual = {
        "asr": {"segments": [{"start": 0, "end": 1, "text": "Пример"}], "language": "ru"},
        "alignment": {"segments": []},
        "diarization": {"turns": [], "exclusive_turns": []},
    }

    def prepare(_source, target, _settings):
        target.write_bytes(b"synthetic audio placeholder")
        return {"duration_ms": 2000, "sample_rate": 16000, "channels": 1}

    def inference(stage, job, _settings, _options):
        snapshot = ProjectStore(tmp_path / DATABASE_FILENAME).load(job.project_id)
        assert snapshot.project.completed_stages[-1] == {"asr": "audio", "alignment": "asr", "diarization": "alignment"}[stage]
        assert snapshot.status == "incomplete"
        (run / f"{stage}.json").write_text(json.dumps(actual[stage]), encoding="utf-8")
        return {"status": "completed", "exit_code": 0, "wall_seconds": 0.01}

    def fail(*_args, **_kwargs):
        raise RuntimeError("synthetic merge failure")

    monkeypatch.setattr(pipeline, "verify_models", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(pipeline, "prepare_audio", prepare)
    monkeypatch.setattr(pipeline, "_run_inference", inference)
    monkeypatch.setattr(pipeline, "merge", fail)
    with pytest.raises(RuntimeError, match="synthetic merge failure"):
        pipeline.run_pipeline(manifest, settings, tmp_path / "source.wav", run)
    metrics = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
    saved = ProjectStore(tmp_path / DATABASE_FILENAME).load(metrics["project_id"])
    assert saved.status == "failed"
    assert saved.project.completed_stages == ["audio", "asr", "alignment", "diarization"]
    assert saved.project.original_diarization == actual["diarization"]
    assert [stage["revision"] for stage in metrics["project_checkpoints"]] == [1, 2, 3, 4]
    assert (run / "audio.wav").is_file()
