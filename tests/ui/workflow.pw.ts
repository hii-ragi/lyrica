import { test, expect, type Page } from "@playwright/test";

async function desktop(page: Page, unresolved = false, nvidia = true) {
  await page.addInitScript(({ unresolved, nvidia }) => {
    const host = window as unknown as {
      isTauri: boolean; __TAURI_INTERNALS__: object; exports: unknown[]; exportFormat: string;
      cancelled: boolean; analyzing: boolean; cudaReady: boolean; requests: any[]; holdAnalysis: boolean; failNext: boolean;
      emitProgress: (payload: any) => void;
    };
    host.isTauri = true;
    host.exports = [];
    host.cudaReady = localStorage.getItem('test-cuda-ready') === '1';
    host.requests = [];
    const callbacks = new Map<number,unknown>();
    let callbackId = 1;
    let progressHandler = 0;
    let jobId = "";
    host.emitProgress = (payload: any) => {
      const callback = callbacks.get(progressHandler) as ((event: any) => void) | undefined;
      callback?.({event:"analysis-progress",id:1,payload:{job_id:jobId,...payload}});
    };
    host.__TAURI_INTERNALS__ = {
      transformCallback: (fn: unknown) => { const id = callbackId++; callbacks.set(id, fn); return id; },
      unregisterCallback: (id: number) => callbacks.delete(id),
      convertFileSrc: () => "http://127.0.0.1:1420/test-audio.wav",
      invoke: async (command: string, args: any) => {
        if (command === "plugin:event|listen") {
          if (args.event === "analysis-progress") progressHandler = args.handler;
          return 1;
        }
        if (command === "restore_audio") return args.paths;
        if (command === "select_audio") return [
          { path: "F:/music/星.mp3", name: "星.mp3" }, { path: "F:/music/空.wav", name: "空.wav" },
        ];
        if (command === "select_lyrics") return [
          { name: "星.txt", text: "星の歌\n夜の歌" }, { name: "空.txt", text: "空の歌\n朝の歌" },
        ];
        if (command === "export_batch") { host.exports = args.tracks; host.exportFormat = args.format; return { saved: ["星.lrc","空.lrc"], errors: [] }; }
        if (command === "cancel_job") { host.cancelled = true; return; }
        if (command === "backend_job") {
          const request = args.request;
          host.requests.push(request);
          if (request.operation === "runtime_status") return {
            ready: request.device === "cuda" ? nvidia && host.cudaReady : true,
            device: request.device ?? "cpu", gpu: {available:nvidia,name:"Test NVIDIA GPU",memory_mb:4096,reason:"NVIDIA GPUが見つかりません"},
          };
          if (request.operation === "setup_runtime") {
            if (request.device === "cuda") {host.cudaReady=true;localStorage.setItem("test-cuda-ready","1");}
            return {ready:true,device:request.device,gpu:{available:nvidia,name:"Test NVIDIA GPU",memory_mb:4096}};
          }
          if (request.operation === "readings") return { lines: request.lines.map((line: any) => ({...line,reading:line.text})) };
          if (request.operation === "analyze") {
            host.analyzing = true;
            jobId = args.jobId;
            host.emitProgress({stage:"separate",message:"ボーカルを分離しています"});
            while (host.holdAnalysis && !host.cancelled) await new Promise(resolve=>setTimeout(resolve,20));
            await new Promise(resolve => setTimeout(resolve, 150));
            if (host.cancelled) throw "処理をキャンセルしました";
            if (host.failNext) {host.failNext=false;throw "解析エラー";}
            return { device:request.options.device,gpu_name:request.options.device === "cuda" ? "Test NVIDIA GPU" : null, duration: 10, review_count: unresolved ? 1 : 0, unresolved_count: unresolved ? 1 : 0,
              lines: request.lines.map((line: any,index: number) => ({
                ...line, reading: line.text, start: unresolved && index === 0 ? null : 1+index*3,
                end: 3+index*3, review: unresolved && index === 0, confidence: .9, note: "",
              })) };
          }
          if (request.operation === "render_lrc") return { lrc: "[00:01.00]" + request.lines[0].text };
        }
        return null;
      },
    };
  }, { unresolved, nvidia });
  const wav = Buffer.alloc(44+16000*2*10);
  wav.write("RIFF",0);wav.writeUInt32LE(wav.length-8,4);wav.write("WAVEfmt ",8);
  wav.writeUInt32LE(16,16);wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);
  wav.writeUInt32LE(16000,24);wav.writeUInt32LE(32000,28);wav.writeUInt16LE(2,32);
  wav.writeUInt16LE(16,34);wav.write("data",36);wav.writeUInt32LE(wav.length-44,40);
  await page.route("**/test-audio.wav", route => {
    const range = route.request().headers()["range"];
    if (range) {
      const match = range.match(/bytes=(\d+)-(\d*)/)!;
      const start = Number(match[1]); const end = match[2] ? Number(match[2]) : wav.length - 1;
      return route.fulfill({status:206,contentType:"audio/wav",body:wav.subarray(start,end+1),
        headers:{"Accept-Ranges":"bytes","Content-Range":`bytes ${start}-${end}/${wav.length}`,"Content-Length":String(end-start+1)}});
    }
    return route.fulfill({contentType:"audio/wav",body:wav,headers:{"Accept-Ranges":"bytes"}});
  });
  await page.goto("/");
  await expect(page.locator("#environment")).toHaveText("解析環境：準備済み");
  await page.locator("#add-audio").click();
  await page.locator("#add-lyrics").click();
}

