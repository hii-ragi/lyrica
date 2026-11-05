import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from lyrica_backend.alignment import aligned_line, apply_evidence, coarse_windows
from lyrica_backend.pipeline import WhisperEngine, demucs_command
from lyrica_backend.settings import SCHEMA, DEFAULTS, analysis_options


class SettingsTests(unittest.TestCase):
    def test_missing_and_legacy_options_use_existing_defaults(self):
        options = analysis_options({"device": "cuda"})
        self.assertEqual(options["device"], "cuda")
        self.assertEqual({key: options[key] for key in DEFAULTS}, DEFAULTS)
        self.assertEqual((options["min_agreement"], options["fallback_coverage"]), (.35, .75))

    def test_numeric_bounds_and_types_are_checked_before_inference(self):
        for key, rule in SCHEMA["numeric"].items():
            invalid = [rule["min"]-1, rule["max"]+1, True, "1", None, float("nan"), float("inf")]
            if rule["step"] == 1:
                invalid.append(rule["min"]+.5)
            for value in invalid:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    WhisperEngine({key: value}, Path("."))

    def test_boolean_types_and_inconsistent_thresholds_are_rejected(self):
        for key in SCHEMA["boolean"]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                analysis_options({key: "false"})
        with self.assertRaises(ValueError):
            analysis_options({"min_agreement": .8, "review_agreement": .6})

    def test_integer_valued_floats_are_normalized_for_model_and_cli(self):
        options = analysis_options({"beam_size":7.0, "demucs_shifts":2.0})
        self.assertIs(type(options["beam_size"]), int)
        command = demucs_command("in.wav","out",options)
        self.assertEqual(command[command.index("--shifts")+1], "2")

    def test_demucs_options_reach_cpu_and_cuda_commands(self):
        options = {"demucs_overlap": .5, "demucs_shifts": 3, "cuda_demucs_segment": 4.5}
        cpu = demucs_command("in.wav", "out", options)
        cuda = demucs_command("in.wav", "out", {**options, "device": "cuda"})
        self.assertEqual(float(cpu[cpu.index("--overlap")+1]), .5)
        self.assertEqual(cpu[cpu.index("--shifts")+1], "3")
        self.assertNotIn("--segment", cpu)
        self.assertEqual(cuda[cuda.index("--segment")+1], "4.5")

    def test_padding_and_window_limit_change_real_anchor_bounds(self):
        lines = [{"normalized": "abc"}]
        segments = [{"text": "abc", "start": 2, "end": 3}]
        default = coarse_windows(lines, segments, 20, str)[0]
        custom = coarse_windows(lines, segments, 20, str, {"align_padding_seconds": 1})[0]
        self.assertEqual((default["start"], default["end"]), (1.65, 3.35))
        self.assertEqual((custom["start"], custom["end"]), (1, 4))
        self.assertIsNone(coarse_windows(lines, [{"text":"abc","start":2,"end":10}], 20, str,
                                        {"align_max_window_seconds":5})[0])

    def test_fallback_threshold_changes_measured_word_time_adoption(self):
        window = {"text": "abc", "anchor_coverage": .5, "anchor_start": 8, "anchor_end": 10}
        row = {"start": None, "end": None, "confidence": 0, "review": True}
        self.assertIsNone(apply_evidence(dict(row), window, "", str)["start"])
        result = apply_evidence(dict(row), window, "", str, {"fallback_coverage": .4})
        self.assertEqual((result["start"], result["end"]), (8, 10))
        self.assertTrue(result["review"])

    def test_relaxed_agreement_remains_reviewable_and_never_accepts_no_evidence(self):
        options = {"min_agreement": .1, "review_agreement": .1, "fallback_coverage": .1}
        row = {"start": 2, "end": 3, "confidence": .9, "review": False}
        window = {"text": "abcdefghij", "anchor_coverage": 0, "anchor_start": None, "anchor_end": None}
        accepted = apply_evidence(dict(row), window, "aklmnopqrs", str, options)
        self.assertEqual(accepted["start"], 2)
        self.assertTrue(accepted["review"])
        self.assertIsNone(apply_evidence(dict(row), window, "xyz", str, options)["start"])

    def test_review_score_threshold_changes_review_flag(self):
        line = {"text":"AB", "reading":"AB", "normalized":"ab", "tokens":[]}
        result = {"segments":[{"chars":[{"start":1, "end":2, "score":.5},
                                       {"start":2, "end":3, "score":.5}]}]}
        self.assertFalse(aligned_line(line, result, 1)["review"])
        self.assertTrue(aligned_line(line, result, 1, {"review_score":.8})["review"])


