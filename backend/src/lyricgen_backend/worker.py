"""Heavy dependencies live only in the managed Python environment."""
import contextlib
import json
import os
from pathlib import Path
import sys
import traceback


def progress(stage, message):
    print("LYRICGEN_EVENT " + json.dumps({"stage": stage, "message": message}, ensure_ascii=False),
          file=sys.stderr, flush=True)


def health():
    import imageio_ffmpeg
    import nltk
    import shutil
    import torch
    import whisperx.alignment
    from faster_whisper import WhisperModel
    import demucs.separate
    from lyricgen_backend.text import Reader
    assert Reader().reading("歌詞")[0]
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
                health()
                return 0
            request = json.load(sys.stdin)
            if request.get("operation") == "readings":
                from lyricgen_backend.text import Reader, prepare_lines
                lines = request["lines"]
                if request.get("language") == "en":
                    lines = [{**line, "reading": line.get("reading") or line["text"]} for line in lines]
                response = {"lines": prepare_lines(lines, Reader())}
            elif request.get("operation") == "analyze":
                from lyricgen_backend.pipeline import analyze
                response = analyze(request, progress)
            else:
                raise ValueError("未対応の解析処理です")
    except Exception as error:
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"error": str(error)}, ensure_ascii=False), flush=True)
        return 1
    print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
