#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde_json::{json, Value};
use std::{
    collections::{HashMap, HashSet},
    io::{BufRead, BufReader, Read, Write},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::Mutex,
};
use tauri::{Emitter, Manager};
use tauri_plugin_dialog::DialogExt;

#[derive(Default)]
struct Job {
    pid: Option<u32>,
    cancelled: bool,
}

#[derive(Default)]
struct AppState {
    jobs: Mutex<HashMap<String, Job>>,
    audio: Mutex<HashSet<PathBuf>>,
}

fn hidden(command: &mut Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    #[cfg(not(windows))]
    let _ = command;
}

fn kill_tree(pid: u32) {
    #[cfg(windows)]
    {
        let mut command = Command::new("taskkill");
        hidden(&mut command);
        let _ = command
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
    #[cfg(not(windows))]
    {
        let _ = Command::new("kill")
            .args(["-TERM", &pid.to_string()])
            .status();
    }
}

fn sibling(name: &str) -> Result<PathBuf, String> {
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    Ok(exe
        .parent()
        .ok_or("実行フォルダが見つかりません")?
        .join(format!("{name}{}", std::env::consts::EXE_SUFFIX)))
}

fn invoke_backend(
    backend: &Path,
    request: Value,
    context: Option<(tauri::AppHandle, String)>,
) -> Result<Value, String> {
    let mut command = Command::new(backend);
    hidden(&mut command);
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let mut child = command
        .spawn()
        .map_err(|e| format!("バックエンドを起動できません: {e}"))?;
    if let Some((app, id)) = &context {
        let state = app.state::<AppState>();
        let mut jobs = state.jobs.lock().map_err(|e| e.to_string())?;
        let job = jobs.entry(id.clone()).or_default();
        job.pid = Some(child.id());
        if job.cancelled {
            kill_tree(child.id());
        }
    }
    let stdout = child.stdout.take().ok_or("stdout unavailable")?;
    let stderr = child.stderr.take().ok_or("stderr unavailable")?;
    let stdout_reader = std::thread::spawn(move || {
        let mut bytes = Vec::new();
        BufReader::new(stdout)
            .read_to_end(&mut bytes)
            .map(|_| bytes)
    });
    let event_context = context.clone();
    let stderr_reader = std::thread::spawn(move || {
        let mut tail = std::collections::VecDeque::new();
        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
            let line: String = line.chars().take(1500).collect();
            if let Some((app, id)) = &event_context {
                let event = line
                    .strip_prefix("LYRICA_EVENT ")
                    .and_then(|s| serde_json::from_str::<Value>(s).ok())
                    .unwrap_or_else(|| json!({"stage":"log","message":line}));
                let _ = app.emit(
                    "analysis-progress",
                    json!({
                        "job_id": id, "stage": event["stage"], "message": event["message"],
                        "completed": event["completed"], "total": event["total"]
                    }),
                );
            }
            tail.push_back(line);
            if tail.len() > 12 {
                tail.pop_front();
            }
        }
        tail.into_iter().collect::<Vec<_>>().join("\n")
    });
    let input = serde_json::to_vec(&request).map_err(|e| e.to_string())?;
    let write = child
        .stdin
        .take()
        .ok_or("stdin unavailable")?
        .write_all(&input);
    if write.is_err() {
        kill_tree(child.id());
    }
    let status = child.wait().map_err(|e| e.to_string())?;
    let bytes = stdout_reader
        .join()
        .map_err(|_| "stdout reader failed")?
        .map_err(|e| e.to_string())?;
    let tail = stderr_reader.join().map_err(|_| "stderr reader failed")?;
    if let Some((app, id)) = &context {
        let state = app.state::<AppState>();
        if state
            .jobs
            .lock()
            .map_err(|e| e.to_string())?
            .get(id)
            .is_some_and(|j| j.cancelled)
        {
            return Err("処理をキャンセルしました".into());
        }
    }
    write.map_err(|e| format!("バックエンドとの通信に失敗しました: {e}"))?;
    let response: Value = serde_json::from_slice(&bytes)
        .map_err(|_| format!("解析プロセスが終了しました。\n{tail}"))?;
    if !status.success() {
        return Err(response["error"]
            .as_str()
            .unwrap_or("解析に失敗しました")
            .to_owned());
    }
    Ok(response)
}

fn enrich(app: &tauri::AppHandle, request: &mut Value) -> Result<(), String> {
    let home = app
        .path()
        .app_local_data_dir()
        .map_err(|e| e.to_string())?
        .join("analysis");
    let resources = app
        .path()
        .resource_dir()
        .map_err(|e| e.to_string())?
        .join("analysis");
    request["runtime_dir"] = json!(home);
    request["resource_dir"] = json!(resources);
    request["uv_path"] = json!(sibling("uv")?);
    Ok(())
}

#[tauri::command]
async fn backend_job(
    app: tauri::AppHandle,
    job_id: String,
    mut request: Value,
) -> Result<Value, String> {
    if job_id.is_empty() || job_id.len() > 100 {
        return Err("不正なジョブIDです".into());
    }
    let operation = request["operation"].as_str().ok_or("処理が未指定です")?;
    if ![
        "render_lrc",
        "runtime_status",
        "setup_runtime",
        "readings",
        "analyze",
    ]
    .contains(&operation)
    {
        return Err("未対応の処理です".into());
    }
    if operation == "analyze" {
        let path = PathBuf::from(request["audio_path"].as_str().ok_or("音源が未指定です")?);
        if !app
            .state::<AppState>()
            .audio
            .lock()
            .map_err(|e| e.to_string())?
            .contains(&path)
        {
            return Err("音源を「曲を追加」から選び直してください".into());
        }
    }
    enrich(&app, &mut request)?;
    {
        let state = app.state::<AppState>();
        let mut jobs = state.jobs.lock().map_err(|e| e.to_string())?;
        if jobs.contains_key(&job_id) {
            return Err("同じジョブが実行中です".into());
        }
        jobs.insert(job_id.clone(), Job::default());
    }
    let worker_app = app.clone();
    let worker_id = job_id.clone();
    let result = tauri::async_runtime::spawn_blocking(move || {
        invoke_backend(
            &sibling("lyrica-backend")?,
            request,
            Some((worker_app, worker_id)),
        )
    })
    .await
    .map_err(|e| e.to_string());
    app.state::<AppState>()
        .jobs
        .lock()
        .map_err(|e| e.to_string())?
        .remove(&job_id);
    result?
}

