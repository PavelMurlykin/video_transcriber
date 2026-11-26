"""Assign speakers to words while preserving the overlapping speech timeline."""

from bisect import bisect_right
from collections import Counter, defaultdict
from itertools import groupby
import math

UNKNOWN = "unknown"
SpeechSpan = tuple[int, int, tuple[str, ...]]


def interval(item: dict):
    start, end = item.get("start"), item.get("end")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        return None
    return start, end


def _ordered_turns(turns: list[dict], duration_ms: int) -> list[dict]:
    return sorted(
        (turn for turn in turns if interval(turn)
         and round(turn["start"] * 1000) < min(duration_ms, round(turn["end"] * 1000))),
        key=lambda turn: (turn["start"], turn["end"], turn["speaker"]),
    )


def _speech_spans(turns: list[dict], duration_ms: int) -> list[SpeechSpan]:
    """Disjoint intervals with the distinct speakers who are active in each."""
    changes = defaultdict(Counter)
    for turn in turns:
        start = round(turn["start"] * 1000)
        end = min(duration_ms, round(turn["end"] * 1000))
        changes[start][turn["speaker_id"]] += 1
        changes[end][turn["speaker_id"]] -= 1

    active = Counter()
    spans = []
    previous = 0
    for instant in sorted(changes):
        if active and previous < instant:
            speakers = tuple(sorted(active))
            if spans and spans[-1][1] == previous and spans[-1][2] == speakers:
                spans[-1] = (spans[-1][0], instant, speakers)
            else:
                spans.append((previous, instant, speakers))
        for speaker, difference in changes[instant].items():
            active[speaker] += difference
            if active[speaker] == 0:
                del active[speaker]
        previous = instant
    return spans


def _intersections(spans: list[SpeechSpan], start: int, end: int):
    index = bisect_right(spans, start, key=lambda span: span[1])
    for i in range(index, len(spans)):
        left, right, speakers = spans[i]
        if left >= end:
            break
        yield min(end, right) - max(start, left), speakers


def _coverage(spans: list[SpeechSpan], start: int, end: int) -> tuple[Counter, Counter, bool]:
    covered = Counter()
    solo = Counter()
    overlaps = False
    for duration, speakers in _intersections(spans, start, end):
        for speaker in speakers:
            covered[speaker] += duration
        if len(speakers) == 1:
            solo[speakers[0]] += duration
        else:
            overlaps = True
    return covered, solo, overlaps


def _clear_candidate(coverage: Counter, duration: int) -> str | None:
    # Require a majority of the word and a lead of at least 10% of its time.
    ranked = coverage.most_common(2)
    if not ranked:
        return None
    speaker, first = ranked[0]
    second = ranked[1][1] if len(ranked) == 2 else 0
    if first * 2 > duration and (first - second) * 10 >= duration:
        return speaker
    return None


def _assign(start: int, end: int, raw: list[SpeechSpan], exclusive: list[SpeechSpan]) -> tuple[str, list[str]]:
    duration = end - start
    covered, solo, overlaps = _coverage(raw, start, end)
    flags = []
    if len(covered) > 1:
        flags.append("speaker_boundary")
    if overlaps:
        flags.append("overlapping_speech")

    candidate = _clear_candidate(covered, duration)
    if len(covered) > 1 and exclusive:
        exclusive_covered, _, _ = _coverage(exclusive, start, end)
        preferred = _clear_candidate(exclusive_covered, duration)
        # The single-speaker view can break a tie only with independent raw solo support.
        if preferred is not None and covered[preferred] * 2 > duration and solo[preferred] * 10 >= duration:
            candidate = preferred if candidate in (None, preferred) else None
    if candidate is None:
        flags.append("speaker_unknown")
    return candidate or UNKNOWN, flags


def _word_assignment(word: dict, bounds: tuple, start: int, end: int,
                     raw: list[SpeechSpan], exclusive: list[SpeechSpan]) -> dict:
    word_bounds = interval(word)
    if word_bounds and not word.get("alignment_missing") and bounds[0] <= word_bounds[0] < word_bounds[1] <= bounds[1]:
        left, right = (round(value * 1000) for value in word_bounds)
        if start <= left < right <= end:
            speaker, flags = _assign(left, right, raw, exclusive)
            return {"text": word["word"], "start_ms": left, "end_ms": right, "speaker_id": speaker,
                    "alignment_missing": False, "review_reasons": flags}

    return {"text": word.get("word", ""), "start_ms": None, "end_ms": None, "speaker_id": UNKNOWN,
            "alignment_missing": True, "review_reasons": ["alignment_missing", "speaker_unknown"]}


