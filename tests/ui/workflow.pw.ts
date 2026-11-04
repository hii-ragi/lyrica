import { test, expect, type Page } from "@playwright/test";

async function desktop(page: Page, unresolved = false) {
  await page.addInitScript(({ unresolved }) => {
    const host = window as unknown as {
      isTauri: boolean; __TAURI_INTERNALS__: object; exports: unknown[];
      cancelled: boolean; analyzing: boolean;
    };
    host.isTauri = true;
    host.exports = [];
    const callbacks = new Map<number,unknown>();
    let callbackId = 1;
    host.__TAURI_INTERNALS__ = {
      transformCallback: (fn: unknown) => { const id = callbackId++; callbacks.set(id, fn); return id; },
      unregisterCallback: (id: number) => callbacks.delete(id),
      convertFileSrc: () => "http://127.0.0.1:1420/test-audio.wav",
      invoke: async (command: string, args: any) => {
        if (command === "plugin:event|listen") return 1;
        if (command === "restore_audio") return args.paths;
        if (command === "select_audio") return [
          { path: "F:/music/星.mp3", name: "星.mp3" }, { path: "F:/music/空.wav", name: "空.wav" },
        ];
        if (command === "select_lyrics") return [
          { name: "星.txt", text: "星の歌\n夜の歌" }, { name: "空.txt", text: "空の歌\n朝の歌" },
        ];
        if (command === "export_batch") { host.exports = args.tracks; return { saved: ["星.lrc","空.lrc"], errors: [] }; }
        if (command === "cancel_job") { host.cancelled = true; return; }
        if (command === "backend_job") {
          const request = args.request;
          if (request.operation === "runtime_status") return { ready: true };
          if (request.operation === "readings") return { lines: request.lines.map((line: any) => ({...line,reading:line.text})) };
          if (request.operation === "analyze") {
            host.analyzing = true;
            await new Promise(resolve => setTimeout(resolve, 150));
            if (host.cancelled) throw "処理をキャンセルしました";
            return { duration: 10, review_count: unresolved ? 1 : 0, unresolved_count: unresolved ? 1 : 0,
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
  }, { unresolved });
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
  await page.reload();
  await expect(page.locator("#status")).toContainText("前回の作業を復元");
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
