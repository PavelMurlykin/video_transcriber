from copy import deepcopy

from local_transcriber.core.speaker_merge import merge


def test_two_speakers_inside_phrase_split_by_words():
    source = {"segments": [{"start": 0, "end": 2, "text": "Привет. Да!", "words": [
        {"word": "Привет.", "start": 0.1, "end": 0.8}, {"word": "Да!", "start": 1.1, "end": 1.8}]}]}
    original = deepcopy(source)
    turns = [{"start": 1, "end": 2, "speaker": "B"}, {"start": 0, "end": 1, "speaker": "A"}]
    result = merge(source, source, turns, 2000)
    assert [s["speaker_id"] for s in result["segments"]] == ["spk_0", "spk_1"]
    assert [s["display_name"] for s in result["speakers"]] == ["Спикер 1", "Спикер 2"]
    assert source == original


def test_missing_alignment_preserves_text_and_has_no_fabricated_timestamps():
    source = {"segments": [{"start": 0, "end": 2, "text": "Счёт 123.", "words": [
        {"word": "Счёт", "start": 0.1, "end": 0.8}, {"word": "123."}]}]}
    result = merge(source, source, [], 2000)["segments"][0]
    assert result["text"] == "Счёт 123."
    assert result["requires_review"]
    assert result["words"][1]["start_ms"] is None
    assert result["words"][1]["speaker_id"] == "unknown"


def test_overlap_is_preserved_and_equal_overlap_is_unknown():
    source = {"segments": [{"start": 0, "end": 2, "text": "Да", "words": [{"word": "Да", "start": 0.5, "end": 1}]}]}
    turns = [{"start": 0, "end": 2, "speaker": "A"}, {"start": 0, "end": 2, "speaker": "B"}]
    result = merge(source, source, turns, 2000)
    assert len(result["diarization_turns"]) == 2
    assert result["segments"][0]["speaker_id"] == "unknown"
    assert "overlapping_speech" in result["segments"][0]["review_reasons"]


def test_incomplete_word_list_does_not_lose_source_text():
    source = {"segments": [{"start": 0, "end": 2, "text": "Раз два", "words": [{"word": "Раз", "start": 0.1, "end": 0.8}]}]}
    result = merge(source, source, [], 2000)["segments"][0]
    assert result["text"] == "Раз два"
    assert "alignment_incomplete" in result["review_reasons"]


def test_nan_word_times_are_marked_missing():
    source = {"segments": [{"start": 0, "end": 2, "text": "Раз", "words": [{"word": "Раз", "start": float("nan"), "end": 1}]}]}
    assert merge(source, source, [], 2000)["segments"][0]["words"][0]["alignment_missing"]
