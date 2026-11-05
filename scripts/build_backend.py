"""Build the small bridge, bundle uv, and copy the analysis source resources."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    import uv
    parser = argparse.ArgumentParser()
    parser.add_argument("--target")
    parser.add_argument("--work-dir", type=Path, default=ROOT / "build" / "pyinstaller",
                        help="Override the intermediate directory if an old build cache is locked")
    args = parser.parse_args()
    target = args.target
    if target is None:
        info = subprocess.check_output(["rustc", "-vV"], text=True)
        target = next(line.split(": ", 1)[1] for line in info.splitlines() if line.startswith("host: "))
    windows = sys.platform == "win32"
    if windows != ("windows" in target):
        raise SystemExit("Build the sidecar on the same OS as the target")
    name = "lyrica-backend"
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
        "--name", name, "--collect-data", "lyrica_backend", "--paths", str(ROOT / "backend" / "src"),
        "--exclude-module", "torch", "--exclude-module", "whisperx",
        "--exclude-module", "demucs", "--exclude-module", "sudachipy",
        "--distpath", str(ROOT / "build" / "sidecar"),
        "--workpath", str(args.work_dir), "--specpath", str(ROOT / "build"),
        str(ROOT / "backend" / "src" / "lyrica_backend" / "cli.py"),
    ], check=True, cwd=ROOT)
    suffix = ".exe" if windows else ""
    binaries = ROOT / "src-tauri" / "binaries"
    debug = ROOT / "src-tauri" / "target" / "debug"
    for folder in (binaries, debug):
        folder.mkdir(parents=True, exist_ok=True)
    for binary, source in ((name, ROOT / "build" / "sidecar" / f"{name}{suffix}"),
                           ("uv", Path(uv.find_uv_bin()))):
        shutil.copy2(source, binaries / f"{binary}-{target}{suffix}")
        shutil.copy2(source, debug / f"{binary}{suffix}")
    for resources in (ROOT / "src-tauri" / "resources" / "analysis", debug / "analysis"):
        resources.mkdir(parents=True, exist_ok=True)
        # Remove only the obsolete generated package, never the user's analysis environment.
        legacy = (resources / "lyricgen_backend").resolve()
        if not legacy.is_relative_to(ROOT.resolve()):
            raise RuntimeError("Generated resource path escaped the project")
        if legacy.is_dir():
            shutil.rmtree(legacy)
        shutil.copytree(ROOT / "backend" / "src" / "lyrica_backend",
                        resources / "lyrica_backend", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for filename in ("requirements-analysis.txt", "constraints-analysis.txt",
                         "requirements-analysis-cuda.txt", "constraints-analysis-cuda.txt"):
            shutil.copy2(ROOT / "backend" / filename, resources / filename)
    print("Built desktop bridge, uv, and analysis resources")


if __name__ == "__main__":
    main()