#[tauri::command]
fn cancel_job(app: tauri::AppHandle, job_id: String) -> Result<(), String> {
    let pid = {
        let state = app.state::<AppState>();
        let mut jobs = state.jobs.lock().map_err(|e| e.to_string())?;
        let job = jobs.get_mut(&job_id).ok_or("実行中の処理がありません")?;
        job.cancelled = true;
        job.pid
    };
    if let Some(pid) = pid {
        kill_tree(pid);
    }
    Ok(())
}

#[tauri::command]
async fn select_audio(app: tauri::AppHandle) -> Result<Vec<Value>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let selected = app
            .dialog()
            .file()
            .add_filter(
                "音源",
                &["wav", "mp3", "flac", "m4a", "aac", "ogg", "opus", "wma"],
            )
            .blocking_pick_files()
            .unwrap_or_default();
        let mut result = Vec::new();
        for file in selected {
            let path = file.into_path().map_err(|e| e.to_string())?;
            app.asset_protocol_scope()
                .allow_file(&path)
                .map_err(|e| e.to_string())?;
            app.state::<AppState>()
                .audio
                .lock()
                .map_err(|e| e.to_string())?
                .insert(path.clone());
            result.push(
                json!({"path":path,"name":path.file_name().unwrap_or_default().to_string_lossy()}),
            );
        }
        Ok(result)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
fn restore_audio(app: tauri::AppHandle, paths: Vec<PathBuf>) -> Result<Vec<PathBuf>, String> {
    let mut allowed = Vec::new();
    for path in paths.into_iter().take(500) {
        let extension = path
            .extension()
            .and_then(|s| s.to_str())
            .unwrap_or("")
            .to_lowercase();
        if path.is_file()
            && ["wav", "mp3", "flac", "m4a", "aac", "ogg", "opus", "wma"]
                .contains(&extension.as_str())
        {
            app.asset_protocol_scope()
                .allow_file(&path)
                .map_err(|e| e.to_string())?;
            app.state::<AppState>()
                .audio
                .lock()
                .map_err(|e| e.to_string())?
                .insert(path.clone());
            allowed.push(path);
        }
    }
    Ok(allowed)
}

#[tauri::command]
async fn select_lyrics(app: tauri::AppHandle) -> Result<Vec<Value>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let selected = app
            .dialog()
            .file()
            .add_filter("歌詞", &["txt", "lrc"])
            .blocking_pick_files()
            .unwrap_or_default();
        selected.into_iter().map(|file| {
            let path = file.into_path().map_err(|e| e.to_string())?;
            let size = std::fs::metadata(&path).map_err(|e| e.to_string())?.len();
            if size > 2_000_000 { return Err("歌詞ファイルは2MB以下にしてください".into()); }
            let text = std::fs::read_to_string(&path)
                .map_err(|_| format!("UTF-8の歌詞ファイルを指定してください: {}",path.display()))?;
            Ok(json!({"name":path.file_name().unwrap_or_default().to_string_lossy(),"text":text}))
        }).collect()
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn export_batch(
    app: tauri::AppHandle,
    tracks: Value,
    format: Option<String>,
) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let folder = app.dialog().file().blocking_pick_folder();
        let Some(folder) = folder else {
            return Ok(json!({"cancelled":true}));
        };
        let directory = folder.into_path().map_err(|e| e.to_string())?;
        invoke_backend(
            &sibling("lyrica-backend")?,
            json!({"operation":"export_batch","directory":directory,"tracks":tracks,"format":format.unwrap_or_else(|| "lrc".into())}),
            None,
        )
    })
    .await
    .map_err(|e| e.to_string())?
}

fn main() {
    tauri::Builder::default()
        .manage(AppState::default())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            backend_job,
            cancel_job,
            select_audio,
            restore_audio,
            select_lyrics,
            export_batch
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let state = window.state::<AppState>();
                if let Ok(jobs) = state.jobs.lock() {
                    for job in jobs.values() {
                        if let Some(pid) = job.pid {
                            kill_tree(pid);
                        }
                    }
                };
            }
        })
        .run(tauri::generate_context!())
        .expect("Failed to run Lyrica");
}

#[cfg(test)]
mod tests {
    use super::*;
    fn backend() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("target/debug")
            .join(format!("lyrica-backend{}", std::env::consts::EXE_SUFFIX))
    }
    #[test]
    fn frozen_python_roundtrip() {
        let response = invoke_backend(
            &backend(),
            json!({"operation":"render_lrc",
            "lines":[{"start":59.995,"text":"宇宙へ"}]}),
            None,
        )
        .unwrap();
        assert_eq!(response["lrc"], "[01:00.00]宇宙へ\n");
    }
    #[test]
    fn backend_validation_reaches_the_ui() {
        let error = invoke_backend(
            &backend(),
            json!({"operation":"render_lrc",
            "lines":[{"start":-1,"text":"歌詞"}]}),
            None,
        )
        .unwrap_err();
        assert!(error.contains("start must be between"));
    }
}
