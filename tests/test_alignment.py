import sys
from types import SimpleNamespace

import numpy as np
import pytest

from local_transcriber.config import ConfigurationError
from local_transcriber.core.alignment import align
from local_transcriber.core.speaker_merge import merge


@pytest.fixture
def local_aligner(tmp_path, monkeypatch):
    calls = {"loads": [], "tokenizers": [], "inputs": [], "phrases": []}
    nltk_data = SimpleNamespace(path=["previous"])
    nltk_data.load = lambda resource: calls["tokenizers"].append((resource, nltk_data.path[:]))

    class Processor:
        tokenizer = SimpleNamespace(get_vocab=lambda: dict.fromkeys("абвдежзиклноп рстуфхцчшщыьэюяё", 1))

        @classmethod
        def from_pretrained(cls, path, **kwargs):
            calls["loads"].append((path, kwargs))
            return cls()

    class Model(Processor):
        def to(self, device):
            return self

    def upstream(segments, _model, _metadata, _audio, _device, **kwargs):
        assert kwargs["interpolate_method"] == "ignore"
        calls["inputs"].extend(segments)
        return {"segments": calls["phrases"]}

    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(Wav2Vec2Processor=Processor, Wav2Vec2ForCTC=Model))
    monkeypatch.setitem(sys.modules, "nltk", SimpleNamespace(data=nltk_data))
    monkeypatch.setitem(sys.modules, "whisperx", SimpleNamespace(align=upstream))
    config = {"alignment": str(tmp_path), "nltk_data": str(tmp_path), "device": "cpu"}
    return config, calls, nltk_data


def test_dropped_sentence_preserves_original_bounds_and_keeps_aligned_word(local_aligner):
    config, calls, nltk_data = local_aligner
    calls["phrases"] = [{"text": "Раз.", "words": [{"word": "Раз.", "start": 0.1, "end": 0.8}]}]
    original = {"start": 0, "end": 2, "text": "Раз.  123."}
    result = align(config, np.ones(32000), {"segments": [original]})
    segment = result["segments"][0]
    assert (segment["start"], segment["end"], segment["text"]) == (0, 2, original["text"])
    assert segment["alignment_incomplete"]
    assert [(w["word"], w["start"], w["end"]) for w in segment["words"]] == [
        ("Раз.", 0.1, 0.8), ("123.", None, None),
    ]
    assert calls["inputs"][0]["text"] == "Раз. 123."
    assert calls["loads"] == [(config["alignment"], {"local_files_only": True})] * 2
    assert calls["tokenizers"] == [("tokenizers/punkt_tab/russian.pickle", [config["nltk_data"]])]
    assert nltk_data.path == ["previous"]


def test_unsupported_tokens_stay_null_even_when_whisperx_assigns_wildcards(local_aligner):
    config, calls, _ = local_aligner
    original = {"start": 0, "end": 4, "text": "РФ 123 [не удалось] GPU слово."}
    calls["phrases"] = [{"text": original["text"], "words": [
        {"word": word, "start": i * 0.5, "end": i * 0.5 + 0.4}
        for i, word in enumerate(original["text"].split())
    ]}]
    asr = {"segments": [original]}
    alignment = align(config, np.ones(64000), asr)
    assert calls["inputs"][0]["text"] == "РФ 123 GPU слово."
    result = merge(asr, alignment, [], 4000)["segments"][0]
    assert (result["start_ms"], result["end_ms"], result["text"]) == (0, 4000, original["text"])
    assert result["requires_review"]
    fields = [(w["text"], w["start_ms"], w["end_ms"], w["alignment_missing"]) for w in result["words"]]
    assert fields == [
        ("РФ", 0, 400, False), ("123", None, None, True), ("[не", None, None, True),
        ("удалось]", None, None, True), ("GPU", None, None, True), ("слово.", 2500, 2900, False),
    ]


def test_ambiguous_repeated_word_receives_no_guessed_position(local_aligner):
    config, calls, _ = local_aligner
    calls["phrases"] = [{"text": "да точно", "words": [
        {"word": "да", "start": 0.1, "end": 0.3},
        {"word": "точно", "start": 0.9, "end": 1.4},
    ]}]
    asr = {"segments": [{"start": 0, "end": 2, "text": "да да точно"}]}
    result = align(config, np.ones(32000), asr)["segments"][0]
    assert [word["start"] for word in result["words"]] == [None, None, 0.9]


def test_complete_alignment_keeps_supported_sentence_boundaries(local_aligner):
    config, calls, _ = local_aligner
    calls["phrases"] = [
        {"text": "Раз.", "words": [{"word": "Раз.", "start": 0.1, "end": 0.5}]},
        {"text": "Да.", "words": [{"word": "Да.", "start": 0.8, "end": 1.2}]},
    ]
    segments = align(config, np.ones(32000), {"segments": [{"start": 0, "end": 2, "text": "Раз. Да."}]})["segments"]
    assert [(s["text"], s["start"], s["end"], s["alignment_incomplete"]) for s in segments] == [
        ("Раз.", 0.1, 0.5, False), ("Да.", 0.8, 1.2, False),
    ]


@pytest.mark.parametrize(("start", "end"), [(0.12, 2.01), (float("nan"), 0.7), (0.5001, 0.5002)])
def test_invalid_word_bounds_are_discarded(local_aligner, start, end):
    config, calls, _ = local_aligner
    calls["phrases"] = [{"text": "да", "words": [{"word": "да", "start": start, "end": end}]}]
    asr = {"segments": [{"start": 0, "end": 2, "text": "да"}]}
    word = align(config, np.ones(32000), asr)["segments"][0]["words"][0]
    assert word["start"] is None and word["end"] is None and word["alignment_missing"]


def test_silence_uses_original_interval_without_running_model_inference(local_aligner):
    config, calls, _ = local_aligner
    asr = {"segments": [{"start": 0.2, "end": 1.4, "text": "да"}]}
    result = align(config, np.zeros(32000), asr)["segments"][0]
    assert calls["inputs"] == []
    assert (result["start"], result["end"], result["alignment_incomplete"]) == (0.2, 1.4, True)
    assert result["words"][0]["start"] is None


def test_no_speech_returns_empty_alignment_without_loading_models():
    assert align({}, None, {"segments": []}) == {"segments": []}


def test_russian_model_rejects_non_russian_input(local_aligner):
    config, calls, _ = local_aligner
    asr = {"language": "en", "segments": [{"start": 0, "end": 1, "text": "Speech"}]}
    with pytest.raises(ConfigurationError, match="Russian"):
        align(config, np.ones(16000), asr)
    assert not calls["loads"]
