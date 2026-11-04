export interface LyricRow {
  source_line?: number;
  text: string; reading: string; start: number | null; end: number | null;
  confidence: number; review: boolean; note: string;
}
export interface Track {
  id: string; path: string; name: string; lyrics: string;
  lines: LyricRow[]; status: string; duration?: number;
}
export function rowsFromText(text: string): LyricRow[] {
  return text.replace(/^\uFEFF/,"").split(/\r?\n/).flatMap((raw, index) => {
    if (/^\[(ar|al|ti|by|offset|re|ve|length):.*\]$/i.test(raw.trim())) return [];
    const stamp = raw.match(/\[(\d+):(\d+(?:[.:]\d+)?)\]/);
    const lyric = raw.replace(/\[\d+:\d+(?:[.:]\d+)?\]/g,"");
    if (!lyric.trim()) return [];
    const start = stamp ? Number(stamp[1])*60+Number(stamp[2].replace(":", ".")) : null;
    return [{text:lyric,source_line:index+1,reading:"",start,end:null,confidence:0,review:true,
      note:stamp ? "読み込んだ時刻を確認してください" : "未解析"}];
  });
}
export function reconcileRows(text: string, previous: LyricRow[]): LyricRow[] {
  const buckets = new Map<string,LyricRow[]>();
  previous.forEach(row => buckets.set(row.text,[...(buckets.get(row.text) ?? []),row]));
  return rowsFromText(text).map(row => ({...(buckets.get(row.text)?.shift() ?? row), source_line:row.source_line}));
}
export function restoreTracks(value: unknown): Track[] {
  if (!Array.isArray(value)) return [];
  return value.slice(0,500).flatMap((item: Partial<Track>) => {
    if (!item || typeof item.path !== "string" || typeof item.name !== "string" ||
        typeof item.lyrics !== "string" || typeof item.id !== "string" || !Array.isArray(item.lines)) return [];
    const sourceRows = rowsFromText(item.lyrics);
    const lines = item.lines.filter(line => line && typeof line.text === "string").map((line,index) => ({
      source_line: Number.isInteger(line.source_line) && line.source_line! > 0 ? line.source_line : sourceRows[index]?.source_line ?? index+1,
      text:line.text,reading:typeof line.reading === "string" ? line.reading : "",
      start:typeof line.start === "number" && Number.isFinite(line.start) ? line.start : null,
      end:typeof line.end === "number" && Number.isFinite(line.end) ? line.end : null,
      confidence:typeof line.confidence === "number" ? line.confidence : 0,
      review:!!line.review,note:typeof line.note === "string" ? line.note : "",
    }));
    return [{id:item.id,path:item.path,name:item.name,lyrics:item.lyrics,lines,
      duration:typeof item.duration === "number" && Number.isFinite(item.duration) ? item.duration : undefined,
      status:item.status === "解析中" ? "前回の解析は中断されました" : String(item.status ?? "復元しました")}];
  });
}
export function stem(name: string): string {
  return name.replace(/\.[^.]+$/,"").normalize("NFKC").toLocaleLowerCase();
}
export function exportable(lines: LyricRow[], duration?: number): boolean {
  let previous = -1;
  return lines.length > 0 && lines.every(line => {
    const start = line.start;
    if (start === null || !Number.isFinite(start) || start < previous || start < 0 ||
        start > 86400 || (duration !== undefined && start > duration)) return false;
    previous = start; return true;
  });
}
export function activeLine(lines: LyricRow[], time: number): number {
  let current = -1;
  lines.forEach((line,index) => { if (line.start !== null && line.start <= time) current = index; });
  return current;
}
export function clock(seconds: number): string {
  const ticks = Math.round(seconds*100);
  return `${Math.floor(ticks/6000).toString().padStart(2,"0")}:${Math.floor(ticks%6000/100).toString().padStart(2,"0")}.${(ticks%100).toString().padStart(2,"0")}`;
}
