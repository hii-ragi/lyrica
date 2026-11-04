"""Heavy dependencies live only in the managed Python environment."""
import contextlib
import json
import os
from pathlib import Path
import sys
import traceback

from lyrica_backend.device import register_cuda_libraries, friendly_error
register_cuda_libraries()


def progress(stage, message, completed=None, total=None):
    event = {"stage": stage, "message": message}
    if completed is not None and total is not None:
        event.update(completed=completed, total=total)
    print("LYRICA_EVENT " + json.dumps(event, ensure_ascii=False),
          file=sys.stderr, flush=True)


def health(device="cpu"):
    import imageio_ffmpeg
    import nltk
    import shutil
    import torch
    import whisperx.alignment
    from faster_whisper import WhisperModel
    import demucs.separate
    from lyrica_backend.text import Reader
    assert Reader().reading("歌詞")[0]
    if device == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("NVIDIA CUDAが利用できません。ドライバーを確認してください")
        import ctranslate2
        precision = ctranslate2.get_supported_compute_types("cuda",0)
        if "int8_float16" not in precision and "float16" not in precision:
            raise RuntimeError("このNVIDIA GPUの演算形式に対応していません")
        with torch.inference_mode():
            value = torch.ones((32,32),device="cuda")
            assert (value @ value).sum().item() > 0
            value = torch.nn.functional.conv1d(torch.ones((1,1,64),device="cuda"),torch.ones((1,1,3),device="cuda"))
            assert value.sum().item() > 0
        del value
        torch.cuda.empty_cache()
        print(f"CUDA OK: {torch.cuda.get_device_name(0)} / torch CUDA {torch.version.cuda}",file=sys.stderr)
    directory = Path(os.environ["NLTK_DATA"])
    directory.mkdir(parents=True, exist_ok=True)
    if not nltk.download("punkt_tab", download_dir=str(directory), quiet=True, raise_on_error=True):
        raise RuntimeError("文分割辞書をダウンロードできませんでした")
    target = Path(os.environ["TORCH_HOME"]).parent.parent / "bin"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), target / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"))
    print(f"Analysis runtime OK (torch {torch.__version__})", file=sys.stderr)


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        with contextlib.redirect_stdout(sys.stderr):
            if "--health" in sys.argv:
                device = sys.argv[sys.argv.index("--device")+1] if "--device" in sys.argv else "cpu"
                health(device)
                return 0
            request = json.load(sys.stdin)
            if request.get("operation") == "readings":
                from lyrica_backend.text import Reader, prepare_lines
                lines = request["lines"]
                response = {"lines": prepare_lines(lines, Reader())}
            elif request.get("operation") == "analyze":
                from lyrica_backend.pipeline import analyze
                response = analyze(request, progress)
            else:
                raise ValueError("未対応の解析処理です")
    except Exception as error:
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"error": friendly_error(error) if os.environ.get("LYRICA_DEVICE") == "cuda" else str(error)}, ensure_ascii=False), flush=True)
        return 1
    print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
