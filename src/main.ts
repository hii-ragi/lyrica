import { convertFileSrc, invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { activeLine, clock, exportable, reconcileRows, restoreTracks, rowsFromText, stem, type LyricRow, type Track } from "./model";
import { DEFAULT_OPTIONS, processingOptions } from "./processing";
import { ProgressView, type ProgressEvent } from "./progress";
import { createAdvancedSettings, readAdvancedSettings, applyAdvancedSettings, advancedControls, validSettings } from "./settings-ui";
import "./style.css";

createAdvancedSettings();

const progress = new ProgressView();

const element = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const button = (id: string) => element<HTMLButtonElement>(id);
const player = element<HTMLAudioElement>("player");
const lyrics = element<HTMLTextAreaElement>("lyrics");
const output = element<HTMLTextAreaElement>("output");
const tbody = element<HTMLTableSectionElement>("rows");
const tracks: Track[] = [];
let selected = "";
let ready = false;
let busy = false;
let checkingRuntime = false;
interface GPUInfo { available: boolean; name?: string; memory_mb?: number; reason?: string; }
interface RuntimeInfo { ready: boolean; device?: string; gpu?: GPUInfo; }
let gpuInfo: GPUInfo | undefined;
const selectedDevice = () => element<HTMLSelectElement>("device").value;

let stopRequested = false;
let activeJob: string | null = null;
let currentTrack: string | null = null;
const log: string[] = [];

function selectedTrack() { return tracks.find(t => t.id === selected); }
function message(text: string) { element("status").textContent = text; }
function errorText(error: unknown) { return error instanceof Error ? error.message : String(error); }
function addLog(text: string) {
  log.push(text);
  if (log.length > 60) log.shift();
  element("log").textContent = log.join("\n");
}
function controls() {
  const locked = busy || checkingRuntime;
  const cuda = selectedDevice() === "cuda";
  for (const id of ["setup","add-audio","add-lyrics","export-all","remove-track","reset-settings"]) button(id).disabled = locked;
  button("setup").disabled ||= cuda && gpuInfo?.available === false;
  for (const id of ["analyze-all","analyze-one","readings"]) button(id).disabled = locked || !ready;
  button("preview-lrc").disabled = locked;
  button("cancel").disabled = !busy || stopRequested;
  lyrics.disabled = locked;
  document.querySelectorAll<HTMLInputElement | HTMLSelectElement>(".options input,.options select")
    .forEach(input => { input.disabled = locked; });
  element<HTMLSelectElement>("cuda-compute-type").disabled = locked || !cuda;
  element<HTMLSelectElement>("cuda-max-segment").disabled = locked || !cuda;
  advancedControls(locked, selectedDevice(), element<HTMLSelectElement>("engine").value, element<HTMLInputElement>("separate").checked);
  tbody.querySelectorAll<HTMLInputElement>("input").forEach(input => { input.disabled = locked; });
  tbody.querySelectorAll<HTMLButtonElement>("button[data-stamp]").forEach(input => { input.disabled = locked; });
  const label = cuda ? "CUDA環境" : "解析環境";
  element("environment").textContent = checkingRuntime ? label+"：確認中…" : label+(ready ? "：準備済み" : "：未準備");
  button("setup").textContent = cuda ? (ready ? "CUDA環境を再確認・修復" : "CUDA解析環境を準備")
    : (ready ? "解析環境を再確認・修復" : "解析環境を準備");
  element("setup-help").textContent = cuda
    ? "NVIDIA GPU用のライブラリを取得します。初回は数GBの空き容量とインターネット接続が必要です。CPU環境も引き続き使えます。"
    : "初回は専用のPython環境と解析ライブラリを取得します。数GBの空き容量とインターネット接続が必要です。";
  element("device-note").textContent = cuda
    ? (gpuInfo?.available
        ? `NVIDIA GPU：${gpuInfo.name}（${((gpuInfo.memory_mb ?? 0)/1024).toFixed(1)}GB）。${ready ? "CUDAで解析できます。" : "CUDA解析環境を準備してください。"}`
        : gpuInfo?.reason ?? "NVIDIA GPUとCUDA環境を確認しています。")
    : "CPUで処理します。NVIDIA GPUを使う場合は「NVIDIA CUDA」を選んでください。";
}

function persist() {
  try { localStorage.setItem("lyrica-workspace-v1",JSON.stringify({tracks,selected})); localStorage.removeItem("lyricgen-workspace-v1"); }
  catch { addLog("作業状態を自動保存できませんでした。LRCを保存してから終了してください。"); }
}
function renderList() {
  persist();
  const list = element("tracks");
  list.replaceChildren();
  for (const track of tracks) {
    const li = document.createElement("li");
    const item = document.createElement("button");
    item.className = track.id === selected ? "track selected" : "track";
    item.setAttribute("aria-current", track.id === selected ? "true" : "false");
    const name = document.createElement("strong"); name.textContent = track.name;
    const status = document.createElement("span"); status.textContent = track.status;
    item.append(name, status);
    item.addEventListener("click", () => { selected = track.id; renderList(); renderEditor(); });
    li.append(item); list.append(li);
  }
  element("track-count").textContent = String(tracks.length);
  element("empty-list").hidden = tracks.length > 0;
}
function invalidatePreview() { output.value = ""; }
function renderRows(track: Track) {
  persist();
  tbody.replaceChildren();
  track.lines.forEach((line, index) => {
    const row = document.createElement("tr");
    row.dataset.index = String(index);
    row.classList.toggle("review", line.review || line.start === null);
    const number = document.createElement("td"); number.textContent = String(line.source_line ?? index + 1);
    const time = document.createElement("td");
    const start = document.createElement("input");
    start.type = "number"; start.min = "0"; start.max = String(track.duration ?? 86400); start.step = ".01";
    start.value = line.start === null ? "" : String(line.start);
    start.setAttribute("aria-label", `${index + 1}行目の開始時刻（秒）`);
    start.addEventListener("change", () => {
      line.start = start.value.trim() === "" ? null : Number(start.value);
      line.review = line.start === null; line.note = line.start === null ? "開始時刻を指定してください" : "手動修正";
      invalidatePreview(); renderRows(track);
    });
    const seek = document.createElement("button"); seek.className = "quiet";
    seek.textContent = "移動"; seek.disabled = line.start === null;
    seek.addEventListener("click", () => { if (line.start !== null) player.currentTime = line.start; });
    const stamp = document.createElement("button"); stamp.className = "quiet";
    stamp.dataset.stamp = "true"; stamp.textContent = "再生位置";
    stamp.addEventListener("click", () => {
      line.start = Math.round(player.currentTime * 1000) / 1000; line.review = false; line.note = "手動修正";
      invalidatePreview(); renderRows(track);
    });
    time.append(start, seek, stamp);
    const text = document.createElement("td");
    const label = document.createElement("p"); label.textContent = line.text;
    const reading = document.createElement("input"); reading.value = line.reading;
    reading.placeholder = "読み（空欄で自動生成）"; reading.setAttribute("aria-label", `${index + 1}行目の読み`);
    reading.addEventListener("change", () => {
      line.reading = reading.value; line.start = null; line.end = null; line.review = true;
      line.note = "読みを変更しました。再解析してください"; invalidatePreview(); renderRows(track);
    });
    text.append(label, reading);
    const review = document.createElement("td");
    review.textContent = line.start === null ? "時刻未確定" : line.review ? "要確認" : "✓";
    if (line.start !== null) {
      const label = document.createElement("label"); label.className = "confirmation";
      const checked = document.createElement("input"); checked.type="checkbox"; checked.checked=!line.review;
      checked.setAttribute("aria-label",String(index+1)+"行目の同期を確認済みにする");
      checked.addEventListener("change",()=>{line.review=!checked.checked;renderRows(track);});
      label.append(checked,document.createTextNode("確認済")); review.append(label);
    }
    review.title = line.note + (line.confidence ? `（スコア ${line.confidence}）` : "");
    row.append(number, time, text, review); tbody.append(row);
  });
  controls(); highlight();
}
function renderEditor() {
  const track = selectedTrack();
  element("empty-editor").hidden = !!track;
  element("track-editor").hidden = !track;
  if (!track) { player.pause(); player.removeAttribute("src"); return; }
  element("track-title").textContent = track.name;
  element("track-path").textContent = track.path;
  if (player.dataset.track !== track.id) {
    player.pause();
    player.src = convertFileSrc(track.path);
    player.dataset.track = track.id;
    player.load();
  }
  lyrics.value = track.lyrics;
  element("track-status").textContent = track.status;
  output.value = "";
  renderRows(track);
}
function highlight() {
  const track = selectedTrack();
  const active = track ? activeLine(track.lines, player.currentTime) : -1;
  tbody.querySelectorAll("tr").forEach((row, index) => row.classList.toggle("playing", index === active));
  element("playback-time").textContent = "再生位置 " + clock(player.currentTime || 0);
}
player.addEventListener("timeupdate", highlight);
player.addEventListener("error", () => {
  if (player.getAttribute("src")) message("この音源を再生できません。対応コーデックを確認してください。解析自体は実行できます。");
});
lyrics.addEventListener("input", () => {
  const track = selectedTrack(); if (!track) return;
  track.lyrics = lyrics.value; track.lines = reconcileRows(track.lyrics,track.lines);
  track.status = track.lines.length ? "解析待ち" : "歌詞を入力してください";
  element("track-status").textContent = track.status;
  invalidatePreview(); renderRows(track); renderList();
});

async function runJob<T>(request: object): Promise<T> {
  const jobId = crypto.randomUUID();
  activeJob = jobId;
  try { return await invoke<T>("backend_job", { jobId, request }); }
  finally { if (activeJob === jobId) activeJob = null; }
}
function begin() { busy = true; stopRequested = false; progress.start(); controls(); }
function finish() { progress.finish(stopRequested); busy = false; currentTrack = null; activeJob = null; controls(); renderList(); }
function options() {
  return processingOptions({
    ...readAdvancedSettings(),
    device: selectedDevice(),
    engine: element<HTMLSelectElement>("engine").value,
    asr_model: element<HTMLSelectElement>("asr-model").value,
    language: element<HTMLSelectElement>("language").value,
    separate: element<HTMLInputElement>("separate").checked,
    align_model: element<HTMLInputElement>("align-model").value.trim(),
    cuda_compute_type: element<HTMLSelectElement>("cuda-compute-type").value,
    cuda_max_segment_seconds: Number(element<HTMLSelectElement>("cuda-max-segment").value),
  });
}
function saveProcessing() {
  if (!validSettings()) return;
  try { localStorage.setItem("lyrica-processing-options-v1",JSON.stringify({...options(),export_format:element<HTMLSelectElement>("export-format").value})); }
  catch { addLog("処理設定を保存できませんでした。"); }
}
function applyProcessing(saved: typeof DEFAULT_OPTIONS, format = "lrc") {
  for (const [id,value] of [["device",saved.device],["engine",saved.engine],["asr-model",saved.asr_model],
    ["language",saved.language],["align-model",saved.align_model],["cuda-compute-type",saved.cuda_compute_type],
    ["cuda-max-segment",String(saved.cuda_max_segment_seconds)]]) {
    element<HTMLInputElement | HTMLSelectElement>(id).value = value;
  }
  element<HTMLInputElement>("separate").checked=saved.separate;
  element<HTMLSelectElement>("export-format").value=format;
  button("export-all").textContent="4. "+format.toUpperCase()+"を一括保存";
  applyAdvancedSettings(saved);
}
function restoreProcessing() {
  try {
    const stored=JSON.parse(localStorage.getItem("lyrica-processing-options-v1") ?? "null");
    applyProcessing(processingOptions(stored),stored?.export_format==="txt" ? "txt" : "lrc");
  } catch {
    applyProcessing(DEFAULT_OPTIONS);
    addLog("保存した処理設定を読み込めませんでした。標準設定を使用します。");
  }
}
async function checkRuntime() {
  checkingRuntime = true; ready = false; controls();
  try {
    const status = await runJob<RuntimeInfo>({operation:"runtime_status",device:selectedDevice()});
    ready = status.ready; gpuInfo = status.gpu;
    message(ready ? "曲を追加して、歌詞を入力してください。" : selectedDevice() === "cuda"
      ? (gpuInfo?.available === false ? gpuInfo.reason ?? "NVIDIA CUDAを利用できません。" : "「CUDA解析環境を準備」を実行してください。")
      : "最初に「解析環境を準備」を実行してください。");
  } finally { checkingRuntime = false; controls(); }
}
document.querySelectorAll<HTMLInputElement | HTMLSelectElement>(".options input,.options select").forEach(input=>{
  input.addEventListener("change",()=>{
    saveProcessing();
    controls();
    if (input.id === "export-format") button("export-all").textContent = "4. "+input.value.toUpperCase()+"を一括保存";
    if (input.id === "device") void checkRuntime().catch(error=>message(errorText(error)));
  });
});
button("reset-settings").addEventListener("click",async()=>{
  if (busy || checkingRuntime) return;
  applyProcessing(DEFAULT_OPTIONS);
  saveProcessing();
  try { await checkRuntime(); message("すべての解析設定を標準に戻しました。"); }
  catch(error) { message("設定を標準に戻しました。環境の確認に失敗しました："+errorText(error)); }
});
button("setup").addEventListener("click",async()=>{
  begin(); message("解析環境を準備しています…");
  try {
    const status = await runJob<RuntimeInfo>({operation:"setup_runtime",device:selectedDevice()});
    ready = status.ready; gpuInfo = status.gpu;
    message((selectedDevice() === "cuda" ? "CUDA" : "CPU")+"解析環境の準備が完了しました。曲と歌詞を登録してください。");
  } catch(error) { ready = false; message(errorText(error)); }
  finally { finish(); }
});
button("add-audio").addEventListener("click", async () => {
  try {
    const files = await invoke<{ path: string; name: string }[]>("select_audio");
    for (const file of files) {
      if (tracks.some(t => t.path === file.path)) continue;
      const track: Track = { ...file, id: crypto.randomUUID(), lyrics: "", lines: [], status: "歌詞を入力してください" };
      tracks.push(track); selected ||= track.id;
    }
    renderList(); renderEditor(); message(`${tracks.length}曲を登録しています。歌詞を入力または読み込んでください。`);
  } catch (error) { message(errorText(error)); }
});
button("add-lyrics").addEventListener("click", async () => {
  try {
    const files = await invoke<{ name: string; text: string }[]>("select_lyrics");
    let count = 0; const unmatched: string[] = [];
    for (const file of files) {
      let matches = tracks.filter(t => stem(t.name) === stem(file.name));
      if (!matches.length && files.length === 1 && selectedTrack()) matches = [selectedTrack()!];
      if (!matches.length) { unmatched.push(file.name); continue; }
      for (const track of matches) {
        track.lyrics = file.text; track.lines = rowsFromText(file.text); track.status = "解析待ち"; count++;
      }
    }
    renderList(); renderEditor();
    message(`${count}曲に歌詞を読み込みました。` + (unmatched.length ? ` 対応する音源がありません：${unmatched.join("、")}` : ""));
  } catch (error) { message(errorText(error)); }
});
button("remove-track").addEventListener("click", () => {
  const index = tracks.findIndex(t => t.id === selected);
  if (index >= 0) tracks.splice(index, 1);
  selected = tracks[0]?.id ?? ""; renderList(); renderEditor();
});
button("readings").addEventListener("click", async () => {
  const track = selectedTrack();
  if (!track?.lines.length) { message("先に歌詞を入力してください。"); return; }
  begin(); currentTrack = track.id;
  try {
    const result = await runJob<{ lines: { reading: string }[] }>({ operation: "readings", lines: track.lines, language: options().language, device: selectedDevice() });
    track.lines.forEach((line,index) => { line.reading = result.lines[index].reading; });
    message("読みを生成しました。実際の歌い方と違う読みは修正できます。");
    if (selected === track.id) renderRows(track);
  } catch (error) { message(errorText(error)); }
  finally { finish(); }
});
async function analyze(queue: Track[]) {
  if (!validSettings(true)) { message("解析設定の数値と範囲を確認してください。"); return; }
  if (!queue.length) { message("音源と歌詞を登録してください。"); return; }
  const runnable = queue.filter(t => t.lines.length > 0);
  if (!runnable.length) { message("解析する曲に歌詞を入力してください。"); return; }
  begin(); progress.startBatch(runnable.length); const settings = options(); let completed = 0; let failed = 0;
  try {
    for (const track of runnable) {
      if (stopRequested) break;
      currentTrack = track.id;
      progress.song(track.name);
      track.status = "解析中"; renderList();
      try {
        const result = await runJob<{ lines: LyricRow[]; duration: number; review_count: number; unresolved_count: number; device?: string; gpu_name?: string }>({
          operation: "analyze", audio_path: track.path, lines: track.lines, options: settings });
        track.lines = result.lines; track.duration = result.duration;
        track.status = `${result.device === "cuda" ? "CUDA" : "CPU"}解析済み・要確認${result.review_count}行／時刻未確定${result.unresolved_count}行`;
        completed++; progress.settled(true);
      } catch (error) {
        track.status = stopRequested ? "キャンセル" : "解析失敗：" + errorText(error);
        if (!stopRequested) { failed++; progress.settled(false); }
        addLog(track.name + "：" + errorText(error));
      }
      renderList(); if (selected === track.id) renderEditor();
    }
    message(stopRequested ? "処理をキャンセルしました。完了済みの結果は保持しています。" :
      `解析終了：${completed}曲完了、${failed}曲失敗、歌詞未登録で除外${queue.length-runnable.length}曲。再生して同期を確認してください。`);
  } finally { finish(); }
}
button("analyze-all").addEventListener("click", () => void analyze([...tracks]));
button("analyze-one").addEventListener("click", () => {
  const track = selectedTrack(); if (track) void analyze([track]); else message("曲を追加してください。");
});
button("cancel").addEventListener("click", async () => {
  stopRequested = true; controls(); message("キャンセルしています…");
  try { if (activeJob) await invoke("cancel_job", { jobId: activeJob }); }
  catch (error) { addLog(errorText(error)); }
});
button("preview-lrc").addEventListener("click", async () => {
  const track = selectedTrack();
  if (!track || !exportable(track.lines, track.duration)) { message("すべての行に、音源内で昇順となる開始時刻を指定してください。"); return; }
  begin();
  try { output.value = (await runJob<{ lrc: string }>({ operation: "render_lrc", lines: track.lines })).lrc; }
  catch (error) { message(errorText(error)); }
  finally { finish(); }
});
button("export-all").addEventListener("click", async () => {
  const eligible = tracks.filter(t => exportable(t.lines, t.duration));
  if (!eligible.length) { message("保存できる曲がありません。未確定・範囲外・逆順の時刻を修正してください。"); return; }
  begin();
  try {
    const result = await invoke<{ saved?: string[]; errors?: { name: string; error: string }[]; cancelled?: boolean }>("export_batch", {
      tracks: eligible.map(t => ({ name: t.name, lines: t.lines })), format: element<HTMLSelectElement>("export-format").value });
    if (result.cancelled) { message("保存をキャンセルしました。"); return; }
    for (const path of result.saved ?? []) addLog("保存：" + path);
    for (const error of result.errors ?? []) addLog(error.name + "：" + error.error);
    message(`${result.saved?.length ?? 0}曲を保存しました。失敗${result.errors?.length ?? 0}曲、歌詞・時刻未完了で除外${tracks.length-eligible.length}曲。同名ファイルは連番で保存します。`);
  } catch (error) { message(errorText(error)); }
  finally { finish(); }
});

async function initialize() {
  if (!isTauri()) {
    message("デスクトップアプリを起動してください。ブラウザーのプレビューでは音源解析を実行できません。");
    document.querySelectorAll<HTMLButtonElement>("button").forEach(item => { item.disabled = true; }); return;
  }
  restoreProcessing();
  controls();
  await listen<ProgressEvent & { job_id: string }>("analysis-progress", event => {
    if (event.payload.job_id !== activeJob) return;
    progress.update(event.payload);
    const text = event.payload.message;
    addLog(text);
    if (event.payload.stage !== "log") {
      const track = tracks.find(t => t.id === currentTrack);
      message((track ? track.name + "：" : "") + text);
    }
  });
  try {
    await checkRuntime();
    const saved = JSON.parse(localStorage.getItem("lyrica-workspace-v1") ?? localStorage.getItem("lyricgen-workspace-v1") ?? "null");
    const restored = restoreTracks(saved?.tracks);
    if (restored.length) {
      const allowed = await invoke<string[]>("restore_audio",{paths:restored.map(track=>track.path)});
      restored.forEach(track=>{if(!allowed.includes(track.path)) track.status="音源が見つかりません。再接続するか、歌詞を保存してください";});
      tracks.push(...restored);
      selected = restored.some(track=>track.id===saved.selected) ? saved.selected : restored[0].id;
      renderList(); renderEditor(); message("前回の作業を復元しました。解析結果・手動修正は自動保存されます。");
    }
  } catch (error) { message(errorText(error)); }
  controls();
}
void initialize();
