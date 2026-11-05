import { describe,expect,it } from "vitest";
import { processingOptions } from "./processing";
describe("処理デバイスの設定",()=>{
  it("未設定や未対応GPUはCPUで初期化する",()=>{
    expect(processingOptions(null).device).toBe("cpu");
    expect(processingOptions({device:"rocm"}).device).toBe("cpu");
  });
  it("CUDAの設定を保存・復元できる",()=>{
    const value=processingOptions({device:"cuda",cuda_compute_type:"float16",cuda_max_segment_seconds:10});
    expect(processingOptions(JSON.parse(JSON.stringify(value)))).toEqual(value);
  });
  it("VRAM向けの既定値と不正値の補正",()=>{
    expect(processingOptions({device:"cuda",cuda_compute_type:"invalid",cuda_max_segment_seconds:100}))
      .toMatchObject({device:"cuda",cuda_compute_type:"int8_float16",cuda_max_segment_seconds:15});
  });
});

it("詳細設定の保存・復元と旧設定への標準値補完",()=>{
  const legacy=processingOptions({device:"cuda",cuda_max_segment_seconds:10});
  expect(legacy).toMatchObject({beam_size:5,vad_enabled:true,vad_threshold:.5,min_agreement:.35,fallback_coverage:.75});
  const tuned=processingOptions({...legacy,beam_size:8,vad_enabled:false,vad_threshold:.2,min_agreement:.2,review_agreement:.4});
  expect(processingOptions(JSON.parse(JSON.stringify(tuned)))).toEqual(tuned);
});
it("不正な詳細値は標準へ補正し、標準オブジェクトを変更しない",()=>{
  const value=processingOptions({beam_size:99,vad_threshold:NaN,demucs_shifts:1.5,min_agreement:.8,review_agreement:.4});
  expect(value).toMatchObject({beam_size:5,vad_threshold:.5,demucs_shifts:1,min_agreement:.8,review_agreement:.8});
  value.beam_size=9;
  expect(processingOptions(null).beam_size).toBe(5);
});
