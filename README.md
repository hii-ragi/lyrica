# Lyrica

音源と正しい歌詞から、行ごとの開始時刻を解析してLRCを一括生成するWindowsアプリです。
Tauri + Web UI → Python前処理 → Sudachi / Demucs → 音声認識 / WhisperXアライメント → LRC → 同期確認、というagents.mdの構成を実装しています。

## アプリの使い方

1. `src-tauri/target/release/bundle/nsis/Lyrica_0.2.2_x64-setup.exe` でインストールして起動します。
2. 「解析環境を準備」を押します。専用のPython 3.12、WhisperX、Demucs、Sudachi、FFmpegを自動取得します。システムのPythonは変更しません。初回はネット接続と数GB以上の空き容量が必要です。
3. 「曲を追加」で音源を複数選びます。
4. 各曲を選んで歌詞を貼り付けるか、UTF-8の.txt / .lrcをまとめて読み込みます。音源と歌詞のファイル名（拡張子を除く）が同じなら自動対応します。歌詞ファイルを1つだけ選んだ場合、名前が一致しなければ選択中の曲へ読み込みます。
5. まず1曲・tinyモデルで動作確認できます。通常はsmallモデルを選び、「全曲を解析」を押します。
6. 音源を再生し、行の「移動」で開始位置を確認します。ずれていたら秒数を編集するか「再生位置」で現在位置を開始時刻に設定します。読みが違う場合は読みを直して再解析できます。確認した行は「確認済」にチェックできます。
7. 「LRCを一括保存」で出力フォルダを選びます。同名ファイルは連番で保存し、既存ファイルを上書きしません。

歌詞に秒数を手入力してから解析する必要はありません。歌詞は、LRCで表示したい単位ごとに改行してください。

```text
最初のフレーズ
次のフレーズ
最後のフレーズ
```

曲・歌詞・解析結果・手動修正はローカルに自動保存され、再起動後に復元します。音源ファイル自体はコピーしません。移動・削除した音源は選び直してください。

## 解析の仕組みと精度

- Sudachiで形態素と読みを生成し、表示用の元の歌詞と別に保持します。「宇宙」を「そら」と歌う場合などは読みを上書きできます。通常は元の表記でアライメントし、特別な読みを設定した行はその読みを使います。
- Demucsでボーカルを分離します。すでにボーカルのみの音源なら設定をオフにできます。
- faster-whisperまたはWhisperXのSilero VADで音声を認識し、単語ごとの時刻を取得します。歌詞と認識結果の読みを順番に照合し、各行の解析範囲を決めます。
- WhisperXの文字アライメントで開始時刻を求めます。強制対応のスコアだけを信用せず、モデルが認識した文字列との一致も確認します。
- WhisperXの対応が弱く、単語時刻の対応が十分ある場合は単語時刻を使って「要確認」にします。時刻の根拠がない行は未確定のままにし、適当な時間を割り振りません。
- 未確定・逆順・範囲外の時刻がある曲は保存対象から除外し、画面に件数を表示します。修正後に保存できます。

歌唱の伸ばし、ラップ、コーラス、歌詞と音源の違いなどにより精度は変わります。出力前に再生確認してください。検証用の合成音声は楽曲での精度を保証するものではありません。

CPU処理です。tiny/base/small/medium/large-v3と、言語ごとの標準アライメントモデルまたは任意のHugging FaceモデルIDを選択できます。モデルと辞書はローカルに保存し、次回から再利用します。日本語・英語、wav/mp3/flac/m4a/aac/ogg/opus/wmaに対応します。画面での再生可否はWebView2のコーデックにも依存します。

## ローカル開発とテスト

必要：Node.js 22.12以上の22系または24系、Python 3.12以上（ビルド用）、Rust stable MSVC、Visual Studio C++ Build Tools、Windows SDK、WebView2。

PowerShellでは実行ポリシーに関係なく呼べる `npm.cmd` を使えます。

