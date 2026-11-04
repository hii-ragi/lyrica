"""Install an isolated analysis environment with the bundled uv binary."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def python_path(home):
    return Path(home) / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def runtime_env(home, resources):
    home = Path(home)
    env = os.environ.copy()
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONPATH=str(resources),
               HF_HOME=str(home / "models"), TORCH_HOME=str(home / "models" / "torch"),
               NLTK_DATA=str(home / "nltk"), UV_CACHE_DIR=str(home / "uv-cache"),
               UV_PYTHON_INSTALL_DIR=str(home / "python"), UV_PYTHON_BIN_DIR=str(home / "bin"),
               UV_NO_PROGRESS="1", HF_HUB_DISABLE_SYMLINKS_WARNING="1",
               PATH=str(home / "bin") + os.pathsep + env.get("PATH", ""))
    env.pop("PYTHONHOME", None)
    return env


def fingerprint(resources):
    files = [Path(resources) / "requirements-analysis.txt", Path(resources) / "constraints-analysis.txt"]
    return hashlib.sha256(b"".join(path.read_bytes() for path in files if path.exists())).hexdigest()


def runtime_status(home, resources):
    home = Path(home)
    ready = False
    try:
        ready = (home / "ready.txt").read_text() == fingerprint(resources) and python_path(home).is_file()
    except OSError:
        pass
    return {"ready": ready, "path": str(home), "python": str(python_path(home))}


def setup_runtime(home, resources, uv, progress):
    home, resources, uv = Path(home), Path(resources), Path(uv)
    home.mkdir(parents=True, exist_ok=True)
    env = runtime_env(home, resources)
    marker = home / "ready.txt"
    marker.unlink(missing_ok=True)

    def run(args):
        subprocess.run([str(a) for a in args], env=env, check=True, stdout=sys.stderr,
                       stderr=sys.stderr, creationflags=0x08000000 if os.name == "nt" else 0)

    if not python_path(home).is_file():
        progress("setup", "解析用Python 3.12を準備しています")
        run([uv, "venv", home / "venv", "--python", "3.12", "--managed-python"])
    progress("setup", "WhisperX・Demucs・Sudachiを取得しています。初回は数GBの空き容量が必要です")
    run([uv, "pip", "install", "--python", python_path(home), "--index-strategy", "unsafe-best-match",
         "-r", resources / "requirements-analysis.txt"])
    progress("setup", "解析ライブラリと辞書の動作を確認しています")
    run([python_path(home), "-m", "lyrica_backend.worker", "--health"])
    marker.write_text(fingerprint(resources))
    return runtime_status(home, resources)


def run_worker(request, home, resources):
    if not runtime_status(home, resources)["ready"]:
        raise RuntimeError("解析環境が未準備です。「解析環境を準備」を実行してください")
    result = subprocess.run(
        [str(python_path(home)), "-m", "lyrica_backend.worker"],
        input=json.dumps(request, ensure_ascii=False), encoding="utf-8",
        stdout=subprocess.PIPE, stderr=sys.stderr, env=runtime_env(home, resources),
        creationflags=0x08000000 if os.name == "nt" else 0)
    try:
        response = json.loads(result.stdout)
    except ValueError as error:
        raise RuntimeError("解析プロセスが応答できませんでした。ログを確認してください") from error
    if result.returncode:
        raise RuntimeError(response.get("error", "解析に失敗しました"))
    return response
