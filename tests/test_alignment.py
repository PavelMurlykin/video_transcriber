import sys
from types import SimpleNamespace

from local_transcriber.core.alignment import align


def test_upstream_dropped_sentence_is_restored_and_loaders_are_local(monkeypatch):
    loads = []
    class Processor:
        tokenizer = SimpleNamespace(get_vocab=lambda: {"а": 1})
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            loads.append((path, kwargs))
            return cls()
    class Model:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            loads.append((path, kwargs))
            return cls()
        def to(self, device):
            return self
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(Wav2Vec2Processor=Processor, Wav2Vec2ForCTC=Model))
    monkeypatch.setitem(sys.modules, "nltk", SimpleNamespace(data=SimpleNamespace(path=[], find=lambda _: True)))
    def upstream(*args, **kwargs):
        assert kwargs["interpolate_method"] == "ignore"
        return {"segments": [{"start": 0, "end": 1, "text": "Раз.", "words": []}]}
    monkeypatch.setitem(sys.modules, "whisperx", SimpleNamespace(align=upstream))
    original = {"start": 0, "end": 2, "text": "Раз. 123."}
    result = align({"alignment": "local-model", "nltk_data": "local-nltk", "device": "cuda"}, None, {"segments": [original]})
    assert result["segments"][0]["text"] == original["text"]
    assert result["segments"][0]["alignment_incomplete"]
    assert result["segments"][0]["words"] == []
    assert all(kwargs["local_files_only"] is True for _, kwargs in loads)
