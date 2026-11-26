"""Reconcile the local Wav2Vec2 alignment with the original ASR text."""

from pathlib import Path
import re

from local_transcriber.config import ConfigurationError

from .media import SAMPLE_RATE
from .speaker_merge import interval

MIN_SAMPLES = 400
ANNOTATION = re.compile(r"\[[^\]]*\]|<[^>]*>")
TOKEN = re.compile(r"\S+")


def _embedding(source: list[str], returned: list[dict], *, reverse: bool = False) -> list[int]:
    """Find the earliest or latest ordered placement of the returned words."""
    indices = range(len(source) - 1, -1, -1) if reverse else range(len(source))
    candidates = iter(indices)
    positions = []
    for word in reversed(returned) if reverse else returned:
        index = next((i for i in candidates if source[i] == word.get("word")), None)
        if index is None:
            return []
        positions.append(index)
    return positions[::-1] if reverse else positions


def _reconcile(original: dict, phrases: list[dict], vocabulary: dict) -> list[dict]:
    tokens = list(TOKEN.finditer(original["text"]))
    expected = [token.group() for token in tokens]
    returned = [word for phrase in phrases for word in phrase.get("words", [])]
    left = _embedding(expected, returned)
    right = _embedding(expected, returned, reverse=True)
    # A dropped repetition can leave several possible positions for a returned word.
    unique = {i: word for i, j, word in zip(left, right, returned) if i == j}
    annotations = [match.span() for match in ANNOTATION.finditer(original["text"])]
    previous_end_ms = round(original["start"] * 1000)
    words = []
    for index, token in enumerate(tokens):
        text = token.group()
        lexical = [char.lower() for char in text if char.isalnum()]
        supported = lexical and all(char in vocabulary for char in lexical)
        annotated = any(start < token.end() and token.start() < end for start, end in annotations)
        candidate = unique.get(index, {})
        bounds = interval(candidate)
        word = {"word": text, "start": None, "end": None, "alignment_missing": True}
        if supported and not annotated and bounds and original["start"] <= bounds[0] < bounds[1] <= original["end"]:
            start_ms, end_ms = (round(value * 1000) for value in bounds)
            if previous_end_ms <= start_ms < end_ms:
                word.update(start=bounds[0], end=bounds[1], alignment_missing=False)
                previous_end_ms = end_ms
        words.append(word)

    incomplete = not words or any(word["alignment_missing"] for word in words)
    if incomplete:
        return [{**original, "words": words, "alignment_incomplete": True}]

    # Keep WhisperX's sentence boundaries when the complete words agree with them.
    if not all(
        phrase.get("words") and phrase["text"].split() == [word["word"] for word in phrase["words"]]
        for phrase in phrases
    ):
        return [{**original, "words": words, "alignment_incomplete": False}]
    result = []
    offset = 0
    for phrase in phrases:
        end = offset + len(phrase["words"])
        group = words[offset:end]
        result.append({**original, "text": phrase["text"], "start": group[0]["start"],
                       "end": group[-1]["end"], "words": group, "alignment_incomplete": False})
        offset = end
    return result


def align(config: dict, audio, asr: dict) -> dict:
    originals = asr["segments"]
    if not originals:
        return {"segments": []}
    if asr.get("language", "ru") != "ru":
        raise ConfigurationError("word alignment requires Russian ASR output")

    model_dir = Path(config["alignment"])
    nltk_dir = Path(config["nltk_data"])
    if any(not path.is_absolute() or str(path).startswith(("\\\\", "//")) or not path.is_dir()
           for path in (model_dir, nltk_dir)):
        raise ConfigurationError("alignment and tokenizer resources need absolute local directories")

    import nltk
    import whisperx
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

    previous_nltk_paths = nltk.data.path[:]
    nltk.data.path[:] = [str(nltk_dir)]
    processor = model = None
    try:
        # Resolve exactly the resource WhisperX needs before it can try its downloader.
        nltk.data.load("tokenizers/punkt_tab/russian.pickle")
        processor = Wav2Vec2Processor.from_pretrained(str(model_dir), local_files_only=True)
        model = Wav2Vec2ForCTC.from_pretrained(str(model_dir), local_files_only=True).to(config["device"])
        vocabulary = {char.lower(): index for char, index in processor.tokenizer.get_vocab().items()}
        metadata = {"language": "ru", "dictionary": vocabulary, "type": "huggingface"}
        segments = []
        duration = len(audio) / SAMPLE_RATE
        for original in originals:
            bounds = interval(original)
            if not original["text"].strip() or not bounds or bounds[0] >= duration:
                continue
            source = {**original, "end": min(bounds[1], duration)}
            start = int(source["start"] * SAMPLE_RATE)
            end = int(source["end"] * SAMPLE_RATE)
            phrases = []
            model_text = " ".join(ANNOTATION.sub(" ", source["text"]).split())
            if model_text and end - start >= MIN_SAMPLES and audio[start:end].any():
                normalized = {**source, "text": model_text}
                result = whisperx.align(
                    [normalized], model, metadata, audio, config["device"],
                    interpolate_method="ignore", return_char_alignments=False, print_progress=False,
                )
                phrases = result["segments"]
            segments.extend(_reconcile(source, phrases, vocabulary))
        return {"segments": segments}
    finally:
        del model, processor
        nltk.data.path[:] = previous_nltk_paths