test("曲の一括登録→解析→同期修正→プレビュー→一括保存", async ({page}) => {
  const errors: string[] = [];
  page.on("pageerror",error=>errors.push(error.message));
  await desktop(page);
  await expect(page).toHaveTitle("Lyrica");
  await expect(page.getByRole("heading",{name:"Lyrica",exact:true})).toBeVisible();
  await expect(page.locator("#tracks li")).toHaveCount(2);
  await expect(page.locator("#lyrics")).toHaveValue("星の歌\n夜の歌");
  await page.locator("#analyze-all").click();
  await expect(page.locator("#status")).toContainText("2曲完了");
  await expect(page.locator("#rows tr")).toHaveCount(2);
  await page.getByLabel("1行目の同期を確認済みにする").uncheck();
  await expect(page.getByLabel("1行目の同期を確認済みにする")).not.toBeChecked();
  await page.getByLabel("1行目の同期を確認済みにする").check();
  await expect(page.getByLabel("1行目の開始時刻（秒）")).toHaveValue("1");
  await expect.poll(() => page.locator("#player").evaluate((audio: HTMLAudioElement) => audio.readyState)).toBeGreaterThanOrEqual(1);
  await page.locator("#player").evaluate((audio: HTMLAudioElement) => { audio.currentTime = 2.5; });
  await expect(page.locator("#player")).toHaveJSProperty("currentTime",2.5);
  await page.locator("#rows tr").first().getByRole("button",{name:"再生位置"}).click();
  await expect(page.getByLabel("1行目の開始時刻（秒）")).toHaveValue("2.5");
  await page.locator("#preview-lrc").click();
  await expect(page.locator("#output")).toHaveValue(/星の歌/);
  await page.locator("#export-all").click();
  await expect(page.locator("#status")).toContainText("2曲を保存");
  const exported = await page.evaluate(()=>(window as any).exports);
  expect(exported[0].lines[0].start).toBe(2.5);
  expect(errors).toEqual([]);
  await page.screenshot({path:"build/ui-preview.png",fullPage:true});
  await page.evaluate(() => {
    const saved = localStorage.getItem("lyrica-workspace-v1");
    if (!saved) throw new Error("Workspace was not saved");
    localStorage.setItem("lyricgen-workspace-v1",saved);
    localStorage.removeItem("lyrica-workspace-v1");
  });
  await page.reload();
  await expect(page.locator("#status")).toContainText("前回の作業を復元");
  expect(await page.evaluate(() => localStorage.getItem("lyricgen-workspace-v1"))).toBeNull();
  expect(await page.evaluate(() => localStorage.getItem("lyrica-workspace-v1"))).not.toBeNull();
  await expect(page.getByLabel("1行目の開始時刻（秒）")).toHaveValue("2.5");
});

test("時刻未確定の曲は保存対象にせず、手動修正で保存可能になる", async ({page}) => {
  await desktop(page,true);
  await page.locator("#analyze-one").click();
  await expect(page.locator("#status")).toContainText("1曲完了");
  await page.locator("#export-all").click();
  await expect(page.locator("#status")).toContainText("保存できる曲がありません");
  await page.getByLabel("1行目の開始時刻（秒）").fill("1.25");
  await page.getByLabel("1行目の開始時刻（秒）").press("Tab");
  await page.locator("#export-all").click();
  await expect(page.locator("#status")).toContainText("保存しました");
});

test("キャンセル後に次の曲を解析しない", async ({page}) => {
  await desktop(page);
  await page.locator("#analyze-all").click();
  await page.locator("#cancel").click();
  await expect(page.locator("#status")).toContainText("処理をキャンセルしました");
  await expect(page.locator("#tracks li").nth(1)).toContainText("解析待ち");
});

test("ブラウザーだけではデスクトップ解析を実行しない", async ({page}) => {
  await page.goto("/");
  await expect(page.locator("#status")).toContainText("デスクトップアプリを起動");
  await expect(page.locator("#add-audio")).toBeDisabled();
});

