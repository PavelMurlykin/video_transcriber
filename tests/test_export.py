from dataclasses import replace
import codecs
import json
from zipfile import ZipFile

import pytest

from local_transcriber.cli import main
from local_transcriber.domain.entities import Project, Segment, Speaker
from local_transcriber.domain.errors import ExportError
from local_transcriber.domain.transcript_schema import project_from_dict, project_to_dict
from local_transcriber.export.document import ExportOptions, build_document
from local_transcriber.export.service import WRITERS, export_project
from local_transcriber.storage.editing import EditSession
from local_transcriber.storage.projects import ProjectStore


@pytest.fixture
def project():
    return Project(
        "export-fixture", r"C:\private\Разговор.mp4", "ru", 4500,
        [Speaker("a", "Первый"), Speaker("b", "Вторая")],
        [Segment("s2", 2000, 4000, "b", "Вторая реплика."),
         Segment("s1", 20, 1500, "a", "Первая <фраза> & продолжение.\r\nНовая строка.")],
        ["audio", "asr", "alignment", "diarization", "merge"],
        processing_started_at="2026-11-27T01:00:00+03:00",
    )


def test_chronological_template_and_legacy_date(project):
    document = build_document(project, ExportOptions(precision="milliseconds"))
    assert document.title == "Разговор"
    assert document.metadata == (
        "Дата начала обработки (UTC): 2026-11-26", "Исходный файл: Разговор.mp4", "Длительность: 00:00:04.500",
        "Язык: ru", "Спикеры: Первый, Вторая",
    )
    assert document.phrases == (
        "[00:00:00.020] Первый: Первая <фраза> & продолжение.\nНовая строка.",
        "[00:00:02.000] Вторая: Вторая реплика.",
    )
    legacy = project_to_dict(project)
    del legacy["processing_started_at"]
    hidden = build_document(project_from_dict(legacy), ExportOptions(show_timestamps=False, show_speakers=False, language="en"))
    assert hidden.metadata[0] == "Processing start date (UTC): unknown"
    assert len(hidden.metadata) == 4
    assert hidden.phrases[0].startswith("Первая <фраза>")


def test_txt_cli_reads_edited_snapshot_and_preserves_original(project, tmp_path, capsys):
    store = ProjectStore(tmp_path / "projects.sqlite3")
    store.create(project, status="completed")
    session = EditSession(store, project.project_id)
    session.rename_speaker("a", "Ведущий")
    session.set_segment_text("s1", "Правка\nПродолжение")
    target = tmp_path / "Стенограмма.txt"
    args = ["--project-db", str(store.path), "projects", "export", project.project_id,
            "--output", str(target), "--format", "txt", "--compact"]
    assert main([*args, "--revision", "2"]) == 2
    assert json.loads(capsys.readouterr().err)["error_code"] == "PROJECT_CHANGED"
    assert not target.exists()
    assert main([*args, "--revision", "3"]) == 0
    result = capsys.readouterr()
    assert json.loads(result.out) == {"status": "exported", "format": "txt", "revision": 3}
    payload = target.read_bytes()
    assert not payload.startswith(codecs.BOM_UTF8)
    decoded = payload.decode("utf-8")
    assert "[00:00:00] Ведущий: Правка\r\nПродолжение\r\n[00:00:02] Вторая: Вторая реплика." in decoded
    assert "private" not in decoded
    assert main([*args, "--bom"]) == 2
    assert json.loads(capsys.readouterr().err)["error_code"] == "EXPORT_FILE_EXISTS"
    assert target.read_bytes() == payload
    assert main([*args, "--bom", "--overwrite"]) == 0
    assert target.read_bytes() == codecs.BOM_UTF8 + payload
    assert ProjectStore(store.path).load(project.project_id).revision == 3


def test_failed_renderer_cleans_temporary_file_without_replacing_target(project, tmp_path, monkeypatch):
    target = tmp_path / "export.docx"
    target.write_bytes(b"previous contents")

    def fail(path, _document, _options):
        path.write_bytes(b"partial output")
        raise RuntimeError("synthetic private value")

    monkeypatch.setitem(WRITERS, "docx", fail)
    with pytest.raises(ExportError) as error:
        export_project(project, target, "docx", ExportOptions(), overwrite=True)
    assert error.value.code == "EXPORT_RENDER_FAILED"
    assert "private value" not in str(error.value)
    assert target.read_bytes() == b"previous contents"
    assert list(tmp_path.iterdir()) == [target]


def test_docx_matches_the_shared_template_and_has_page_numbers(project, tmp_path):
    python_docx = pytest.importorskip("docx")
    target = tmp_path / "Стенограмма.docx"
    opts = ExportOptions(precision="milliseconds")
    reference = build_document(project, opts)
    export_project(project, target, "docx", opts)
    loaded = python_docx.Document(target)
    assert [paragraph.text for paragraph in loaded.paragraphs] == [
        reference.title, *reference.metadata, reference.heading, *reference.phrases,
    ]
    assert loaded.core_properties.title == reference.title
    assert loaded.paragraphs[-1].style.name == "Transcript Phrase"
    with ZipFile(target) as archive:
        assert b'w:instr="PAGE"' in archive.read("word/footer1.xml")


def test_pdf_embeds_cyrillic_fonts_and_paginates_long_transcript(project, tmp_path):
    pytest.importorskip("reportlab")
    repeated = [
        replace(project.segments[1], id=f"s{index}", start_ms=index * 1000, end_ms=(index + 1) * 1000,
                text=f"Реплика {index} с кириллицей и символами <>&. " + "длинноеслово" * 24)
        for index in range(110)
    ]
    long_project = replace(project, duration_ms=110_000, segments=repeated)
    target = tmp_path / "Многостраничная стенограмма.pdf"
    export_project(long_project, target, "pdf", ExportOptions())
    data = target.read_bytes()
    assert data.startswith(b"%PDF-") and data.count(b"/Type /Page\n") > 1
    assert b"/FontFile2" in data and b"/ToUnicode" in data