```powershell
git clone https://github.com/hii-ragi/lyrica.git
cd lyrica
npm.cmd ci
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-build.txt -e ./backend

npm.cmd test
npm.cmd run build
.venv\Scripts\python.exe -m unittest discover -s backend/tests -v

# 小さなPythonブリッジ・uv・解析ソースをパッケージ
.venv\Scripts\python.exe scripts/build_backend.py
.venv\Scripts\python.exe scripts/smoke_backend.py src-tauri/binaries/lyrica-backend-x86_64-pc-windows-msvc.exe

cargo test --locked --manifest-path src-tauri/Cargo.toml
npm.cmd run tauri -- dev
```

Pythonの解析環境はアプリのボタンから準備できます。CLIから同じ環境を準備する場合：

```powershell
.venv\Scripts\python.exe scripts/manage_analysis.py setup
.venv\Scripts\python.exe scripts/manage_analysis.py status
```

配置先は `%LOCALAPPDATA%/io.lyricgen.desktop/analysis/` です。依存バージョンは `backend/requirements-analysis.txt` と `backend/constraints-analysis.txt` で固定しています。

画面テストはネイティブAPIの応答を置き換え、曲の登録・一括解析の進行・音声のシーク・時刻修正・保存・キャンセル・作業復元を検証します。実モデルの検証とは別です。

```powershell
# インストール済みEdgeを使う場合
$env:PLAYWRIGHT_CHANNEL = "msedge"
npm.cmd run test:ui
# Chromiumを使う場合は事前に npx playwright install chromium
```

実モデルでのテストは、テスト音源と正しい歌詞を指定します。tinyを使用し、全行に音源内で昇順の時刻が付くことを検証します。

```powershell
# Windows標準の音声合成から英語テスト音源を作成
powershell -ExecutionPolicy Bypass -File scripts/create_smoke_audio.ps1
.venv\Scripts\python.exe scripts/smoke_analysis.py --audio build/smoke-en.wav --lyrics build/smoke-en.txt --language en --separate --engine whisperx
# 自分の短い日本語音源を使う場合
.venv\Scripts\python.exe scripts/smoke_analysis.py --audio path/to/audio.wav --lyrics path/to/lyrics.txt --language ja --separate
```

診断結果は `build/smoke-analysis-result.json` に保存します。

## ビルドとGitHub Actions

```powershell
npm.cmd run tauri -- build --ci -- --locked
```

Windows x64のNSISインストーラーを `src-tauri/target/release/bundle/nsis/` に生成します。小さなPythonブリッジ・uv・解析ソースを同梱し、解析ライブラリとモデルは初回準備時・初回解析時に取得します。署名なしです。WebView2が未導入ならインストーラーが取得します。

Actionsはpush・PR・手動実行で、Windows/Linuxの単体テスト、Linuxの画面テスト、WindowsのRust結合テストとインストーラー生成を実行します。インストーラーはArtifactsに14日間保存します。
手動実行時に `real_models` を有効にすると、Windowsで解析環境を新規構築し、音声合成した音源にDemucs・WhisperXを実行する追加テストも走ります。通常のテストではモデルをダウンロードしません。

## 構成

- `src/`：曲一覧、歌詞・読み・時刻の編集、再生同期、バッチ操作、自動保存。
- `src-tauri/`：ネイティブダイアログ、選択音源の再生許可、Python呼び出し、進捗通知、子プロセスのキャンセル。
- `backend/src/lyrica_backend/`：環境準備、読み生成、分離、音声認識・アライメント、LRC出力。
- `scripts/`：ブリッジのビルド、実モデル検証、環境のCLI管理。
- `tests/ui/`：ブラウザーによる操作テスト。

音声・歌詞のデータを外部APIへ送る処理はありません。初回のライブラリ・辞書・モデルのダウンロードでは外部サーバーへ接続します。

## ロゴと配色

アイコンと画面のロゴはルートの `logo.png` を使用しています。配色は `src/style.css` のアイボリー・ブラウンの変数で管理します。画像を差し替えた場合は `python scripts/create_icons.py` でWindowsアイコン、ヘッダーロゴ、faviconを再生成できます。

## 旧名称からの引き継ぎ

製品名・実行ファイル・パッケージ名はLyricaに統一しています。既存の解析環境・モデル・インストール済みアプリとの互換性のため、内部アプリIDは io.lyricgen.desktop を維持しています。作業データは旧保存キーから自動で引き継ぎます。開発フォルダの名前は任意です。
