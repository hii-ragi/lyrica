import json
from pathlib import Path
import tempfile
import unittest

from lyrica_backend.alignment import aligned_line, apply_evidence, coarse_windows
from lyrica_backend.export import export_batch
from lyrica_backend.runtime import fingerprint, python_path, runtime_status
from lyrica_backend.text import canonical, lyric_text, prepare_lines


class FakeReader:
    def reading(self, text):
        return "ウチュウ", [{"surface":text,"reading":"ウチュウ","begin":0,"end":len(text)}]


class TextTests(unittest.TestCase):
    def test_original_text_and_override_are_separate(self):
        row = prepare_lines([{"text":"宇宙","reading":"ソラ"}], FakeReader())[0]
        self.assertEqual((row["text"],row["reading"],row["normalized"]), ("宇宙","ソラ","そら"))
        self.assertEqual(row["tokens"][0]["surface"], "宇宙")

    def test_normalization(self):
        self.assertEqual(canonical("ソラ ＡＢＣ、１２３！"), "そらabc123")

    def test_plain_and_lrc_input(self):
        self.assertEqual(lyric_text("\ufeff[ti:曲]\n[00:01.20]宇宙\n\n君へ"), ["宇宙","君へ"])

    def test_invalid_line_format(self):
        for rows in ([], [{}], [{"text":""}], [{"text":"A\nB"}], [{"text":"a","reading":2}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                prepare_lines(rows, FakeReader())


class AlignmentTests(unittest.TestCase):
    def test_repeated_chorus_remains_in_sequence(self):
        lines = [{"normalized":text} for text in ("あいう","かきく","あいう")]
        segments = [{"text":text,"start":start,"end":start+2}
                    for text,start in (("あいう",2),("かきく",10),("あいう",20))]
        windows = coarse_windows(lines, segments, 30, lambda text:text)
        self.assertLess(windows[0]["end"],windows[1]["start"])
        self.assertLess(windows[1]["end"],windows[2]["start"])

    def test_reading_offsets_are_independent_of_display_length(self):
        lines = [{"normalized":"あいうえお", "alignment_text":"今日"},
                 {"normalized":"かきくけこ", "alignment_text":"天気"}]
        windows = coarse_windows(lines, [{"text":"あいうえお", "start":0,"end":2},
                                          {"text":"かきくけこ", "start":10,"end":12}],20,lambda t:t)
        self.assertGreater(windows[1]["start"],7)
        self.assertEqual(windows[1]["text"],"天気")

    def test_missing_edge_line_is_unresolved(self):
        windows = coarse_windows([{"normalized":"xyz"},{"normalized":"abc"}],
                                 [{"text":"abc","start":10,"end":12}],20,lambda t:t)
        self.assertIsNone(windows[0])
        self.assertIsNotNone(windows[1])

    def test_no_voice_is_an_error(self):
        with self.assertRaises(ValueError):
            coarse_windows([{"normalized":"a"}],[],10,lambda t:t)

    def test_whisperx_fallback_window_is_not_a_measured_timestamp(self):
        line = {"text":"宇宙","reading":"ソラ","normalized":"そら","tokens":[]}
        result = aligned_line(line, {"segments":[{"start":0,"end":10,"chars":[]}]}, 1)
        self.assertIsNone(result["start"])
        self.assertTrue(result["review"])

    def test_character_timing_and_low_confidence(self):
        line = {"text":"宇宙","reading":"ソラ","normalized":"そら","tokens":[]}
        chars = [{"start":2,"end":2.2,"score":.9},{"start":2.2,"end":2.5,"score":.8}]
        result = aligned_line(line,{"segments":[{"chars":chars}]},1)
        self.assertEqual((result["text"],result["start"],result["end"]),("宇宙",2,2.5))
        self.assertFalse(result["review"])
        self.assertTrue(aligned_line(line,{"segments":[{"chars":chars}]},.1)["review"])

    def test_high_blank_score_is_checked_against_recognition(self):
        row = {"start":0,"end":5,"confidence":.99,"review":False}
        window = {"text":"hello","anchor_coverage":1,"anchor_start":2,"anchor_end":3}
        result = apply_evidence(row,window,"xyz",lambda t:t)
        self.assertEqual(result["start"],2)
        self.assertTrue(result["review"])

    def test_no_evidence_keeps_line_unresolved(self):
        row = {"start":0,"end":5,"confidence":.99,"review":False}
        window = {"text":"hello","anchor_coverage":.1,"anchor_start":2,"anchor_end":3}
        self.assertIsNone(apply_evidence(row,window,"",lambda t:t)["start"])

    def test_nonfinite_timing_is_never_exported(self):
        line = {"text":"A","reading":"A","normalized":"a","tokens":[]}
        result = aligned_line(line,{"segments":[{"chars":[{"start":float("nan"),"end":1,"score":1}]}]},1)
        self.assertIsNone(result["start"])


class ExportTests(unittest.TestCase):
    def test_collision_never_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as path:
            existing = Path(path)/"曲.lrc"
            existing.write_text("keep",encoding="utf-8")
            track = {"name":"曲.mp3","lines":[{"start":1,"text":"歌詞"}]}
            result = export_batch(path,[track,track])
            self.assertEqual(existing.read_text(encoding="utf-8"),"keep")
            self.assertEqual([Path(p).name for p in result["saved"]],["曲_1.lrc","曲_2.lrc"])
            self.assertEqual(Path(result["saved"][0]).read_text(encoding="utf-8"),"[00:01.00]歌詞\n")

    def test_failed_track_does_not_block_other_tracks(self):
        with tempfile.TemporaryDirectory() as path:
            result = export_batch(path,[
                {"name":"unknown.mp3","lines":[{"start":None,"text":"a"}]},
                {"name":"../../CON.mp3","lines":[{"start":0,"text":"b"}]}])
            self.assertEqual(len(result["errors"]),1)
            self.assertEqual(Path(result["saved"][0]).parent,Path(path))
            self.assertEqual(Path(result["saved"][0]).name,"_CON.lrc")


class RuntimeTests(unittest.TestCase):
    def test_partial_or_outdated_install_is_not_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            home, resources = Path(folder)/"home",Path(folder)/"resources"
            home.mkdir();resources.mkdir()
            requirements = resources/"requirements-analysis.txt"
            requirements.write_text("version 1")
            self.assertFalse(runtime_status(home,resources)["ready"])
            python_path(home).parent.mkdir(parents=True)
            python_path(home).touch()
            (home/"ready.txt").write_text(fingerprint(resources))
            self.assertTrue(runtime_status(home,resources)["ready"])
            requirements.write_text("version 2")
            self.assertFalse(runtime_status(home,resources)["ready"])


if __name__ == "__main__":
    unittest.main()
