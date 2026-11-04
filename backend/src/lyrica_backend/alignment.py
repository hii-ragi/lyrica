"""Use measured ASR word times as anchors; keep failures visible."""
from difflib import SequenceMatcher
import math
from lyrica_backend.text import canonical


def coarse_windows(lines, segments, duration, normalize):
    reference = "".join(line["normalized"] for line in lines)
    hypothesis, times = "", []
    for segment in segments:
        text = normalize(segment["text"])
        start, end = float(segment["start"]), float(segment["end"])
        if not text or not 0 <= start < end <= duration + .1:
            continue
        hypothesis += text
        times.extend([(start, min(end, duration))] * len(text))
    if not hypothesis:
        raise ValueError("歌声を認識できませんでした。分離設定・音源・言語を確認してください")
    anchors = {}
    for block in SequenceMatcher(None, reference, hypothesis, autojunk=False).get_matching_blocks():
        if block.size >= 2 or len(reference) == 1:
            for offset in range(block.size):
                anchors[block.a + offset] = times[block.b + offset]
    bounds, offset = [], 0
    for line in lines:
        end = offset + len(line["normalized"])
        points = [anchors[i] for i in range(offset, end) if i in anchors]
        bounds.append((offset, end, points))
        offset = end
    windows = []
    for index, (begin, end, points) in enumerate(bounds):
        coverage = len(points) / (end - begin)
        anchor_start = min(p[0] for p in points) if points else None
        anchor_end = max(p[1] for p in points) if points else None
        if points:
            start, stop = max(0, anchor_start - .35), min(duration, anchor_end + .35)
        else:
            before = [t[1] for pos, t in anchors.items() if pos < begin]
            after = [t[0] for pos, t in anchors.items() if pos >= end]
            if not before or not after:
                windows.append(None)
                continue
            start, stop = max(0, max(before) - .35), min(duration, min(after) + .35)
        if stop - start > 90 or stop - start < .1:
            windows.append(None)
        else:
            windows.append({"start": start, "end": stop,
                            "text": lines[index].get("alignment_text", lines[index]["normalized"]),
                            "anchor_coverage": coverage, "anchor_start": anchor_start, "anchor_end": anchor_end})
    return windows


def aligned_line(line, result, anchor_coverage):
    characters = [c for segment in result.get("segments", []) for c in (segment.get("chars") or [])]
    timed = [c for c in characters if all(isinstance(c.get(k), (int, float))
             and math.isfinite(c[k]) for k in ("start", "end", "score"))
             and 0 <= c["start"] < c["end"] and c["score"] > 0]
    base = {k: line[k] for k in ("text", "reading", "tokens")}
    if not timed:
        return {**base, "start": None, "end": None, "confidence": 0, "review": True,
                "note": "時刻を特定できません。再生位置から手動で指定してください"}
    score = sum(c["score"] for c in timed) / len(timed)
    coverage = len(timed) / max(1, len(canonical(line.get("alignment_text", line["normalized"]))))
    review = score < .35 or coverage < .6 or anchor_coverage < .3
    return {**base, "start": round(min(c["start"] for c in timed), 3),
            "end": round(max(c["end"] for c in timed), 3), "confidence": round(score, 3),
            "review": review, "note": "認識が不確かなため同期を確認してください" if review else ""}


def apply_evidence(row, window, decoded, normalize):
    # A forced path through mostly blank emissions can have a misleadingly high score.
    expected, observed = normalize(window["text"]), normalize(decoded)
    agreement = SequenceMatcher(None, expected, observed, autojunk=False).ratio() if observed else 0
    if row["start"] is None or agreement < .35:
        if window["anchor_coverage"] >= .75 and window["anchor_start"] is not None:
            row.update(start=round(window["anchor_start"],3), end=round(window["anchor_end"],3),
                       confidence=round(window["anchor_coverage"] * .5,3), review=True,
                       note="WhisperXの対応が不確かなため音声認識の単語時刻を使用。同期を確認してください")
        else:
            row.update(start=None,end=None,confidence=0,review=True,
                       note="歌詞と音声の対応を確認できません。手動で開始時刻を指定してください")
    elif agreement < .65:
        row.update(review=True,note="アライメント結果と歌詞の対応が弱いため同期を確認してください")
    row["agreement"] = round(agreement,3)
    return row
