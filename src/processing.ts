import schema from "../backend/src/lyrica_backend/settings.json";

export type NumericSetting = keyof typeof schema.numeric;
export type BooleanSetting = keyof typeof schema.boolean;
export interface NumericRule {
  default: number; min: number; max: number; step: number;
  group: string; label: string; help: string; device?: string; engine?: string;
}
export const numericSettings = Object.entries(schema.numeric) as [NumericSetting, NumericRule][];
export const booleanSettings = Object.entries(schema.boolean) as [BooleanSetting, typeof schema.boolean[BooleanSetting]][];
export interface ProcessingOptions extends Record<NumericSetting, number>, Record<BooleanSetting, boolean> {
  device: "cpu" | "cuda";
  engine: "faster-whisper" | "whisperx";
  asr_model: "tiny" | "base" | "small" | "medium" | "large-v3";
  language: "ja" | "en";
  separate: boolean;
  align_model: string;
  cuda_compute_type: "int8_float16" | "float16";
  cuda_max_segment_seconds: 10 | 15 | 20;
}
export const DEFAULT_OPTIONS: Readonly<ProcessingOptions> = Object.freeze({
  device:"cpu", engine:"faster-whisper", asr_model:"small", language:"ja",
  separate:true, align_model:"", cuda_compute_type:"int8_float16", cuda_max_segment_seconds:15,
  ...Object.fromEntries(numericSettings.map(([key, rule])=>[key,rule.default])) as Record<NumericSetting,number>,
  ...Object.fromEntries(booleanSettings.map(([key, rule])=>[key,rule.default])) as Record<BooleanSetting,boolean>,
});
export function processingOptions(input: unknown): ProcessingOptions {
  const value = input && typeof input === "object" ? input as Record<string,unknown> : {};
  const result: ProcessingOptions = {
    ...DEFAULT_OPTIONS,
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
  for (const [key, rule] of numericSettings) {
    const number = value[key];
    result[key] = typeof number === "number" && Number.isFinite(number)
      && number >= rule.min && number <= rule.max && (rule.step !== 1 || Number.isInteger(number))
      ? number : rule.default;
  }
  for (const [key, rule] of booleanSettings) {
    result[key] = typeof value[key] === "boolean" ? value[key] : rule.default;
  }
  result.review_agreement = Math.max(result.min_agreement,result.review_agreement);
  return result;
}
