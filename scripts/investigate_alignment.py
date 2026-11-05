"""Measure recognition vs alignment failures using the production analyzer."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
parser = argparse.ArgumentParser()
parser.add_argument("--audio", type=Path, required=True)
parser.add_argument("--lyrics", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--engine", choices=["whisperx", "faster-whisper"], default="whisperx")
parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
parser.add_argument("--model", default="small")
args = parser.parse_args()
from lyrica_backend.runtime import runtime_env
home = Path(os.environ["LOCALAPPDATA"]) / "io.lyricgen.desktop/analysis"
os.environ.update(runtime_env(home, ROOT / "src-tauri/target/debug/analysis", args.device))
from lyrica_backend.device import register_cuda_libraries
register_cuda_libraries()
from lyrica_backend.pipeline import analyze
from lyrica_backend.text import lyric_text, Reader, canonical
from unittest.mock import patch
import difflib
import lyrica_backend.pipeline as pipeline_module

def progress(stage, message, *counters):
    print(stage, message, *counters, flush=True)

evidence = []
reader = Reader()
original_evidence = pipeline_module.apply_evidence
def capture_evidence(row, window, decoded, normalize, options=None):
    expected, observed = normalize(window["text"]), normalize(decoded)
    result = original_evidence(dict(row), window, decoded, normalize, options)
    # Numeric script/phonetic diagnostics; full lyrics and decoded lyrics are not persisted.
    evidence.append({"source_line": row.get("source_line"),
                     "ctc_start_before_filter": row["start"], "ctc_end_before_filter": row["end"],
                     "ctc_confidence": row["confidence"], "anchor_coverage": window["anchor_coverage"],
                     "expected_chars": len(expected), "decoded_chars": len(observed),
                     "expected_latin_chars": sum("a" <= c <= "z" for c in expected),
                     "decoded_latin_chars": sum("a" <= c <= "z" for c in observed),
                     "agreement": result["agreement"],
                     "after_filter_start": result["start"]})
    return result

with patch.object(pipeline_module, "apply_evidence", side_effect=capture_evidence):
    result = analyze({"audio_path": str(args.audio.resolve()),
                  "lines": [{"text": t} for t in lyric_text(args.lyrics.read_text(encoding="utf-8"))],
                  "options": {"engine": args.engine, "device": args.device, "asr_model": args.model,
                              "language": "ja", "separate": True}}, progress)
recognition = result["diagnostics"]["recognition"]
windows = result["diagnostics"]["windows"]
rows = result["lines"]
report = {k: result[k] for k in ["duration", "device", "engine", "review_count", "unresolved_count"]}
report["evidence"] = evidence
report["asr_items"] = len(recognition)
report["asr_last_end"] = max((r["end"] for r in recognition), default=None)
report["asr_chars"] = sum(len(r["text"]) for r in recognition)
report["line_count"] = len(rows)
report["rows"] = [{"line": i+1, "start": row["start"], "end": row["end"],
                   "review": row["review"], "confidence": row["confidence"], "agreement": row.get("agreement"), "note": row["note"],
                   "anchor_coverage": window["anchor_coverage"] if window else 0,
                   "window_start": window["start"] if window else None,
                   "window_end": window["end"] if window else None}
                  for i,(row,window) in enumerate(zip(rows,windows))]
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("RESULT", json.dumps({k:v for k,v in report.items() if k not in ("rows", "evidence")}, ensure_ascii=False), flush=True)
