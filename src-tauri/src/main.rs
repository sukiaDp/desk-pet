// 桌宠主程序：透明置顶窗口 + 托盘；前端负责动画，这里只提供文件读取、鼠标位置和 CC 状态汇总。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{fs, path::PathBuf, thread, time::{Duration, SystemTime}};
use tauri::{
    ipc::Response,
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Emitter, Manager, PhysicalPosition, PhysicalSize, WebviewWindow,
};

fn assets_dir() -> PathBuf {
    std::env::var("DESK_PET_ASSETS")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"), "/../assets")))
}

fn sessions_dir() -> PathBuf {
    PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".cache/desk-pet/sessions")
}

/// 读素材目录里的文件（返回原始字节，前端转成 ImageBitmap / JSON）
#[tauri::command]
fn read_asset(path: String) -> Result<Response, String> {
    if path.contains("..") { return Err("bad path".into()); }
    fs::read(assets_dir().join(path)).map(Response::new).map_err(|e| e.to_string())
}

fn scale() -> u32 {
    std::env::var("DESK_PET_SCALE").ok().and_then(|v| v.parse().ok()).filter(|v| *v >= 1).unwrap_or(1)
}

/// 放大倍数（整数，最近邻）。窗口物理尺寸 = 200x240 × 倍数
#[tauri::command]
fn pet_scale() -> u32 { scale() }

/// 透明处点穿：前端按像素 alpha 判断后调用
#[tauri::command]
fn set_through(window: WebviewWindow, on: bool) {
    let _ = window.set_ignore_cursor_events(on);
}

/// 汇总所有 CC 会话：等待 > 出错 > 工作中 > 完成 > 空闲。
/// 3 分钟没心跳的文件视为会话已退出；ended 和 1 天前的文件顺手删掉。
/// 完成/出错 超过 2 分钟回落为空闲。
#[tauri::command]
fn cc_state() -> serde_json::Value {
    let now = SystemTime::now();
    let mut counts = std::collections::BTreeMap::<String, u32>::new();
    if let Ok(rd) = fs::read_dir(sessions_dir()) {
        for ent in rd.flatten() {
            let p = ent.path();
            let age = ent.metadata().and_then(|m| m.modified()).ok()
                .and_then(|m| now.duration_since(m).ok()).unwrap_or_default().as_secs();
            let state = fs::read_to_string(&p).ok()
                .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())
                .and_then(|v| v["state"].as_str().map(String::from))
                .unwrap_or_default();
            if state == "ended" || age > 86400 { let _ = fs::remove_file(&p); continue; }
            if age > 180 { continue; }
            let state = if (state == "done" || state == "error") && age > 120 { "idle".to_string() } else { state };
            *counts.entry(state).or_default() += 1;
        }
    }
    let top = ["waiting", "error", "working", "done", "idle"]
        .into_iter().find(|s| counts.contains_key(*s)).unwrap_or("idle");
    serde_json::json!({ "state": top, "counts": counts })
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![read_asset, set_through, cc_state, pet_scale])
        .setup(|app| {
            let win = app.get_webview_window("main").unwrap();
            let k = scale();
            let _ = win.set_size(PhysicalSize::new(200 * k, 240 * k));
            // 默认放在主屏右下角
            if let Ok(Some(m)) = win.primary_monitor() {
                let (s, sz) = (m.position(), m.size());
                let _ = win.set_position(PhysicalPosition::new(
                    s.x + sz.width as i32 - 60 - 200 * k as i32, s.y + sz.height as i32 - 80 - 240 * k as i32));
            }
            let _ = win.show();

            let toggle = MenuItem::with_id(app, "toggle", "显示 / 隐藏", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
            TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("羊角修女")
                .menu(&Menu::with_items(app, &[&toggle, &quit])?)
                .on_menu_event(|app, ev| match ev.id().as_ref() {
                    "quit" => app.exit(0),
                    "toggle" => if let Some(w) = app.get_webview_window("main") {
                        if w.is_visible().unwrap_or(true) { let _ = w.hide(); } else { let _ = w.show(); }
                    },
                    _ => {}
                })
                .build(app)?;

            // 全局鼠标位置（相对窗口，物理像素）推给前端：用于视线和点穿判断
            let w = win.clone();
            thread::spawn(move || loop {
                thread::sleep(Duration::from_millis(40));
                if let (Ok(c), Ok(p)) = (w.cursor_position(), w.outer_position()) {
                    let _ = w.emit("cursor", (c.x - p.x as f64, c.y - p.y as f64));
                }
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("desk-pet failed");
}