class RecognitionSettingsTests(unittest.TestCase):
    @staticmethod
    def decoder():
        return Mock(side_effect=lambda *a, **kw: (iter([SimpleNamespace(words=[], text="word", start=1, end=2)]), None))

    def test_faster_whisper_receives_vad_and_decode_settings(self):
        decode = self.decoder()
        module = SimpleNamespace(WhisperModel=lambda *a, **kw: SimpleNamespace(transcribe=decode))
        options = {"vad_enabled":False, "vad_threshold":.2, "beam_size":7,
                   "no_speech_threshold":.4, "log_prob_threshold":-.5, "condition_on_previous_text":False}
        with patch.dict(sys.modules, {"faster_whisper":module}), patch("lyrica_backend.pipeline.release_gpu"):
            WhisperEngine(options, Path(".")).transcribe([0]*16000, lambda *a: None)
        self.assertEqual(decode.call_args.kwargs["beam_size"], 7)
        self.assertFalse(decode.call_args.kwargs["vad_filter"])
        self.assertEqual(decode.call_args.kwargs["vad_parameters"], {"threshold":.2})
        self.assertFalse(decode.call_args.kwargs["condition_on_previous_text"])
        self.assertEqual(decode.call_args.kwargs["no_speech_threshold"], .4)

    def test_whisperx_receives_threshold_chunk_and_decode_settings(self):
        decode = self.decoder()
        first = Mock(return_value={"segments":[{"text":"word", "start":0, "end":8}]})
        load = Mock(return_value=SimpleNamespace(transcribe=first, model=SimpleNamespace(transcribe=decode)))
        options = {"engine":"whisperx", "vad_threshold":.2, "whisperx_chunk_seconds":12,
                   "beam_size":7, "condition_on_previous_text":False}
        with patch.dict(sys.modules, {"whisperx":SimpleNamespace(load_model=load)}), patch("lyrica_backend.pipeline.release_gpu"):
            WhisperEngine(options, Path(".")).transcribe([0]*16000*10, lambda *a: None)
        self.assertEqual(load.call_args.kwargs["vad_options"]["vad_onset"], .2)
        self.assertAlmostEqual(load.call_args.kwargs["vad_options"]["vad_offset"], .1452)
        self.assertEqual(first.call_args.kwargs["chunk_size"], 12)
        self.assertEqual(decode.call_args.kwargs["clip_timestamps"], [0,8])
        self.assertEqual(decode.call_args.kwargs["beam_size"], 7)
        self.assertFalse(decode.call_args.kwargs["condition_on_previous_text"])

    def test_whisperx_vad_off_does_not_gate_audio_through_first_pass(self):
        decode = self.decoder()
        first = Mock(side_effect=AssertionError("VAD first pass must be skipped"))
        module = SimpleNamespace(load_model=lambda *a, **kw: SimpleNamespace(
            transcribe=first, model=SimpleNamespace(transcribe=decode)))
        with patch.dict(sys.modules, {"whisperx":module}), patch("lyrica_backend.pipeline.release_gpu"):
            result = WhisperEngine({"engine":"whisperx","vad_enabled":False}, Path(".")).transcribe([0]*16000*10, lambda *a: None)
        first.assert_not_called()
        self.assertEqual(decode.call_args.kwargs["clip_timestamps"], [0,10])
        self.assertEqual(len(result), 1)