def _display_groups(source: dict, words: list[dict], start: int, end: int):
    complete_text = source["text"].split() == " ".join(word["text"] for word in words).split()
    missing = any(word["alignment_missing"] for word in words)
    incomplete = source.get("alignment_incomplete") or not words or not complete_text or missing
    named_speakers = {word["speaker_id"] for word in words} - {UNKNOWN}
    if not complete_text or (incomplete and len(named_speakers) < 2):
        yield source["text"], start, end, UNKNOWN, words, True
        return

    groups = [(speaker, list(group)) for speaker, group in groupby(words, key=lambda word: word["speaker_id"])]
    for index, (speaker, group) in enumerate(groups):
        timed = [word for word in group if not word["alignment_missing"]]
        if len(timed) == len(group):
            left = min(word["start_ms"] for word in timed)
            right = max(word["end_ms"] for word in timed)
        else:
            # Use surrounding anchors for the display group. Missing word times stay null.
            left = groups[index - 1][1][-1]["end_ms"] if index else start
            right = groups[index + 1][1][0]["start_ms"] if index + 1 < len(groups) else end
            if left >= right or any(not left <= word["start_ms"] < word["end_ms"] <= right for word in timed):
                left, right = start, end
        text = source["text"] if len(groups) == 1 else " ".join(word["text"] for word in group)
        yield text, left, right, speaker, group, incomplete


def merge(asr: dict, aligned: dict, turns: list[dict], duration_ms: int, *,
          exclusive_turns: list[dict] | None = None) -> dict:
    raw_turns = _ordered_turns(turns, duration_ms)
    mapping = {label: f"spk_{i}" for i, label in enumerate(dict.fromkeys(turn["speaker"] for turn in raw_turns))}
    mapped_turns = [{**turn, "speaker_id": mapping[turn["speaker"]]} for turn in raw_turns]
    mapped_exclusive = [
        {**turn, "speaker_id": mapping[turn["speaker"]]}
        for turn in _ordered_turns(exclusive_turns or [], duration_ms) if turn["speaker"] in mapping
    ]
    raw = _speech_spans(mapped_turns, duration_ms)
    exclusive = _speech_spans(mapped_exclusive, duration_ms)
    segments = []

    for source in aligned.get("segments", []) or asr.get("segments", []):
        bounds = interval(source)
        if not bounds:
            raise ValueError("INVALID_SEGMENT_TIMESTAMPS")
        start = round(bounds[0] * 1000)
        end = min(duration_ms, round(bounds[1] * 1000))
        if start >= end:
            continue
        words = [_word_assignment(word, bounds, start, end, raw, exclusive) for word in source.get("words", [])]
        for text, left, right, speaker, group, incomplete in _display_groups(source, words, start, end):
            reasons = {reason for word in group for reason in word["review_reasons"]}
            if incomplete:
                reasons.add("alignment_incomplete")
            if speaker == UNKNOWN:
                reasons.add("speaker_unknown")
            if any(len(speakers) > 1 for _, speakers in _intersections(raw, left, right)):
                reasons.add("overlapping_speech")
            segments.append({"id": f"seg_{len(segments) + 1}", "start_ms": left, "end_ms": right, "text": text,
                             "speaker_id": speaker, "words": group, "requires_review": bool(reasons),
                             "review_reasons": sorted(reasons)})

    return {
        "speakers": [{"id": speaker, "display_name": f"Спикер {i + 1}"} for i, speaker in enumerate(mapping.values())],
        "segments": segments,
        "diarization_turns": mapped_turns,
        "exclusive_diarization_turns": mapped_exclusive,
        "overlap_regions": [
            {"start_ms": start, "end_ms": end, "speaker_ids": list(speakers)}
            for start, end, speakers in raw if len(speakers) > 1
        ],
    }
