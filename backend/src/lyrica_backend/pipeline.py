"""Audio -> Demucs -> measured ASR word anchors -> WhisperX -> original lyric lines."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from lyrica_backend.alignment import aligned_line, apply_evidence, coarse_windows
from lyrica_backend.text import Reader, canonical, prepare_lines
from lyrica_backend.device import cuda_settings, release_gpu
from lyrica_backend.settings import analysis_options


def run_command(args):
    subprocess.run([str(arg) for arg in args], check=True, stdout=sys.stderr, stderr=sys.stderr,
                   creationflags=0x08000000 if os.name == "nt" else 0)


def demucs_command(source, output, options):
    options = analysis_options(options)
    device = options.get("device", "cpu")
    command = [sys.executable, "-m", "demucs", "--two-stems", "vocals", "-n", "htdemucs",
               "--device", device, "--out", output, "--float32", "--jobs", "0",
               "--shifts", str(options["demucs_shifts"]), "--overlap", str(options["demucs_overlap"])]
    if device == "cuda":
        command.extend(["--segment", str(options["cuda_demucs_segment"])])
    return [*command, source]


class WhisperEngine:
    def __init__(self, options, cache):
        self.options, self.cache = analysis_options(options), cache

    def transcribe(self, audio, progress):
        options = self.options
        device = options.get("device","cpu")
        compute_type = "int8" if device == "cpu" else cuda_settings(options)[0]
        progress("transcribe",f"音声認識と単語時刻を解析しています（{'CUDA' if device == 'cuda' else 'CPU'} / {compute_type}）")
        language = options.get("language","ja")
        decode = {"beam_size": options["beam_size"],
                  "no_speech_threshold": options["no_speech_threshold"],
                  "log_prob_threshold": options["log_prob_threshold"],
                  "condition_on_previous_text": options["condition_on_previous_text"]}
        model = pipeline = iterator = None
        try:
            if options.get("engine","faster-whisper") == "faster-whisper":
                from faster_whisper import WhisperModel
                model = WhisperModel(options.get("asr_model","small"),device=device,
                                     compute_type=compute_type,download_root=str(self.cache/"whisper"))
                iterator,_ = model.transcribe(audio,language=language,word_timestamps=True,
                                              vad_filter=options["vad_enabled"],
                                              vad_parameters={"threshold":options["vad_threshold"]}, **decode)
            else:
                import whisperx
                pipeline = whisperx.load_model(options.get("asr_model","small"),device,
                    compute_type=compute_type,language=language,vad_method="silero",
                    download_root=str(self.cache/"whisper"),
                    asr_options={"beam_size":options["beam_size"],
                                 "no_speech_threshold":options["no_speech_threshold"],
                                 "log_prob_threshold":options["log_prob_threshold"]},
                    vad_options={"vad_onset":options["vad_threshold"],
                                 "vad_offset":options["vad_threshold"]*.726,
                                 "chunk_size":options["whisperx_chunk_seconds"]})
                if options["vad_enabled"]:
                    coarse = pipeline.transcribe(audio,batch_size=1 if device == "cuda" else 4,
                                                  language=language,chunk_size=options["whisperx_chunk_seconds"])["segments"]
                    if not coarse:
                        raise ValueError("音声を認識できませんでした")
                    clips = [value for segment in coarse for value in (segment["start"],segment["end"])]
                else:
                    progress("transcribe","WhisperXのVAD付き一次認識を省略し、全音源から単語時刻を解析します")
                    clips = [0, len(audio)/16000]
                model = pipeline.model
                iterator,_ = model.transcribe(audio,language=language,word_timestamps=True,
                                              clip_timestamps=clips, **decode)
            segments = []
            duration = len(audio) / 16000
            processed = 0.0
            progress("transcribe", "音声認識を進めています", 0, duration)
            for segment in iterator:
                if segment.words:
                    segments.extend({"text":w.word,"start":w.start,"end":w.end} for w in segment.words)
                else:
                    segments.append({"text":segment.text,"start":segment.start,"end":segment.end})
                processed = max(processed, min(segment.end, duration))
                progress("transcribe", f"音声認識済み {processed:.1f} / {duration:.1f}秒", processed, duration)
            progress("transcribe", "音声認識が完了しました", duration, duration)
            return segments
        finally:
            iterator = pipeline = model = None
            release_gpu(device)

    def align(self, audio, lines, windows, progress, normalize):
        import torch
        import whisperx
        from contextlib import nullcontext
        device = self.options.get("device","cpu")
        limit = min(cuda_settings(self.options)[1], self.options["align_max_window_seconds"]) if device == "cuda" else self.options["align_max_window_seconds"]
        eligible = [window for window in windows if window and window["end"]-window["start"] <= limit]
        model = capture = None
        try:
            if eligible:
                progress("align",f"WhisperXアライメントモデルを準備しています（{'CUDA' if device == 'cuda' else 'CPU'}）")
                model,metadata = whisperx.load_align_model(
                    language_code=self.options.get("language","ja"),device=device,
                    model_name=self.options.get("align_model") or None,model_dir=str(self.cache/"align"))
                if device == "cuda":
                    model.half()
                model.eval()

                class Capture(torch.nn.Module):
                    def __init__(self,base):
                        super().__init__()
                        self.base,self.logits = base,None
                    def forward(self,*args,**kwargs):
                        result = self.base(*args,**kwargs)
                        self.logits = result.logits if hasattr(result,"logits") else result[0]
                        return result

                capture = Capture(model)
                labels = {value:key for key,value in metadata["dictionary"].items()}
                special = {"<pad>","[pad]","<s>","</s>","<unk>","[unk]"}
            output,previous = [],-1.0
            for index,(line,window) in enumerate(zip(lines,windows)):
                progress("align",f"歌詞の時刻を解析中 {index+1}/{len(lines)}行",index,len(lines))
                if window is None:
                    row = aligned_line(line,{},0,self.options)
                elif window["end"]-window["start"] > limit:
                    row = apply_evidence(aligned_line(line,{},window["anchor_coverage"],self.options),window,"",normalize,self.options)
                    if row["start"] is not None:
                        row["note"] = f"解析区間が{limit:g}秒を超えたため、音声認識の単語時刻を使用。同期を確認してください"
                        row["review"] = True
                else:
                    capture.logits = None
                    precision = torch.autocast(device_type="cuda",dtype=torch.float16) if device == "cuda" else nullcontext()
                    with precision:
                        result = whisperx.align(
                            [{"start":window["start"],"end":window["end"],"text":window["text"]}],
                            capture,metadata,audio,device,return_char_alignments=True)
                    row = aligned_line(line,result,window["anchor_coverage"],self.options)
                    decoded = ""
                    if capture.logits is not None:
                        ids = capture.logits.argmax(-1)[0].detach().cpu().tolist()
                        reduced = [token for pos,token in enumerate(ids) if pos == 0 or token != ids[pos-1]]
                        decoded = "".join(labels.get(token,"") for token in reduced
                                          if labels.get(token,"") not in special).replace("|"," ")
                    capture.logits = None
                    row = apply_evidence(row,window,decoded,normalize,self.options)
                if row["start"] is not None:
                    if row["start"] < previous:
                        row.update(start=None,end=None,review=True,confidence=0,
                                   note="時刻の順序が不確かなため手動修正が必要です")
                    else:
                        previous = row["start"]
                output.append(row)
                progress("align",f"歌詞の時刻を解析済み {index+1}/{len(lines)}行",index+1,len(lines))
                if device == "cuda":
                    torch.cuda.empty_cache()
            return output
        finally:
            capture = model = None
            release_gpu(device)


def analyze(request, progress, engine_factory=WhisperEngine, reader_factory=Reader):
    options = analysis_options(request.get("options", {}))
    import numpy as np
    import imageio_ffmpeg
    import torch
    from scipy.io import wavfile

    torch.set_num_threads(min(8,os.cpu_count() or 4))
    source = Path(request["audio_path"]).resolve()
    if not source.is_file() or source.suffix.lower() not in {
            ".wav",".mp3",".flac",".m4a",".aac",".ogg",".opus",".wma"}:
        raise ValueError("対応する音源ファイルを指定してください")
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
    device = options.get("device","cpu")
    gpu_name = None
    if device == "cuda":
        cuda_settings(options)
        torch.cuda.set_device(0)
        gpu_name = torch.cuda.get_device_name(0)
        progress("device",f"NVIDIA CUDAで処理します: {gpu_name}")
    else:
        progress("device","CPUで処理します")
    progress("reading","Sudachiで歌詞の読みを生成しています")
    reader = reader_factory()
    input_lines = request["lines"]
    lines = prepare_lines(input_lines,reader)
    cache = Path(os.environ.get("HF_HOME",Path.home()/".cache"/"lyrica"))
    cache.mkdir(parents=True,exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory(prefix="lyrica-") as directory:
        work = Path(directory)
        progress("preprocess","音源を前処理しています")
        stereo = work/"source.wav"
        run_command([ffmpeg,"-nostdin","-v","error","-y","-i",source,
                     "-t","86400","-ar","44100","-ac","2","-c:a","pcm_s16le",stereo])
        vocal = stereo
        if options.get("separate",True):
            progress("separate","Demucsでボーカルを分離しています（初回はモデルを取得）")
            run_command(demucs_command(stereo,work/"stems",options))
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

        windows = coarse_windows(lines,segments,duration,normalize,options)
        result = engine.align(audio,lines,windows,progress,normalize)
    for previous, following in zip(result,result[1:]):
        if previous["end"] is not None and following["start"] is not None and previous["end"] > following["start"] + .2:
            previous.update(review=True,note="次の行と解析範囲が重なっています。開始時刻を再生確認してください")
    progress("complete","解析が完了しました。再生して同期を確認してください")
    return {"lines":result,"duration":duration,"engine":options.get("engine","faster-whisper"),
            "device":device,"gpu_name":gpu_name,
            "review_count":sum(line["review"] for line in result),
            "unresolved_count":sum(line["start"] is None for line in result),
            "diagnostics":{"recognition":segments,"windows":windows,"options":options}}
