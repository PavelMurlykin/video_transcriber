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


def test_millisecond_rounding_does_not_publish_zero_duration_words():
    source = {"segments": [{"start": 0, "end": 2, "text": "Раз", "words": [
        {"word": "Раз", "start": 0.5001, "end": 0.5002}
    ]}]}
    segment = merge(source, source, [], 2000)["segments"][0]
    assert (segment["start_ms"], segment["end_ms"]) == (0, 2000)
    assert segment["requires_review"]
    word = segment["words"][0]
    assert word["start_ms"] is None and word["end_ms"] is None and word["alignment_missing"]


def test_exclusive_track_resolves_boundary_with_raw_solo_evidence_and_retains_overlap():
    source = {"segments": [{"start": 0, "end": 1, "text": "Пример",
                            "words": [{"word": "Пример", "start": 0, "end": 1}]}]}
    raw = [{"start": 0, "end": 0.65, "speaker": "A"}, {"start": 0.35, "end": 1, "speaker": "B"}]
    exclusive = [{"start": 0, "end": 0.6, "speaker": "A"}, {"start": 0.6, "end": 1, "speaker": "B"}]
    result = merge(source, source, raw, 1000, exclusive_turns=exclusive)
    word = result["segments"][0]["words"][0]
    assert word["speaker_id"] == "spk_0"
    assert "overlapping_speech" in word["review_reasons"]
    assert result["overlap_regions"] == [{"start_ms": 350, "end_ms": 650, "speaker_ids": ["spk_0", "spk_1"]}]
    assert [row["speaker_id"] for row in result["exclusive_diarization_turns"]] == ["spk_0", "spk_1"]


def test_exclusive_track_cannot_hide_entirely_overlapping_voices():
    source = {"segments": [{"start": 0, "end": 1, "text": "Да",
                            "words": [{"word": "Да", "start": 0, "end": 1}]}]}
    raw = [{"start": 0, "end": 1, "speaker": "A"}, {"start": 0, "end": 1, "speaker": "B"}]
    result = merge(source, source, raw, 1000, exclusive_turns=raw[:1])
    word = result["segments"][0]["words"][0]
    assert word["speaker_id"] == "unknown"
    assert set(word["review_reasons"]) >= {"overlapping_speech", "speaker_unknown"}


def test_conflicting_supported_tracks_leave_word_unknown():
    source = {"segments": [{"start": 0, "end": 1, "text": "Да",
                            "words": [{"word": "Да", "start": 0, "end": 1}]}]}
    raw = [{"start": 0, "end": 0.88, "speaker": "A"}, {"start": 0.24, "end": 1, "speaker": "B"}]
    exclusive = [{"start": 0, "end": 0.25, "speaker": "A"}, {"start": 0.25, "end": 1, "speaker": "B"}]
    result = merge(source, source, raw, 1000, exclusive_turns=exclusive)
    assert result["segments"][0]["words"][0]["speaker_id"] == "unknown"


def test_duplicate_turns_cannot_overstate_word_coverage():
    source = {"segments": [{"start": 0, "end": 1, "text": "Да",
                            "words": [{"word": "Да", "start": 0, "end": 1}]}]}
    under_half = {"start": 0, "end": 0.4, "speaker": "A"}
    result = merge(source, source, [under_half, under_half], 1000)
    assert result["segments"][0]["speaker_id"] == "unknown"
    assert result["overlap_regions"] == []


def test_partial_phrase_splits_confirmed_speakers_without_attributing_missing_word():
    source = {"segments": [{"start": 0, "end": 2, "text": "Первый 123 Второй", "alignment_incomplete": True,
                            "words": [{"word": "Первый", "start": 0.1, "end": 0.9},
                                      {"word": "123", "start": None, "end": None},
                                      {"word": "Второй", "start": 1.1, "end": 1.9}]}]}
    turns = [{"start": 0, "end": 1, "speaker": "A"}, {"start": 1, "end": 2, "speaker": "B"}]
    segments = merge(source, source, turns, 2000)["segments"]
    assert [segment["speaker_id"] for segment in segments] == ["spk_0", "unknown", "spk_1"]
    assert " ".join(segment["text"] for segment in segments) == "Первый 123 Второй"
    assert (segments[1]["start_ms"], segments[1]["end_ms"]) == (900, 1100)
    assert segments[1]["words"][0]["start_ms"] is None
    assert all(segment["requires_review"] for segment in segments)


def test_overlap_between_words_is_preserved_in_segment_and_project():
    source = {"segments": [{"start": 0, "end": 2, "text": "Раз два", "words": [
        {"word": "Раз", "start": 0.1, "end": 0.5}, {"word": "два", "start": 1.2, "end": 1.8},
    ]}]}
    turns = [{"start": 0.7, "end": 1, "speaker": "B"}, {"start": 0, "end": 2, "speaker": "A"}]
    result = merge(source, source, turns, 2000)
    assert [word["speaker_id"] for word in result["segments"][0]["words"]] == ["spk_0", "spk_0"]
    assert "overlapping_speech" in result["segments"][0]["review_reasons"]
    assert result["overlap_regions"] == [{"start_ms": 700, "end_ms": 1000, "speaker_ids": ["spk_0", "spk_1"]}]
