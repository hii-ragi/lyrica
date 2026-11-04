import { describe, expect, it } from "vitest";
import { activeLine, clock, exportable, reconcileRows, restoreTracks, rowsFromText, stem } from "./model";

describe("歌詞の登録と同期編集", () => {
  it("普通の歌詞に時刻を捏造しない", () => {
    const rows = rowsFromText("宇宙\r\n\r\n君へ");
    expect(rows.map(r => r.text)).toEqual(["宇宙","君へ"]);
    expect(rows.every(r => r.start === null && r.review)).toBe(true);
  });
  it("UTF-8 BOMとLRCメタデータを除き、表示用歌詞を保持する", () => {
    const rows = rowsFromText("\uFEFF[ti:曲]\n[00:12.50]宇宙\n[01:02:25]君へ");
    expect(rows.map(r => [r.text,r.start])).toEqual([["宇宙",12.5],["君へ",62.25]]);
  });
  it("同名音源と歌詞を全角・大小文字を正規化して対応させる", () => {
    expect(stem("ＳＯＮＧ.MP3")).toBe(stem("song.txt"));
  });
  it("未確定・逆順・範囲外の時刻は保存できない", () => {
    const rows = rowsFromText("A\nB");
    expect(exportable(rows)).toBe(false);
    rows[0].start = 10; rows[1].start = 9;
    expect(exportable(rows)).toBe(false);
    rows[1].start = 11;
    expect(exportable(rows, 10)).toBe(false);
    expect(exportable(rows, 12)).toBe(true);
    rows[1].start = Number.NaN;
    expect(exportable(rows)).toBe(false);
  });
  it("再生位置から対応する歌詞行を選ぶ", () => {
    const rows = rowsFromText("[00:02.00]A\n[00:05.00]B");
    expect(activeLine(rows,1)).toBe(-1);
    expect(activeLine(rows,2)).toBe(0);
    expect(activeLine(rows,5.1)).toBe(1);
  });
  it("歌詞の一部を削除しても残りの行の修正を保持する", () => {
    const rows = rowsFromText("間奏\n宇宙\n君へ");
    rows[1].start=12;rows[1].reading="ソラ";
    const updated = reconcileRows("宇宙\n君へ\n新しい行",rows);
    expect(updated[0].start).toBe(12);
    expect(updated[0].reading).toBe("ソラ");
    expect(updated[2].start).toBeNull();
  });
  it("不正な保存状態を破棄する", () => {
    expect(restoreTracks(null)).toEqual([]);
    expect(restoreTracks([{path:"a"}])).toEqual([]);
  });
  it("時刻表示の繰り上がり", () => {
    expect(clock(59.999)).toBe("01:00.00");
  });
});

it("空行を除いても元の行番号と空白を保持し、編集後の行番号を更新する",()=>{
  const rows = rowsFromText("[ti:曲]\n  宇宙(そら)  \n\n君とFly away");
  expect(rows.map(row=>[row.text,row.source_line])).toEqual([["  宇宙(そら)  ",2],["君とFly away",4]]);
  rows[1].reading="キミトFly away"; rows[1].start=5;
  const updated=reconcileRows("君とFly away\n\n  宇宙(そら)  ",rows);
  expect(updated.map(row=>row.source_line)).toEqual([1,3]);
  expect(updated[0].reading).toBe("キミトFly away");
  const restored=restoreTracks([{id:"test",name:"曲.wav",path:"F:/曲.wav",lyrics:"君とFly away\n\n  宇宙(そら)  ",lines:updated}]);
  expect(restored[0].lines.map(row=>row.source_line)).toEqual([1,3]);
});
