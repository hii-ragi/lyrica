"""Manage separate CPU and NVIDIA CUDA environments, sharing downloaded models."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def validate_device(device):
    if device not in ("cpu", "cuda"):
        raise ValueError("処理デバイスはCPUまたはNVIDIA CUDAを指定してください")
    return device


def python_path(home, device="cpu"):
    validate_device(device)
    folder = "venv-cuda" if device == "cuda" else "venv"
    return Path(home) / folder / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def probe_nvidia():
    """Driver API only: no PyTorch import or installation is required."""
    try:
        if os.name == "nt":
            library = ctypes.WinDLL(str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/nvcuda.dll"))
        else:
            library = ctypes.CDLL("libcuda.so.1")
        count = ctypes.c_int()
        if library.cuInit(0) != 0 or library.cuDeviceGetCount(ctypes.byref(count)) != 0 or count.value < 1:
            return {"available":False,"reason":"NVIDIA GPUを利用できません"}
        name, memory, version = ctypes.create_string_buffer(256), ctypes.c_size_t(), ctypes.c_int()
        if library.cuDeviceGetName(name,256,0) != 0:
            return {"available":False,"reason":"NVIDIA GPUを確認できません"}
        library.cuDeviceTotalMem_v2(ctypes.byref(memory),0)
        library.cuDriverGetVersion(ctypes.byref(version))
        return {"available":True,"name":name.value.decode("utf-8",errors="replace"),
                "memory_mb":memory.value//(1024*1024),"driver_cuda_version":version.value}
    except (OSError, AttributeError):
        return {"available":False,"reason":"NVIDIAのCUDAドライバーが見つかりません"}


def runtime_env(home, resources, device="cpu"):
    validate_device(device)
    home = Path(home)
    python = python_path(home,device)
    torch_lib = python.parent.parent / "Lib/site-packages/torch/lib" if os.name == "nt" else python.parent.parent / "lib"
    env = os.environ.copy()
    paths = [str(home/"bin")]
    if device == "cuda":
        paths.insert(0,str(torch_lib))
    env.update(PYTHONUTF8="1",PYTHONIOENCODING="utf-8",PYTHONPATH=str(Path(resources).resolve()),
               HF_HOME=str(home/"models"),TORCH_HOME=str(home/"models/torch"),
               NLTK_DATA=str(home/"nltk"),UV_CACHE_DIR=str(home/"uv-cache"),
               UV_PYTHON_INSTALL_DIR=str(home/"python"),UV_PYTHON_BIN_DIR=str(home/"bin"),
               UV_NO_PROGRESS="1",HF_HUB_DISABLE_SYMLINKS_WARNING="1",
               LYRICA_DEVICE=device,PATH=os.pathsep.join(paths+[env.get("PATH","")]))
    env.pop("PYTHONHOME",None)
    return env


def fingerprint(resources, device="cpu"):
    validate_device(device)
    suffix = "-cuda" if device == "cuda" else ""
    files = [Path(resources)/f"requirements-analysis{suffix}.txt",
             Path(resources)/f"constraints-analysis{suffix}.txt"]
    return hashlib.sha256(b"".join(path.read_bytes() for path in files if path.exists())).hexdigest()


def runtime_status(home, resources, device="cpu"):
    validate_device(device)
    home = Path(home)
    marker = home/("ready-cuda.txt" if device == "cuda" else "ready.txt")
    ready = False
    try:
        ready = marker.read_text() == fingerprint(resources,device) and python_path(home,device).is_file()
    except OSError:
        pass
    gpu = probe_nvidia()
    if device == "cuda" and not gpu["available"]:
        ready = False
    return {"ready":ready,"device":device,"path":str(home),
            "python":str(python_path(home,device)),"gpu":gpu}


def setup_runtime(home, resources, uv, progress, device="cpu"):
    validate_device(device)
    home,resources,uv = Path(home),Path(resources),Path(uv)
    if device == "cuda" and not probe_nvidia()["available"]:
        raise RuntimeError("NVIDIA CUDAが利用できません。NVIDIAドライバーを確認するかCPUを選択してください")
    home.mkdir(parents=True,exist_ok=True)
    env = runtime_env(home,resources,device)
    marker = home/("ready-cuda.txt" if device == "cuda" else "ready.txt")
    marker.unlink(missing_ok=True)

    def run(args):
        subprocess.run([str(a) for a in args],env=env,check=True,stdout=sys.stderr,stderr=sys.stderr,
                       creationflags=0x08000000 if os.name == "nt" else 0)

    python = python_path(home,device)
    if not python.is_file():
        progress("setup",f"{'CUDA' if device == 'cuda' else 'CPU'}解析用Python 3.12を準備しています")
        run([uv,"venv",python.parent.parent,"--python","3.12","--managed-python"])
    progress("setup","CUDA対応ライブラリを取得しています（初回は数GB）" if device == "cuda"
             else "WhisperX・Demucs・Sudachiを取得しています")
    requirements = resources/("requirements-analysis-cuda.txt" if device == "cuda" else "requirements-analysis.txt")
    run([uv,"pip","install","--python",python,"--index-strategy","unsafe-best-match","-r",requirements])
    progress("setup","CUDAとNVIDIAライブラリの動作を確認しています" if device == "cuda"
             else "解析ライブラリと辞書の動作を確認しています")
    run([python,"-m","lyrica_backend.worker","--health","--device",device])
    marker.write_text(fingerprint(resources,device))
    return runtime_status(home,resources,device)


def run_worker(request, home, resources):
    device = request.get("options",{}).get("device","cpu") if request.get("operation") == "analyze" else request.get("device","cpu")
    validate_device(device)
    if not runtime_status(home,resources,device)["ready"]:
        name = "CUDA" if device == "cuda" else "CPU"
        raise RuntimeError(f"{name}解析環境が未準備です。処理デバイスを選び「解析環境を準備」を実行してください")
    result = subprocess.run([str(python_path(home,device)),"-m","lyrica_backend.worker"],
        input=json.dumps(request,ensure_ascii=False),encoding="utf-8",stdout=subprocess.PIPE,
        stderr=sys.stderr,env=runtime_env(home,resources,device),
        creationflags=0x08000000 if os.name == "nt" else 0)
    try:
        response = json.loads(result.stdout)
    except ValueError as error:
        raise RuntimeError("解析プロセスが応答できませんでした。ログを確認してください") from error
    if result.returncode:
        raise RuntimeError(response.get("error","解析に失敗しました"))
    return response
