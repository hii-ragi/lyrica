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
