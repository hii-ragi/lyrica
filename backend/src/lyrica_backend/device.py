"""CUDA DLL registration and memory settings shared by worker and tests."""
import gc
import os
from pathlib import Path
import sys

_DLL_HANDLES = []


def register_cuda_libraries():
    if os.name == "nt" and os.environ.get("LYRICA_DEVICE") == "cuda":
        directory = Path(sys.prefix)/"Lib/site-packages/torch/lib"
        if directory.is_dir():
            _DLL_HANDLES.append(os.add_dll_directory(str(directory)))
            os.environ["PATH"] = str(directory)+os.pathsep+os.environ.get("PATH","")


def cuda_settings(options):
    precision = options.get("cuda_compute_type","int8_float16")
    if precision not in ("int8_float16","float16"):
        raise ValueError("CUDAの演算精度が不正です")
    seconds = options.get("cuda_max_segment_seconds",15)
    if isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or seconds not in (10,15,20):
        raise ValueError("CUDAの解析区間は10・15・20秒から選択してください")
    return precision,float(seconds)


def release_gpu(device):
    gc.collect()
    if device == "cuda":
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def friendly_error(error):
    message = str(error)
    lower = message.lower()
    if "out of memory" in lower or "cublas_status_alloc_failed" in lower:
        return "CUDAメモリが不足しました。tiny/baseなど小さいモデルか短い解析区間を選ぶか、CPUへ切り替えてください。"
    if any(word in lower for word in ("cublas64","cudnn","cudart64")) and any(word in lower for word in ("not found","cannot","could not","unable","missing")):
        return "CUDAライブラリを読み込めません。CUDA解析環境を再準備し、NVIDIAドライバーを確認してください。"
    return message
