"""Small, deterministic stage-0 merge; raw outputs remain in the project JSON."""
import math


def interval(item: dict):
    start, end = item.get("start"), item.get("end")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        return None
    return start, end


def assign(start: float, end: float, turns: list[dict], mapping: dict) -> tuple[str, list[str]]:
    overlap_by_speaker = {}
    active = []
    for turn in turns:
        left, right = max(start, turn["start"]), min(end, turn["end"])
        if right > left:
            speaker = mapping[turn["speaker"]]
            overlap_by_speaker[speaker] = overlap_by_speaker.get(speaker, 0) + right - left
            active.append((left, right, speaker))
    if not active:
        return "unknown", ["speaker_unknown"]
    ranked = sorted(overlap_by_speaker, key=overlap_by_speaker.get, reverse=True)
    flags = []
    if len(ranked) > 1:
        flags.append("speaker_boundary")
        if any(a[2] != b[2] and min(a[1], b[1]) > max(a[0], b[0]) for a in active for b in active):
            flags.append("overlapping_speech")
        if abs(overlap_by_speaker[ranked[0]] - overlap_by_speaker[ranked[1]]) < 1e-6:
            return "unknown", flags + ["speaker_unknown"]
    return ranked[0], flags


def merge(asr: dict, aligned: dict, turns: list[dict], duration_ms: int) -> dict:
    turns = sorted((turn for turn in turns if interval(turn)), key=lambda t: (t["start"], t["end"], t["speaker"]))
    mapping = {}
    for turn in turns:
        mapping.setdefault(turn["speaker"], f"spk_{len(mapping)}")
    segments = []
    for source in aligned.get("segments", []) or asr.get("segments", []):
        bounds = interval(source)
        if not bounds:
            raise ValueError("INVALID_SEGMENT_TIMESTAMPS")
        segment_start_ms = round(bounds[0] * 1000)
        segment_end_ms = min(duration_ms, round(bounds[1] * 1000))
        if segment_start_ms >= segment_end_ms:
            continue
        words = []
        for word in source.get("words", []):
            bounds_word = interval(word)
            word_start_ms, word_end_ms = (round(value * 1000) for value in bounds_word) if bounds_word else (None, None)
            valid = (not word.get("alignment_missing") and bounds_word
                     and bounds[0] <= bounds_word[0] < bounds_word[1] <= bounds[1]
                     and segment_start_ms <= word_start_ms < word_end_ms <= segment_end_ms)
            speaker, flags = assign(*bounds_word, turns, mapping) if valid else ("unknown", ["alignment_missing", "speaker_unknown"])
            words.append({"text": word.get("word", ""), "start_ms": word_start_ms if valid else None,
                          "end_ms": word_end_ms if valid else None,
                          "speaker_id": speaker, "alignment_missing": not bool(valid), "review_reasons": flags})
        # Preserve the entire source text if tokenization/alignment omitted any words.
        normalized = lambda text: " ".join(text.split())
        complete_text = normalized(" ".join(w["text"] for w in words)) == normalized(source["text"])
        if source.get("alignment_incomplete") or not words or not complete_text or any(w["alignment_missing"] for w in words):
            speaker, flags = assign(*bounds, turns, mapping)
            groups = [(source["text"], segment_start_ms, segment_end_ms, speaker, words,
                       sorted(set(flags + ["alignment_incomplete"] + [r for w in words for r in w["review_reasons"]])))]
        else:
            groups = []
            for word in words:
                if groups and groups[-1][3] == word["speaker_id"]:
                    previous = groups[-1]
                    groups[-1] = (previous[0] + " " + word["text"], previous[1], word["end_ms"], previous[3],
                                  previous[4] + [word], sorted(set(previous[5] + word["review_reasons"])))
                else:
                    groups.append((word["text"], word["start_ms"], word["end_ms"], word["speaker_id"], [word], word["review_reasons"]))
        for text, start, end, speaker, group_words, flags in groups:
            segments.append({"id": f"seg_{len(segments) + 1}", "start_ms": start, "end_ms": end, "text": text,
                             "speaker_id": speaker, "words": group_words, "requires_review": bool(flags), "review_reasons": flags})
    return {"speakers": [{"id": value, "display_name": f"Спикер {i + 1}"} for i, value in enumerate(mapping.values())],
            "segments": segments, "diarization_turns": [{**turn, "speaker_id": mapping[turn["speaker"]]} for turn in turns]}
