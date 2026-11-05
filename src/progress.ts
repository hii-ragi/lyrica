export interface ProgressEvent {
  stage: string;
  message: string;
  completed?: number | null;
  total?: number | null;
}

export class ProgressView {
  private batch = false;
  private total = 0;
  private succeeded = 0;
  private failed = 0;
  private root = document.getElementById("generation-progress")!;
  private overall = document.getElementById("batch-progress") as HTMLProgressElement;
  private summary = document.getElementById("batch-progress-label")!;
  private current = document.getElementById("stage-progress") as HTMLProgressElement;
  private detail = document.getElementById("stage-progress-label")!;

  start() {
    this.batch = false;
    this.root.hidden = false;
    this.overall.hidden = this.summary.hidden = true;
    this.current.hidden = this.detail.hidden = false;
    this.current.removeAttribute("value");
    this.detail.textContent = "処理を開始しています…";
  }

  startBatch(total: number) {
    this.batch = true;
    this.total = total;
    this.succeeded = this.failed = 0;
    this.overall.hidden = this.summary.hidden = false;
    this.overall.max = total;
    this.drawBatch();
  }

  song(name: string) {
    this.current.removeAttribute("value");
    this.detail.textContent = name + "：解析を開始しています…";
  }

  update(event: ProgressEvent) {
    if (event.stage === "log") return;
    const { completed, total } = event;
    const measured = typeof completed === "number" && Number.isFinite(completed) && completed >= 0
      && typeof total === "number" && Number.isFinite(total) && total > 0;
    if (measured) {
      this.current.max = total;
      this.current.value = Math.min(completed, total);
    } else {
      this.current.removeAttribute("value");
    }
    this.detail.textContent = event.message + (measured ? "（" + Math.floor(Math.min(completed, total) / total * 100) + "%）" : "");
  }

  settled(success: boolean) {
    if (success) this.succeeded++; else this.failed++;
    this.drawBatch();
  }

  finish(cancelled: boolean) {
    this.current.hidden = this.detail.hidden = true;
    if (this.batch) this.drawBatch(cancelled ? "・キャンセル" : "・終了");
    else this.root.hidden = true;
  }

  private drawBatch(suffix = "") {
    const done = this.succeeded + this.failed;
    this.overall.value = done;
    this.summary.textContent = "処理済み " + done + " / " + this.total
      + "曲（成功 " + this.succeeded + "・失敗 " + this.failed + "）" + suffix;
  }
}
