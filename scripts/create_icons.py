"""Regenerate desktop and UI icons from the supplied logo without altering its artwork."""
from pathlib import Path
import os
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "logo.png"
if not source.is_file():
    raise SystemExit(f"Logo not found: {source}")
generated = ROOT / "build" / "logo-icons"
subprocess.run([
    "npm.cmd" if os.name == "nt" else "npm", "run", "tauri", "--", "icon",
    str(source), "--output", str(generated),
], check=True, cwd=ROOT)
icons = ROOT / "src-tauri" / "icons"
assets = ROOT / "src" / "assets"
public = ROOT / "public"
for directory in (icons, assets, public):
    directory.mkdir(parents=True, exist_ok=True)
for name in ("icon.png", "icon.ico"):
    shutil.copy2(generated / name, icons / name)
shutil.copy2(generated / "128x128@2x.png", assets / "logo.png")
shutil.copy2(generated / "32x32.png", public / "favicon.png")
print("Updated application icon, header logo, and favicon from logo.png")
