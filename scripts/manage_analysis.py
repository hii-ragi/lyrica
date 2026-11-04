"""Prepare or inspect the same per-user runtime used by the installed application."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("operation", choices=["setup", "status", "analyze", "readings"])
parser.add_argument("--home", type=Path)
parser.add_argument("--request", type=Path, help="JSON request for analyze/readings")
args = parser.parse_args()
default = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "io.lyricgen.desktop" / "analysis"
home = args.home or default
debug = ROOT / "src-tauri" / "target" / "debug"
request = json.loads(args.request.read_text(encoding="utf-8")) if args.request else {}
request.update(operation={"setup": "setup_runtime", "status": "runtime_status"}.get(args.operation, args.operation),
               runtime_dir=str(home), resource_dir=str(debug / "analysis"),
               uv_path=str(debug / ("uv.exe" if os.name == "nt" else "uv")))
result = subprocess.run([str(debug / ("lyrica-backend.exe" if os.name == "nt" else "lyrica-backend"))],
                        input=json.dumps(request, ensure_ascii=False), encoding="utf-8", check=False)
raise SystemExit(result.returncode)
