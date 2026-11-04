export interface ProcessingOptions {
  device: "cpu" | "cuda";
  engine: "faster-whisper" | "whisperx";
  asr_model: "tiny" | "base" | "small" | "medium" | "large-v3";
  language: "ja" | "en";
  separate: boolean;
  align_model: string;
  cuda_compute_type: "int8_float16" | "float16";
  cuda_max_segment_seconds: 10 | 15 | 20;
}
export function processingOptions(input: unknown): ProcessingOptions {
  const value = input && typeof input === "object" ? input as Record<string,unknown> : {};
  return {
    device: value.device === "cuda" ? "cuda" : "cpu",
    engine: value.engine === "whisperx" ? "whisperx" : "faster-whisper",
    asr_model: ["tiny","base","small","medium","large-v3"].includes(String(value.asr_model))
      ? value.asr_model as ProcessingOptions["asr_model"] : "small",
    language: value.language === "en" ? "en" : "ja",
    separate: typeof value.separate === "boolean" ? value.separate : true,
    align_model: typeof value.align_model === "string" ? value.align_model.trim().slice(0,500) : "",
    cuda_compute_type: value.cuda_compute_type === "float16" ? "float16" : "int8_float16",
    cuda_max_segment_seconds: [10,15,20].includes(Number(value.cuda_max_segment_seconds))
      ? Number(value.cuda_max_segment_seconds) as 10|15|20 : 15,
  };
}
