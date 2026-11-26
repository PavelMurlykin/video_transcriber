import json

import pytest

from local_transcriber.domain.entities import StageStatus, TranscriptionJob, Word
from local_transcriber.domain.transcript_schema import project_from_dict, project_to_dict


def stage_zero_data():
    return {
        "schema_version": 1,
        "project_id": "sample-project",
        "media_path": "C:/Media/demo.mp4",
        "language": "ru",
        "duration_ms": 2000,
        "sample_rate": 16000,
        "channels": 1,
        "speakers": [{"id": "spk_0", "display_name": "Спикер 1"}],
        "segments": [{
            "id": "seg_1", "start_ms": 0, "end_ms": 1500, "speaker_id": "spk_0", "text": "Пример",
            "words": [{"text": "Пример", "start_ms": None, "end_ms": None, "speaker_id": "unknown",
                       "alignment_missing": True, "review_reasons": ["alignment_missing"]}],
            "requires_review": True, "review_reasons": ["alignment_incomplete"],
        }],
        "original_asr": {"segments": [{"text": "Пример"}]},
        "original_alignment": {"segments": []},
        "diarization_turns": [{"start": 0, "end": 1.5, "speaker": "SPEAKER_00", "speaker_id": "spk_0"}],
        "completed_stages": ["audio", "asr", "alignment", "diarization", "merge"],
        "models_manifest_sha256": "example",
    }


def test_stage_zero_json_round_trip_and_edit_is_separate_from_inference():
    data = stage_zero_data()
    project = project_from_dict(json.loads(json.dumps(data, ensure_ascii=False)))
    assert isinstance(project.segments[0].words[0], Word)
    assert project_to_dict(project) == data
    project.segments[0].text = "Исправление"
    assert project_to_dict(project)["original_asr"] == data["original_asr"]


def test_schema_rejects_unrecognized_version():
    data = stage_zero_data()
    data["schema_version"] = 99
    with pytest.raises(ValueError, match="UNSUPPORTED_TRANSCRIPT_SCHEMA"):
        project_from_dict(data)


def test_job_tracks_completed_failed_and_cancelled_stages(tmp_path):
    job = TranscriptionJob(tmp_path / "input.mp4", tmp_path / "run")
    with job.stage("audio"):
        assert job.stages["audio"] == StageStatus.RUNNING
    with pytest.raises(RuntimeError), job.stage("asr"):
        raise RuntimeError("synthetic failure")
    with pytest.raises(KeyboardInterrupt), job.stage("alignment"):
        raise KeyboardInterrupt
    assert job.completed_stages == ["audio"]
    assert job.stages["asr"] == StageStatus.FAILED
    assert job.stages["alignment"] == StageStatus.CANCELLED
    assert job.stages["diarization"] == StageStatus.PENDING
