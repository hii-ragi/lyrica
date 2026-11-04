"""Real model smoke test: supply a short audio and its UTF-8 lyrics."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--audio", required=True, type=Path)
parser.add_argument("--lyrics", required=True, type=Path)
parser.add_argument("--language", default="ja", choices=["ja","en"])
parser.add_argument("--separate", action="store_true")
parser.add_argument("--bridge-dir",type=Path,help="Packaged directory to test; default: target/debug")
parser.add_argument("--engine", default="faster-whisper", choices=["faster-whisper","whisperx"])
args = parser.parse_args()
sys.path.insert(0, str(ROOT / "backend" / "src"))
from lyrica_backend.text import lyric_text
home = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "io.lyricgen.desktop" / "analysis"
debug = args.bridge_dir or ROOT / "src-tauri" / "target" / "debug"
texts = lyric_text(args.lyrics.read_text(encoding="utf-8"))
request = {"operation":"analyze", "audio_path":str(args.audio.resolve()),
           "runtime_dir":str(home), "resource_dir":str(debug / "analysis"),
           "lines":[{"text":text} for text in texts],
           "options":{"engine":args.engine, "asr_model":"tiny", "language":args.language,
                      "device":"cpu", "separate":args.separate}}
result = subprocess.run([str(debug / ("lyrica-backend.exe" if os.name == "nt" else "lyrica-backend"))],
                        input=json.dumps(request, ensure_ascii=False), encoding="utf-8",
                        stdout=subprocess.PIPE, timeout=1800, check=False)
if result.returncode:
    raise SystemExit(result.stdout)
data = json.loads(result.stdout)
(ROOT / "build" / "smoke-analysis-result.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
if [line["text"] for line in data["lines"]] != texts:
    raise SystemExit("Original lyrics were changed")
times = [line["start"] for line in data["lines"] if line["start"] is not None]
if len(times) != len(texts) or times != sorted(times) or any(not 0 <= t <= data["duration"] for t in times):
    raise SystemExit(f"Smoke audio was not fully aligned: {data}")
print(f"Real-model smoke test passed: {len(times)} lines, duration={data['duration']:.2f}s, review={data['review_count']}")
