import { convertFileSrc, invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { activeLine, clock, exportable, reconcileRows, restoreTracks, rowsFromText, stem, type LyricRow, type Track } from "./model";
import "./style.css";

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
  for (const id of ["setup","add-audio","add-lyrics","export-all","remove-track"]) button(id).disabled = busy;
  for (const id of ["analyze-all","analyze-one","readings"]) button(id).disabled = busy || !ready;
  button("preview-lrc").disabled = busy;
  button("cancel").disabled = !busy || stopRequested;
  lyrics.disabled = busy;
  document.querySelectorAll<HTMLInputElement | HTMLSelectElement>(".options input,.options select")
    .forEach(input => { input.disabled = busy; });
  tbody.querySelectorAll<HTMLInputElement>("input").forEach(input => { input.disabled = busy; });
  tbody.querySelectorAll<HTMLButtonElement>("button[data-stamp]").forEach(input => { input.disabled = busy; });
  element("environment").textContent = ready ? "解析環境：準備済み" : "解析環境：未準備";
  button("setup").textContent = ready ? "解析環境を再確認・修復" : "解析環境を準備";
}
function persist() {
  try { localStorage.setItem("lyricgen-workspace-v1",JSON.stringify({tracks,selected})); }
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
    const number = document.createElement("td"); number.textContent = String(index + 1);
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
function begin() { busy = true; stopRequested = false; controls(); }
function finish() { busy = false; currentTrack = null; activeJob = null; controls(); renderList(); }
function options() {
  return { engine: element<HTMLSelectElement>("engine").value,
    asr_model: element<HTMLSelectElement>("asr-model").value,
    language: element<HTMLSelectElement>("language").value, device: "cpu",
    separate: element<HTMLInputElement>("separate").checked,
    align_model: element<HTMLInputElement>("align-model").value.trim() };
}
async function checkRuntime() {
  const status = await runJob<{ ready: boolean }>({ operation: "runtime_status" });
  ready = status.ready; controls();
  message(ready ? "曲を追加して、歌詞を入力してください。" : "最初に「解析環境を準備」を実行してください。");
}
button("setup").addEventListener("click", async () => {
  begin(); message("解析環境を準備しています…");
  try {
    const status = await runJob<{ ready: boolean }>({ operation: "setup_runtime" });
    ready = status.ready; message("解析環境の準備が完了しました。曲と歌詞を登録してください。");
  } catch (error) { ready = false; message(errorText(error)); }
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
    const result = await runJob<{ lines: { reading: string }[] }>({ operation: "readings", lines: track.lines, language: options().language });
    track.lines.forEach((line,index) => { line.reading = result.lines[index].reading; });
    message("読みを生成しました。実際の歌い方と違う読みは修正できます。");
    if (selected === track.id) renderRows(track);
  } catch (error) { message(errorText(error)); }
  finally { finish(); }
});
async function analyze(queue: Track[]) {
  if (!queue.length) { message("音源と歌詞を登録してください。"); return; }
  const runnable = queue.filter(t => t.lines.length > 0);
  if (!runnable.length) { message("解析する曲に歌詞を入力してください。"); return; }
  begin(); const settings = options(); let completed = 0; let failed = 0;
  try {
    for (const track of runnable) {
      if (stopRequested) break;
      currentTrack = track.id;
      track.status = "解析中"; renderList();
      try {
        const result = await runJob<{ lines: LyricRow[]; duration: number; review_count: number; unresolved_count: number }>({
          operation: "analyze", audio_path: track.path, lines: track.lines, options: settings });
        track.lines = result.lines; track.duration = result.duration;
        track.status = `解析済み・要確認${result.review_count}行／時刻未確定${result.unresolved_count}行`;
        completed++;
      } catch (error) {
        track.status = stopRequested ? "キャンセル" : "解析失敗：" + errorText(error); failed++;
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
      tracks: eligible.map(t => ({ name: t.name, lines: t.lines })) });
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
  await listen<{ job_id: string; stage: string; message: string }>("analysis-progress", event => {
    if (event.payload.job_id !== activeJob) return;
    const text = event.payload.message;
    addLog(text);
    if (event.payload.stage !== "log") {
      const track = tracks.find(t => t.id === currentTrack);
      message((track ? track.name + "：" : "") + text);
    }
  });
  try {
    await checkRuntime();
    const saved = JSON.parse(localStorage.getItem("lyricgen-workspace-v1") ?? "null");
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
