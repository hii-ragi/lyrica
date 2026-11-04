"""Audio -> Demucs -> measured ASR word anchors -> WhisperX -> original lyric lines."""
import gc
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from lyricgen_backend.alignment import aligned_line, apply_evidence, coarse_windows
from lyricgen_backend.text import Reader, canonical, prepare_lines


def run_command(args):
    subprocess.run([str(arg) for arg in args], check=True, stdout=sys.stderr, stderr=sys.stderr,
                   creationflags=0x08000000 if os.name == "nt" else 0)


class WhisperEngine:
    def __init__(self, options, cache):
        self.options, self.cache = options, cache

    def transcribe(self, audio, progress):
        options = self.options
        progress("transcribe", "音声認識と単語時刻を解析しています（初回はモデルを取得）")
        device = options.get("device", "cpu")
        compute_type = "int8" if device == "cpu" else "float16"
        language = options.get("language", "ja")
        if options.get("engine", "faster-whisper") == "faster-whisper":
            from faster_whisper import WhisperModel
            model = WhisperModel(options.get("asr_model", "small"), device=device,
                                 compute_type=compute_type, download_root=str(self.cache / "whisper"))
            iterator, _ = model.transcribe(audio, language=language, word_timestamps=True,
                                          vad_filter=True, beam_size=5)
        else:
            import whisperx
            pipeline = whisperx.load_model(options.get("asr_model", "small"), device,
                                            compute_type=compute_type, language=language,
                                            vad_method="silero", download_root=str(self.cache / "whisper"))
            coarse = pipeline.transcribe(audio, batch_size=4, language=language)["segments"]
            if not coarse:
                raise ValueError("音声を認識できませんでした")
            clips = [value for segment in coarse for value in (segment["start"],segment["end"])]
            model = pipeline.model
            iterator, _ = model.transcribe(audio, language=language, word_timestamps=True,
                                          clip_timestamps=clips, beam_size=5)
        segments = []
        for segment in iterator:
            if segment.words:
                segments.extend({"text":w.word,"start":w.start,"end":w.end} for w in segment.words)
            else:
                segments.append({"text":segment.text,"start":segment.start,"end":segment.end})
        del model
        gc.collect()
        return segments

    def align(self, audio, lines, windows, progress, normalize):
        if not any(windows):
            return [aligned_line(line, {}, 0) for line in lines]
        import torch
        import whisperx
        device = self.options.get("device", "cpu")
        progress("align", "WhisperXのアライメントモデルを準備しています（初回はダウンロード）")
        model, metadata = whisperx.load_align_model(
            language_code=self.options.get("language", "ja"), device=device,
            model_name=self.options.get("align_model") or None, model_dir=str(self.cache / "align"))

        class Capture(torch.nn.Module):
            def __init__(self, base):
                super().__init__()
                self.base, self.logits = base, None
            def forward(self, *args, **kwargs):
                result = self.base(*args, **kwargs)
                self.logits = result.logits if hasattr(result, "logits") else result[0]
                return result

        capture = Capture(model)
        labels = {value:key for key,value in metadata["dictionary"].items()}
        special = {"<pad>","[pad]","<s>","</s>","<unk>","[unk]"}
        output, previous = [], -1.0
        for index, (line, window) in enumerate(zip(lines, windows)):
            progress("align", f"歌詞の時刻を解析中 {index + 1}/{len(lines)}")
            if window is None:
                row = aligned_line(line, {}, 0)
            else:
                capture.logits = None
                result = whisperx.align(
                    [{"start":window["start"],"end":window["end"],"text":window["text"]}],
                    capture, metadata, audio, device, return_char_alignments=True)
                row = aligned_line(line, result, window["anchor_coverage"])
                decoded = ""
                if capture.logits is not None:
                    ids = capture.logits.argmax(-1)[0].detach().cpu().tolist()
                    reduced = [token for pos,token in enumerate(ids) if pos == 0 or token != ids[pos-1]]
                    decoded = "".join(labels.get(token,"") for token in reduced
                                      if labels.get(token,"") not in special).replace("|"," ")
                row = apply_evidence(row, window, decoded, normalize)
            if row["start"] is not None:
                if row["start"] < previous:
                    row.update(start=None,end=None,review=True,confidence=0,
                               note="時刻の順序が不確かなため手動修正が必要です")
                else:
                    previous = row["start"]
            output.append(row)
        del capture, model
        gc.collect()
        return output


