"""Small reproductions of the current two-pass recognition boundary."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from lyrica_backend.alignment import coarse_windows, apply_evidence
from lyrica_backend.pipeline import WhisperEngine


class Audio:
    def __len__(self):
        return 16000 * 120


class RecognitionInvestigationTests(unittest.TestCase):
    def test_second_pass_is_limited_to_first_pass_intervals(self):
        calls = []
        def transcribe(audio, **kwargs):
            calls.append(kwargs)
            return iter([SimpleNamespace(words=[], text="first", start=0, end=30)]), None
        pipeline = SimpleNamespace(
            model=SimpleNamespace(transcribe=transcribe),
            transcribe=lambda *a, **kw: {"segments": [{"text": "first", "start": 0, "end": 30}]})
        module = SimpleNamespace(load_model=lambda *a, **kw: pipeline)
        with patch.dict(sys.modules, {"whisperx": module}), patch("lyrica_backend.pipeline.release_gpu"):
            rows = WhisperEngine({"engine": "whisperx"}, Path(".")).transcribe(Audio(), lambda *a: None)
        self.assertEqual(calls[0]["clip_timestamps"], [0, 30])
        self.assertEqual(max(row["end"] for row in rows), 30)
        self.assertNotIn("vad_filter", calls[0])

    def test_empty_first_pass_does_not_decode_audio_again(self):
        calls = []
        pipeline = SimpleNamespace(
            model=SimpleNamespace(transcribe=lambda *a, **kw: calls.append(kw)),
            transcribe=lambda *a, **kw: {"segments": []})
        module = SimpleNamespace(load_model=lambda *a, **kw: pipeline)
        with patch.dict(sys.modules, {"whisperx": module}), patch("lyrica_backend.pipeline.release_gpu"):
            with self.assertRaises(ValueError):
                WhisperEngine({"engine": "whisperx"}, Path(".")).transcribe(Audio(), lambda *a: None)
        self.assertEqual(calls, [])

    def test_valid_late_words_are_not_systematically_cut_in_half(self):
        lines = [{"normalized": "abc"}, {"normalized": "xyz"}]
        windows = coarse_windows(lines, [{"text": "abc", "start": 2, "end": 3},
                                        {"text": "xyz", "start": 110, "end": 112}], 120, str)
        self.assertIsNotNone(windows[1])
        self.assertEqual(windows[1]["anchor_start"], 110)
        self.assertEqual(windows[1]["anchor_coverage"], 1)


    def test_high_confidence_ctc_candidate_is_unresolved_when_content_disagrees(self):
        row = {"start": 150, "end": 155, "confidence": .9, "review": False}
        window = {"text": "abcdef", "anchor_coverage": .53,
                  "anchor_start": 150, "anchor_end": 155}
        result = apply_evidence(row, window, "xyz", str)
        self.assertIsNone(result["start"])
        self.assertIsNone(result["end"])
        self.assertTrue(result["review"])
