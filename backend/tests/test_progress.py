import contextlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from lyrica_backend.cli import progress
from lyrica_backend.pipeline import WhisperEngine


class ProgressTests(unittest.TestCase):
    def test_events_are_stderr_json_and_counters_are_optional(self):
        stderr, stdout = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
            progress("separate", "ボーカル分離中")
            progress("align", "解析済み", 2, 4)
        self.assertEqual(stdout.getvalue(), "")
        events = [json.loads(line.removeprefix("LYRICA_EVENT ")) for line in stderr.getvalue().splitlines()]
        self.assertNotIn("completed", events[0])
        self.assertEqual((events[1]["completed"], events[1]["total"]), (2, 4))

    def test_asr_progress_uses_measured_audio_position(self):
        segments = [
            SimpleNamespace(words=[], text="one", start=0, end=2),
            SimpleNamespace(words=[], text="two", start=2, end=7),
        ]
        model = SimpleNamespace(transcribe=lambda *args, **kwargs: (iter(segments), None))
        module = SimpleNamespace(WhisperModel=lambda *args, **kwargs: model)
        events = []
        with patch.dict(sys.modules, {"faster_whisper": module}), patch("lyrica_backend.pipeline.release_gpu"):
            result = WhisperEngine({}, Path(".")).transcribe([0] * 160000, lambda *args: events.append(args))
        self.assertEqual(len(result), 2)
        counters = [(e[2], e[3]) for e in events if len(e) == 4]
        self.assertEqual(counters, [(0, 10), (2, 10), (7, 10), (10, 10)])

    def test_unresolved_lines_advance_only_when_checked_and_keep_no_dummy_times(self):
        events = []
        lines = [{"text": "未確定", "reading": "ミカクテイ", "tokens": []} for _ in range(3)]
        with patch.dict(sys.modules, {"torch": SimpleNamespace(), "whisperx": SimpleNamespace()}), patch("lyrica_backend.pipeline.release_gpu"):
            result = WhisperEngine({}, Path(".")).align([], lines, [None] * 3, lambda *args: events.append(args), str)
        self.assertEqual([e[2] for e in events], [0, 1, 1, 2, 2, 3])
        self.assertTrue(all(e[3] == 3 for e in events))
        self.assertTrue(all(row["start"] is None for row in result))
