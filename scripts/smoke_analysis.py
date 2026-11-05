"""Real model smoke test: supply a short audio and its UTF-8 lyrics."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--audio", required=True, type=Path)
parser.add_argument("--lyrics", required=True, type=Path)
parser.add_argument("--language", default="ja", choices=["ja","en"])
parser.add_argument("--separate", action="store_true")
parser.add_argument("--bridge-dir",type=Path,help="Packaged directory to test; default: target/debug")
parser.add_argument("--device",choices=["cpu","cuda"],default="cpu")
parser.add_argument("--model",choices=["tiny","base","small"],default="tiny")
parser.add_argument("--engine", default="faster-whisper", choices=["faster-whisper","whisperx"])
parser.add_argument("--output", type=Path, default=ROOT / "build/smoke-analysis-result.json")
parser.add_argument("--settings", type=Path, help="JSON settings; explicit device/model/engine flags take priority")
args = parser.parse_args()
sys.path.insert(0, str(ROOT / "backend" / "src"))
from lyrica_backend.text import lyric_text
home = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "io.lyricgen.desktop" / "analysis"
debug = args.bridge_dir or ROOT / "src-tauri" / "target" / "debug"
texts = lyric_text(args.lyrics.read_text(encoding="utf-8"))
extra = json.loads(args.settings.read_text(encoding="utf-8")) if args.settings else {}
if not isinstance(extra, dict):
    raise SystemExit("Settings must be a JSON object")
request = {"operation":"analyze", "audio_path":str(args.audio.resolve()),
           "runtime_dir":str(home), "resource_dir":str(debug / "analysis"),
           "lines":[{"text":text} for text in texts],
           "options":{**extra, "engine":args.engine, "asr_model":args.model, "language":args.language,
                      "device":args.device, "separate":args.separate}}
result = subprocess.run([str(debug / ("lyrica-backend.exe" if os.name == "nt" else "lyrica-backend"))],
                        input=json.dumps(request, ensure_ascii=False), encoding="utf-8",
                        stdout=subprocess.PIPE, timeout=1800, check=False)
if result.returncode:
    raise SystemExit(result.stdout)
data = json.loads(result.stdout)
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
if args.settings:
    from lyrica_backend.settings import analysis_options
    expected = analysis_options(request["options"])
    assert data["diagnostics"]["options"] == expected
if data.get("device") != args.device:
    raise SystemExit("Requested processing device was not used")
if args.device == "cuda" and not data.get("gpu_name"):
    raise SystemExit("CUDA execution did not report the NVIDIA GPU")
if [line["text"] for line in data["lines"]] != texts:
    raise SystemExit("Original lyrics were changed")
times = [line["start"] for line in data["lines"] if line["start"] is not None]
if len(times) != len(texts) or times != sorted(times) or any(not 0 <= t <= data["duration"] for t in times):
    raise SystemExit(f"Smoke audio was not fully aligned: {data}")
# Verify the frozen exporter writes actual inferred times with untouched source text.
from lyrica_backend.lrc import render_lrc
expected_lrc = render_lrc(data["lines"])
with tempfile.TemporaryDirectory(prefix="lyrica-acceptance-") as folder:
    for format in ("lrc", "txt"):
        exported = subprocess.run(
            [str(debug / ("lyrica-backend.exe" if os.name == "nt" else "lyrica-backend"))],
            input=json.dumps({"operation":"export_batch","directory":folder,"format":format,
                              "tracks":[{"name":"acceptance.wav","lines":data["lines"]}]}),
            encoding="utf-8",capture_output=True,timeout=60,check=True)
        report = json.loads(exported.stdout)
        assert not report["errors"] and len(report["saved"]) == 1, report
        target = Path(report["saved"][0])
        assert target.suffix == "." + format
        assert target.read_bytes() == expected_lrc.encode("utf-8")
args.output.with_suffix(".lrc").write_text(expected_lrc,encoding="utf-8")

print(f"Real-model smoke test passed ({args.device}, {args.model}): {len(times)} lines, duration={data['duration']:.2f}s, review={data['review_count']}")
