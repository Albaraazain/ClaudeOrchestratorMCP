use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;
use tauri::{AppHandle, Emitter};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandEvent;

// Track if backend is ready
static BACKEND_READY: AtomicBool = AtomicBool::new(false);

// Backend port - using 8765 to avoid conflicts with dev server on 8000
const BACKEND_PORT: u16 = 8765;

#[tauri::command]
fn get_backend_url() -> String {
    format!("http://localhost:{}", BACKEND_PORT)
}

#[tauri::command]
fn get_ws_url() -> String {
    format!("ws://localhost:{}", BACKEND_PORT)
}

#[tauri::command]
fn is_backend_ready() -> bool {
    BACKEND_READY.load(Ordering::SeqCst)
}

async fn wait_for_backend_ready() -> bool {
    let client = reqwest::Client::new();
    let health_url = format!("http://localhost:{}/health", BACKEND_PORT);

    for attempt in 1..=30 {
        match client.get(&health_url).timeout(Duration::from_secs(2)).send().await {
            Ok(response) if response.status().is_success() => {
                println!("[Tauri] Backend ready after {} attempts", attempt);
                return true;
            }
            Ok(response) => {
                println!("[Tauri] Backend returned status: {}", response.status());
            }
            Err(e) => {
                if attempt % 5 == 0 {
                    println!("[Tauri] Waiting for backend... attempt {}/30 - {}", attempt, e);
                }
            }
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }

    println!("[Tauri] Backend failed to start after 30 attempts");
    false
}

fn spawn_backend(app: &AppHandle) -> Result<(), String> {
    let shell = app.shell();

    // Create sidecar command - handle errors gracefully
    let sidecar_cmd = match shell.sidecar("dashboard-api") {
        Ok(cmd) => cmd,
        Err(e) => {
            eprintln!("[Tauri] Failed to create sidecar command: {}", e);
            return Err(format!("Failed to create sidecar: {}", e));
        }
    };

    // Spawn with port argument
    let (mut rx, _child) = match sidecar_cmd
        .args(["--port", &BACKEND_PORT.to_string()])
        .spawn()
    {
        Ok(result) => result,
        Err(e) => {
            eprintln!("[Tauri] Failed to spawn sidecar: {}", e);
            return Err(format!("Failed to spawn sidecar: {}", e));
        }
    };

    println!("[Tauri] Spawned dashboard-api sidecar on port {}", BACKEND_PORT);

    // Monitor sidecar output in background
    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    let line_str = String::from_utf8_lossy(&line);
                    println!("[API] {}", line_str);

                    // Detect when uvicorn is ready
                    if line_str.contains("Uvicorn running") || line_str.contains("Application startup complete") {
                        BACKEND_READY.store(true, Ordering::SeqCst);
                        let _ = app_handle.emit("backend-ready", true);
                    }
                }
                CommandEvent::Stderr(line) => {
                    let line_str = String::from_utf8_lossy(&line);
                    eprintln!("[API ERR] {}", line_str);

                    // Uvicorn logs to stderr
                    if line_str.contains("Uvicorn running") || line_str.contains("Application startup complete") {
                        BACKEND_READY.store(true, Ordering::SeqCst);
                        let _ = app_handle.emit("backend-ready", true);
                    }
                }
                CommandEvent::Error(err) => {
                    eprintln!("[API ERROR] {}", err);
                }
                CommandEvent::Terminated(status) => {
                    eprintln!("[API] Sidecar terminated with status: {:?}", status);
                    BACKEND_READY.store(false, Ordering::SeqCst);
                    let _ = app_handle.emit("backend-terminated", status.code);
                    break;
                }
                _ => {}
            }
        }
    });

    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            println!("[Tauri] Starting Claude Orchestrator Dashboard...");

            // Spawn backend sidecar - don't crash if it fails
            match spawn_backend(app.handle()) {
                Ok(()) => println!("[Tauri] Backend sidecar spawned successfully"),
                Err(e) => {
                    eprintln!("[Tauri] Warning: Backend sidecar failed to start: {}", e);
                    eprintln!("[Tauri] App will continue but backend features may not work");
                }
            }

            // Wait for backend in background, then notify frontend
            let app_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                if wait_for_backend_ready().await {
                    BACKEND_READY.store(true, Ordering::SeqCst);
                    let _ = app_handle.emit("backend-ready", true);
                    println!("[Tauri] Backend is ready, frontend can connect");
                } else {
                    let _ = app_handle.emit("backend-failed", "Backend failed to start");
                    eprintln!("[Tauri] Backend failed to become ready");
                }
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_backend_url,
            get_ws_url,
            is_backend_ready
        ])
        .run(tauri::generate_context!())
        .expect("Error running Claude Orchestrator Dashboard");
}
