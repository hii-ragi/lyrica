"""Acceptance regressions using the same real Sudachi dictionary as the app."""
from pathlib import Path
import tempfile
import unittest

from lyrica_backend.alignment import aligned_line, apply_evidence, coarse_windows
from lyrica_backend.export import export_batch
from lyrica_backend.lrc import render_lrc
from lyrica_backend.text import Reader, canonical, lyric_text, prepare_lines, ruby_text


class ReadingAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader = Reader()

    def test_parenthesized_reading_overrides_dictionary_without_changing_source(self):
        for text in ("宇宙(そら)を見上げる", "宇宙（そら）を見上げる"):
            with self.subTest(text=text):
                row = prepare_lines([{"text": text}], self.reader)[0]
                self.assertEqual(row["reading"], "そらヲミアゲル")
                self.assertEqual(row["normalized"], "そらをみあげる")
                self.assertEqual(row["alignment_text"], "そらを見上げる")
                self.assertEqual(row["text"], text)

    def test_multiple_annotations_and_token_offsets_refer_to_original(self):
        text = "宇宙(そら)と未来（あす）へFly away"
        reading, tokens = self.reader.reading(text)
        self.assertEqual(reading, "そらトあすヘFly away")
        self.assertEqual("".join(token["surface"] for token in tokens), text)
        for token in tokens:
            self.assertEqual(text[token["begin"]:token["end"]], token["surface"])
        self.assertEqual(len([token for token in tokens if token.get("explicit")]), 2)

    def test_latin_case_spaces_apostrophes_and_punctuation_are_preserved(self):
        for text, expected in (
            ("君とFly away", "キミトFly away"),
            ("君とDon't STOP!  Fly away", "キミトDon't STOP!  Fly away"),
            ("君とＦｌｙ away", "キミトＦｌｙ away"),
            ("I love you", "I love you"),
        ):
            with self.subTest(text=text):
                self.assertEqual(self.reader.reading(text)[0], expected)

    def test_manual_reading_has_priority_over_parentheses(self):
        row = prepare_lines([{"text": "宇宙(そら)", "reading": "ウチュウ"}], self.reader)[0]
        self.assertEqual(row["reading"], "ウチュウ")
        self.assertEqual(row["alignment_text"], "ウチュウ")
        self.assertEqual(row["text"], "宇宙(そら)")

    def test_automatic_reading_returned_by_ui_still_expands_annotations(self):
        row = prepare_lines([{"text": "宇宙(そら)を見上げる", "reading": "そらヲミアゲル"}], self.reader)[0]
        self.assertEqual(row["alignment_text"], "そらを見上げる")

    def test_ordinary_empty_and_mismatched_parentheses_are_not_ruby(self):
        for text in ("君とFly (live)", "(そら)", "宇宙()", "宇宙(そら）", "宇宙（そら)", "宇宙(広い空)"):
            with self.subTest(text=text):
                self.assertEqual(ruby_text(text), text)

    def test_source_lines_and_whitespace_survive_to_utf8_export(self):
        texts = lyric_text("\ufeff[ti:曲]\n  宇宙(そら)  \n\n君とFly away")
        self.assertEqual(texts, ["  宇宙(そら)  ", "君とFly away"])
        lines = prepare_lines([{"text": text, "source_line": n} for text, n in zip(texts, (2, 4))], self.reader)
        # These are measured-ASR fixtures; timestamps are never inserted by prepare_lines.
        segments = [{"text": "そら", "start": 1.25, "end": 2.5},
                    {"text": "君とFly away", "start": 4, "end": 6}]
        normalize = lambda text: canonical(self.reader.reading(text)[0])
        windows = coarse_windows(lines, segments, 10, normalize)
        rows = [apply_evidence(aligned_line(line, {}, 0), window, "", normalize)
                for line, window in zip(lines, windows)]
        self.assertEqual([row["source_line"] for row in rows], [2, 4])
        self.assertEqual([row["start"] for row in rows], [1.25, 4])
        expected = "[00:01.25]  宇宙(そら)  \n[00:04.00]君とFly away\n"
        self.assertEqual(render_lrc(rows), expected)
        with tempfile.TemporaryDirectory() as folder:
            for format in ("lrc", "txt"):
                result = export_batch(folder, [{"name": "曲.wav", "lines": rows}], format)
                self.assertFalse(result["errors"])
                self.assertEqual(Path(result["saved"][0]).suffix, "." + format)
                self.assertEqual(Path(result["saved"][0]).read_bytes(), expected.encode("utf-8"))

    def test_unmatched_mixed_line_does_not_get_a_dummy_time_or_export(self):
        line = prepare_lines([{"text": "宇宙(そら)とFly away", "source_line": 8}], self.reader)[0]
        row = apply_evidence(aligned_line(line, {}, 0),
                             {"text": line["alignment_text"], "anchor_coverage": 0,
                              "anchor_start": None, "anchor_end": None}, "", canonical)
        self.assertIsNone(row["start"])
        self.assertEqual((row["text"], row["source_line"]), ("宇宙(そら)とFly away", 8))
        with self.assertRaises(ValueError):
            render_lrc([row])
        with tempfile.TemporaryDirectory() as folder:
            result = export_batch(folder, [{"name": "failed.wav", "lines": [row]}])
            self.assertEqual(result["saved"], [])
            self.assertEqual(len(result["errors"]), 1)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_invalid_source_line_is_rejected(self):
        for n in (0, -1, True, "2"):
            with self.subTest(n=n), self.assertRaises(ValueError):
                prepare_lines([{"text": "歌", "source_line": n}], self.reader)

    def test_txt_collision_and_invalid_formats(self):
        with tempfile.TemporaryDirectory() as folder:
            track = {"name": "曲.wav", "lines": [{"text": "原文", "start": 2}]}
            first = export_batch(folder, [track, track], "txt")
            self.assertEqual([Path(p).name for p in first["saved"]], ["曲.txt", "曲_1.txt"])
            for format in ("csv", "../txt", "", None):
                with self.subTest(format=format), self.assertRaises(ValueError):
                    export_batch(folder, [track], format)
