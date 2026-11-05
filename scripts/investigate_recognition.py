"""Investigate music recognition coverage without changing the production pipeline.

Run with the managed analysis Python. Results contain timing/counts, not full lyrics.
The audio must be obtained with permission; attribution is recorded separately.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "build/recognition-investigation")
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    parser.add_argument("--model", default="small")
    parser.add_argument("--lyrics", type=Path)
    args = parser.parse_args()
    work = args.output_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)

    from lyrica_backend.runtime import runtime_env
    home = Path(os.environ["LOCALAPPDATA"]) / "io.lyricgen.desktop/analysis"
    os.environ.update(runtime_env(home, ROOT / "src-tauri/target/debug/analysis", args.device))
    from lyrica_backend.device import register_cuda_libraries, release_gpu
    register_cuda_libraries()
    import numpy as np
    import torch
    import whisperx
    import imageio_ffmpeg
    from scipy.io import wavfile
    from lyrica_backend.pipeline import WhisperEngine
    from lyrica_backend.text import Reader, canonical, lyric_text, prepare_lines
    from lyrica_backend.alignment import coarse_windows

    torch.set_num_threads(min(8, os.cpu_count() or 4))
    reader = Reader()
    reference = prepare_lines([{"text": t} for t in lyric_text(args.lyrics.read_text(encoding="utf-8"))], reader) if args.lyrics else None
    cache = Path(os.environ["HF_HOME"])
    report = {"model": args.model, "device": args.device, "input": str(args.audio.resolve()),
              "source_code_sha256": hashlib.sha256((ROOT / "backend/src/lyrica_backend/pipeline.py").read_bytes()).hexdigest(),
              "profiles": {}}
    result_path = work / "recognition-metrics.json"

    def save():
        result_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=lambda value: value.item()), encoding="utf-8")

    def command(command):
        subprocess.run([str(x) for x in command], check=True,
                       creationflags=0x08000000 if os.name == "nt" else 0)

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    stereo = work / "source.wav"
    if not stereo.exists():
        command([ffmpeg, "-nostdin", "-v", "error", "-y", "-i", args.audio.resolve(),
                 "-t", "86400", "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", stereo])
    vocals = work / "stems/htdemucs/source/vocals.wav"
    if not vocals.exists():
        separation = [sys.executable, "-m", "demucs", "--two-stems", "vocals", "-n", "htdemucs",
                      "--device", args.device, "--out", work / "stems", "--float32", "--jobs", "0"]
        if args.device == "cuda":
            separation += ["--segment", "5", "--shifts", "1"]
        command([*separation, stereo])

    audio_by_name = {}
    for name, source in (("original", stereo), ("vocals", vocals)):
        target = work / (name + "-16k.wav")
        command([ffmpeg, "-nostdin", "-v", "error", "-y", "-i", source,
                 "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", target])
        rate, audio = wavfile.read(target)
        audio = audio.astype(np.float32) / 32768
        audio_by_name[name] = audio
        duration = len(audio) / rate
        bins = [{"start": start, "end": min(start + 20, duration),
                 "rms": float(np.sqrt(np.mean(audio[int(start * rate):int(min(start + 20, duration) * rate)] ** 2)))}
                for start in range(0, int(duration), 20)]
        report.setdefault("audio", {})[name] = {"duration": duration, "samples": len(audio),
                                                "sample_rate": rate, "rms_by_20s": bins}
    save()

    model = whisperx.load_model(args.model, args.device,
                               compute_type="int8_float16" if args.device == "cuda" else "int8",
                               language="ja", vad_method="silero", download_root=str(cache / "whisper"))

    def summarize(rows, duration):
        # Use exactly the same acceptance checks as coarse_windows; no original lyrics required.
        accepted, rejected = [], []
        for row in rows:
            normalized = canonical(reader.reading(row["text"])[0])
            start, end = float(row["start"]), float(row["end"])
            ok = bool(normalized) and 0 <= start < end <= duration + .1
            (accepted if ok else rejected).append(row)
        bins = [{"start": start, "end": min(start + 30, duration),
                 "items": sum(start <= r["start"] < start + 30 for r in rows),
                 "chars": sum(len(r["text"]) for r in rows if start <= r["start"] < start + 30)}
                for start in range(0, int(duration), 30)]
        matching = None
        if reference and accepted:
            windows = coarse_windows(reference, rows, duration, lambda t: canonical(reader.reading(t)[0]))
            matching = [{"line": i+1, "anchor_coverage": w["anchor_coverage"] if w else 0,
                         "start": w["start"] if w else None, "end": w["end"] if w else None}
                        for i,w in enumerate(windows)]
        return {"lyric_windows": matching, "items": len(rows), "chars": sum(len(r["text"]) for r in rows),
                "last_end": max((r["end"] for r in rows), default=None),
                "first_start": min((r["start"] for r in rows), default=None),
                "second_half_chars": sum(len(r["text"]) for r in rows if r["start"] >= duration / 2),
                "accepted_by_alignment": len(accepted), "rejected_by_alignment": len(rejected),
                "rejected_chars": sum(len(r["text"]) for r in rejected),
                "by_30s": bins,
                "segments": [{"start": r["start"], "end": r["end"], "chars": len(r["text"])} for r in rows],
                "text_sha256": hashlib.sha256("".join(r["text"] for r in rows).encode()).hexdigest()}

    def profile_app(label, audio, threshold=None):
        duration = len(audio) / 16000
        captured = {}
        vad = model.vad_model
        vad_class = type(vad)
        original_merge = vad_class.merge_chunks
        original_transcribe = model.transcribe
        old_threshold = vad.vad_onset
        old_params = dict(model._vad_params)
        if threshold is not None:
            vad.vad_onset = threshold
            model._vad_params.update(vad_onset=threshold, vad_offset=threshold * .726)

        def merge(raw, *args, **kwargs):
            captured["vad_raw"] = [{"start": float(s.start), "end": float(s.end)} for s in raw]
            merged = original_merge(raw, *args, **kwargs)
            captured["vad_merged"] = [{"start": s["start"], "end": s["end"]} for s in merged]
            return merged

        def transcribe(*args, **kwargs):
            result = original_transcribe(*args, **kwargs)
            captured["first_pass"] = summarize(result["segments"], duration)
            return result

        start = time.monotonic()
        rows = []
        try:
            with patch.object(vad_class, "merge_chunks", staticmethod(merge)), \
                 patch.object(model, "transcribe", side_effect=transcribe), \
                 patch.object(whisperx, "load_model", return_value=model):
                rows = WhisperEngine({"device": args.device, "asr_model": args.model,
                                      "engine": "whisperx", "language": "ja"}, cache).transcribe(audio, lambda *a: None)
        except ValueError as error:
            captured["error"] = str(error)
        finally:
            vad.vad_onset = old_threshold
            model._vad_params.clear()
            model._vad_params.update(old_params)
        captured.update(summary=summarize(rows, duration), duration=duration,
                        elapsed_seconds=time.monotonic()-start, threshold=threshold or old_threshold)
        report["profiles"][label] = captured
        save()
        print(label, json.dumps({k: captured["summary"][k] for k in ("items", "chars", "second_half_chars", "last_end", "rejected_by_alignment")}), flush=True)
        return rows

    def profile_direct(label, audio, vad, context=True):
        duration = len(audio) / 16000
        start = time.monotonic()
        segments, info = model.model.transcribe(audio, language="ja", word_timestamps=True,
                                               vad_filter=vad, beam_size=5, condition_on_previous_text=context)
        rows = []
        for segment in segments:
            if segment.words:
                rows.extend({"text": w.word, "start": w.start, "end": w.end} for w in segment.words)
            else:
                rows.append({"text": segment.text, "start": segment.start, "end": segment.end})
        report["profiles"][label] = {"summary": summarize(rows, duration), "duration": duration,
                                    "elapsed_seconds": time.monotonic()-start,
                                    "vad_filter": vad, "condition_on_previous_text": context,
                                    "duration_after_vad": info.duration_after_vad,
                                    "vad_options": asdict(info.vad_options) if info.vad_options else None}
        save()
        print(label, json.dumps({k: report["profiles"][label]["summary"][k] for k in ("items", "chars", "second_half_chars", "last_end", "rejected_by_alignment")}), flush=True)

    for name, audio in audio_by_name.items():
        profile_app(name + "_app", audio)
        profile_direct(name + "_direct_vad", audio, True)
        profile_direct(name + "_direct_no_vad", audio, False)
        profile_direct(name + "_direct_no_vad_no_context", audio, False, False)
        profile_app(name + "_app_low_vad", audio, .2)
        tail = audio[len(audio)//2:]
        tail_path = work / (name + "-tail-16k.wav")
        wavfile.write(tail_path, 16000, (tail * 32767).astype(np.int16))
        profile_app(name + "_tail_app", tail)
        report["profiles"][name + "_tail_app"]["source_offset"] = len(audio)//2 / 16000
        save()
    del model
    release_gpu(args.device)
    print("Saved", result_path, flush=True)


if __name__ == "__main__":
    main()