def analyze(request, progress, engine_factory=WhisperEngine, reader_factory=Reader):
    import numpy as np
    import imageio_ffmpeg
    import torch
    from scipy.io import wavfile

    torch.set_num_threads(min(8,os.cpu_count() or 4))
    source = Path(request["audio_path"]).resolve()
    if not source.is_file() or source.suffix.lower() not in {
            ".wav",".mp3",".flac",".m4a",".aac",".ogg",".opus",".wma"}:
        raise ValueError("対応する音源ファイルを指定してください")
    options = request.get("options", {})
    if options.get("device","cpu") not in ("cpu","cuda"):
        raise ValueError("処理デバイスが不正です")
    if options.get("device") == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDAが利用できません。CPUを指定してください")
    if options.get("engine","faster-whisper") not in ("faster-whisper","whisperx"):
        raise ValueError("解析エンジンが不正です")
    if options.get("asr_model","small") not in ("tiny","base","small","medium","large-v3"):
        raise ValueError("音声認識モデルが不正です")
    if options.get("language","ja") not in ("ja","en"):
        raise ValueError("対応言語は日本語・英語です")
    progress("reading","Sudachiで歌詞の読みを生成しています")
    reader = reader_factory()
    input_lines = request["lines"]
    if options.get("language","ja") == "en":
        input_lines = [{**line,"reading":line.get("reading") or line["text"]} for line in input_lines]
    lines = prepare_lines(input_lines,reader)
    cache = Path(os.environ.get("HF_HOME",Path.home()/".cache"/"lyricgen"))
    cache.mkdir(parents=True,exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory(prefix="lyricgen-") as directory:
        work = Path(directory)
        progress("preprocess","音源を前処理しています")
        stereo = work/"source.wav"
        run_command([ffmpeg,"-nostdin","-v","error","-y","-i",source,
                     "-t","86400","-ar","44100","-ac","2","-c:a","pcm_s16le",stereo])
        vocal = stereo
        if options.get("separate",True):
            progress("separate","Demucsでボーカルを分離しています（初回はモデルを取得）")
            run_command([sys.executable,"-m","demucs","--two-stems","vocals","-n","htdemucs",
                         "--device",options.get("device","cpu"),"--out",work/"stems",
                         "--float32","--jobs","0",stereo])
            vocal = work/"stems"/"htdemucs"/"source"/"vocals.wav"
            if not vocal.is_file():
                raise RuntimeError("Demucsのボーカル出力が見つかりません")
        mono = work/"alignment.wav"
        run_command([ffmpeg,"-nostdin","-v","error","-y","-i",vocal,
                     "-ar","16000","-ac","1","-c:a","pcm_s16le",mono])
        rate,data = wavfile.read(mono)
        audio = data.astype(np.float32)/32768
        duration = len(audio)/rate
        if duration <= .1:
            raise ValueError("音源が短すぎるか、音声が含まれていません")
        engine = engine_factory(options,cache)
        segments = engine.transcribe(audio,progress)

        def normalize(text):
            return canonical(text if options.get("language","ja") == "en" else reader.reading(text)[0])

        windows = coarse_windows(lines,segments,duration,normalize)
        result = engine.align(audio,lines,windows,progress,normalize)
    for previous, following in zip(result,result[1:]):
        if previous["end"] is not None and following["start"] is not None and previous["end"] > following["start"] + .2:
            previous.update(review=True,note="次の行と解析範囲が重なっています。開始時刻を再生確認してください")
    progress("complete","解析が完了しました。再生して同期を確認してください")
    return {"lines":result,"duration":duration,"engine":options.get("engine","faster-whisper"),
            "review_count":sum(line["review"] for line in result),
            "unresolved_count":sum(line["start"] is None for line in result),
            "diagnostics":{"recognition":segments,"windows":windows}}
