import json
import subprocess
import sys
import unittest

from lyricgen_backend.lrc import render_lrc


class LrcTests(unittest.TestCase):
    def test_japanese_and_minute_rollover(self):
        self.assertEqual(render_lrc([
            {"start": 0, "text": "宇宙"},
            {"start": 59.995, "text": "そら"},
            {"start": 61.005, "text": "君へ"},
        ]), "[00:00.00]宇宙\n[01:00.00]そら\n[01:01.01]君へ\n")

    def test_invalid_lines(self):
        for lines in (None, [], [None], [{"start": True, "text": "a"}],
                      [{"start": -1, "text": "a"}], [{"start": float("nan"), "text": "a"}],
                      [{"start": float("inf"), "text": "a"}], [{"start": 86401, "text": "a"}],
                      [{"start": 0, "text": "a\nb"}], [{"start": 0, "text": "a\x00b"}],
                      [{"start": 0, "text": 1}], [{"start": "1", "text": "a"}],
                      [{"start": 2, "text": "a"}, {"start": 1, "text": "b"}]):
            with self.subTest(lines=lines), self.assertRaises(ValueError):
                render_lrc(lines)

    def test_equal_times_and_empty_text(self):
        self.assertEqual(render_lrc([
            {"start": 1, "text": ""}, {"start": 1, "text": "合唱"},
        ]), "[00:01.00]\n[00:01.00]合唱\n")

    def run_cli(self, request):
        return subprocess.run(
            [sys.executable, "-m", "lyricgen_backend.cli"], input=request,
            capture_output=True, encoding="utf-8", check=False,
        )

    def test_cli_roundtrip(self):
        result = self.run_cli(json.dumps({
            "operation": "render_lrc", "lines": [{"start": 12.5, "text": "日本語の歌詞"}],
        }, ensure_ascii=False))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"lrc": "[00:12.50]日本語の歌詞\n"})

    def test_cli_errors_are_json(self):
        for request in ("not json", "[]", '{"operation":"unknown"}', '{"operation":"render_lrc"}'):
            with self.subTest(request=request):
                result = self.run_cli(request)
                self.assertEqual(result.returncode, 1)
                self.assertIn("error", json.loads(result.stdout))


if __name__ == "__main__":
    unittest.main()