test("CUDA環境を準備してGPUを指定し、設定を復元してCPUへ戻せる", async ({page})=>{
  await desktop(page);
  await page.locator("#device").selectOption("cuda");
  await expect(page.locator("#environment")).toHaveText("CUDA環境：未準備");
  await expect(page.locator("#analyze-one")).toBeDisabled();
  await page.locator("#setup").click();
  await expect(page.locator("#environment")).toHaveText("CUDA環境：準備済み");
  await page.locator("#analyze-one").click();
  await expect(page.locator("#status")).toContainText("1曲完了");
  await expect(page.locator("#track-status")).toContainText("CUDA解析済み");
  const request=await page.evaluate(()=>(window as any).requests.findLast((item:any)=>item.operation==="analyze"));
  expect(request.options).toMatchObject({device:"cuda",cuda_compute_type:"int8_float16",cuda_max_segment_seconds:15});
  await page.screenshot({path:"build/ui-preview-cuda.png",fullPage:true});
  await page.reload();
  await expect(page.locator("#device")).toHaveValue("cuda");
  await expect(page.locator("#environment")).toHaveText("CUDA環境：準備済み");
  await page.locator("#device").selectOption("cpu");
  await expect(page.locator("#environment")).toHaveText("解析環境：準備済み");
  await expect(page.locator("#analyze-one")).toBeEnabled();
});

test("NVIDIA GPUがない場合はCUDA解析を開始できない",async({page})=>{
  await desktop(page,false,false);
  await page.locator("#device").selectOption("cuda");
  await expect(page.locator("#environment")).toHaveText("CUDA環境：未準備");
  await expect(page.locator("#device-note")).toContainText("NVIDIA GPUが見つかりません");
  await expect(page.locator("#setup")).toBeDisabled();
  await expect(page.locator("#analyze-all")).toBeDisabled();
  await page.locator("#device").selectOption("cpu");
  await expect(page.locator("#environment")).toHaveText("解析環境：準備済み");
});

test("実際の進捗イベントでバーを更新し、ログと別ジョブを無視する",async({page})=>{
  await desktop(page);
  await page.evaluate(()=>(window as any).holdAnalysis=true);
  await page.locator("#analyze-all").click();
  await expect(page.locator("#stage-progress-label")).toHaveText("ボーカルを分離しています");
  await expect(page.locator("#stage-progress")).not.toHaveAttribute("value");
  await expect(page.locator("#batch-progress")).toHaveJSProperty("value",0);
  await page.evaluate(()=>(window as any).emitProgress({stage:"align",message:"歌詞の時刻を解析済み 1/2行",completed:1,total:2}));
  await expect(page.locator("#stage-progress")).toHaveJSProperty("value",1);
  await expect(page.locator("#stage-progress")).toHaveJSProperty("max",2);
  await expect(page.locator("#stage-progress-label")).toContainText("50%");
  await page.evaluate(()=>{
    (window as any).emitProgress({stage:"log",message:"詳細ログ"});
    (window as any).emitProgress({job_id:"old-job",stage:"align",message:"古いジョブ",completed:2,total:2});
  });
  await expect(page.locator("#stage-progress-label")).toContainText("50%");
  await page.screenshot({path:"build/ui-preview-progress.png",fullPage:true});
  await page.evaluate(()=>(window as any).holdAnalysis=false);
  await expect(page.locator("#status")).toContainText("2曲完了");
  await expect(page.locator("#batch-progress")).toHaveJSProperty("value",2);
  await expect(page.locator("#batch-progress-label")).toHaveText("処理済み 2 / 2曲（成功 2・失敗 0）・終了");
  await expect(page.locator("#stage-progress")).toBeHidden();
});

test("失敗した曲も全体の処理済み件数に含め、成功と区別する",async({page})=>{
  await desktop(page);
  await page.evaluate(()=>(window as any).failNext=true);
  await page.locator("#analyze-all").click();
  await expect(page.locator("#status")).toContainText("1曲完了、1曲失敗");
  await expect(page.locator("#batch-progress-label")).toHaveText("処理済み 2 / 2曲（成功 1・失敗 1）・終了");
  await expect(page.locator("#stage-progress")).toBeHidden();
});

test("キャンセル時は未完了の曲を加算せず進捗表示を停止する",async({page})=>{
  await desktop(page);
  await page.evaluate(()=>(window as any).holdAnalysis=true);
  await page.locator("#analyze-all").click();
  await expect(page.locator("#stage-progress-label")).toContainText("ボーカル");
  await page.locator("#cancel").click();
  await expect(page.locator("#status")).toContainText("処理をキャンセルしました");
  await expect(page.locator("#batch-progress-label")).toHaveText("処理済み 0 / 2曲（成功 0・失敗 0）・キャンセル");
  await expect(page.locator("#stage-progress")).toBeHidden();
});

test("保存形式TXTを選択して一括保存に渡し、元ファイルの行番号を保持する",async({page})=>{
  await desktop(page);
  await page.locator("#lyrics").fill("宇宙(そら)\n\n君とFly away");
  await page.locator("#analyze-one").click();
  await expect(page.locator("#status")).toContainText("1曲完了");
  await expect(page.locator("#rows tr").nth(1).locator("td").first()).toHaveText("3");
  await page.locator("#export-format").selectOption("txt");
  await page.locator("#export-all").click();
  await expect(page.locator("#status")).toContainText("保存しました");
  const saved=await page.evaluate(()=>({format:(window as any).exportFormat,tracks:(window as any).exports}));
  expect(saved.format).toBe("txt");
  expect(saved.tracks[0].lines.map((line:any)=>[line.text,line.source_line])).toEqual([["宇宙(そら)",1],["君とFly away",3]]);
});
