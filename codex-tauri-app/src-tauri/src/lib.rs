// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use reqwest::header::{ACCEPT, AUTHORIZATION, USER_AGENT};
use serde::Deserialize;
use serde_json::Value;
use std::error::Error as StdError;
use std::time::Duration;
use tauri::Manager;
use tauri::{
    menu::MenuBuilder,
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    WindowEvent,
};

const WHAM_USAGE_URL: &str = "https://chatgpt.com/backend-api/wham/usage";
const MENU_SHOW: &str = "tray_show";
const MENU_QUIT: &str = "tray_quit";
const TRAY_ICON: tauri::image::Image<'_> = tauri::include_image!("icons/tray-icon.png");

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ProxyConfig {
    proxy_url: Option<String>,
}

fn format_error_chain(err: &(dyn StdError + 'static)) -> String {
    let mut messages = vec![err.to_string()];
    let mut source = err.source();

    while let Some(inner) = source {
        messages.push(inner.to_string());
        source = inner.source();
    }

    messages.join(" | source: ")
}

fn normalize_proxy_value(value: Option<&String>) -> Option<String> {
    value
        .map(|item| item.trim().to_string())
        .filter(|item| !item.is_empty())
}

fn normalize_proxy_url(value: Option<&String>) -> Option<String> {
    let proxy = normalize_proxy_value(value)?;
    if proxy.contains("://") {
        Some(proxy)
    } else {
        Some(format!("http://{}", proxy))
    }
}

fn select_proxy_for_wham_usage(proxy_config: &Option<ProxyConfig>) -> Option<String> {
    let Some(proxy_config) = proxy_config else {
        return None;
    };

    normalize_proxy_url(proxy_config.proxy_url.as_ref())
}

fn apply_proxy(
    builder: reqwest::ClientBuilder,
    selected_proxy: &Option<String>,
) -> Result<reqwest::ClientBuilder, String> {
    let Some(selected_proxy) = selected_proxy else {
        return Ok(builder);
    };

    let http_proxy = reqwest::Proxy::http(selected_proxy)
        .map_err(|err| format!("代理配置无效: {}", format_error_chain(&err)))?;
    let https_proxy = reqwest::Proxy::https(selected_proxy)
        .map_err(|err| format!("代理配置无效: {}", format_error_chain(&err)))?;

    Ok(builder.proxy(http_proxy).proxy(https_proxy))
}

fn show_main_window<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    let _ = ensure_tray_icon(app);

    #[cfg(target_os = "macos")]
    let _ = app.set_activation_policy(tauri::ActivationPolicy::Regular);

    if let Some(window) = app.get_webview_window("main") {
        if let Some(icon) = app.default_window_icon() {
            let _ = window.set_icon(icon.clone());
        }
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn build_tray_icon<R: tauri::Runtime>(app: &tauri::AppHandle<R>) -> tauri::Result<()> {
    let tray_menu = MenuBuilder::new(app)
        .text(MENU_SHOW, "Show Codex Switch")
        .separator()
        .text(MENU_QUIT, "Quit")
        .build()?;

    TrayIconBuilder::with_id("main-tray")
        .menu(&tray_menu)
        .icon(TRAY_ICON.clone())
        .tooltip("Codex Switch")
        .icon_as_template(true)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            MENU_SHOW => show_main_window(app),
            MENU_QUIT => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_main_window(tray.app_handle());
            }
        })
        .build(app)?;

    Ok(())
}

fn ensure_tray_icon<R: tauri::Runtime>(app: &tauri::AppHandle<R>) -> tauri::Result<()> {
    if app.tray_by_id("main-tray").is_some() {
        return Ok(());
    }

    build_tray_icon(app)
}

#[tauri::command]
async fn fetch_wham_usage(access_token: String, proxy_config: Option<ProxyConfig>) -> Result<Value, String> {
    let bearer = format!("Bearer {}", access_token);
    let selected_proxy = select_proxy_for_wham_usage(&proxy_config);

    let builder = reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(5))
        .timeout(Duration::from_secs(12));

    let builder = apply_proxy(builder, &selected_proxy)?;

    let client = builder
        .build()
        .map_err(|err| format!("创建 HTTP 客户端失败: {}", format_error_chain(&err)))?;

    let response = client
        .get(WHAM_USAGE_URL)
        .header(AUTHORIZATION, bearer)
        .header(ACCEPT, "application/json")
        .header(USER_AGENT, "codex-switch/1.0.0")
        .send()
        .await
        .map_err(|err| format!("请求官方用量接口失败: {}", format_error_chain(&err)))?;

    let status = response.status();
    if !status.is_success() {
        return Err(format!("官方用量接口返回 HTTP {}", status.as_u16()));
    }

    response
        .json::<Value>()
        .await
        .map_err(|err| format!("解析官方用量接口响应失败: {}", err))
}

#[tauri::command]
async fn switch_codex_provider(provider: String) -> Result<String, String> {
    let home = dirs::home_dir().ok_or("无法获取用户主目录")?;
    let config_path = home.join(".codex").join("config.toml");

    if !config_path.exists() {
        return Err("Codex 配置文件不存在".to_string());
    }

    let content = std::fs::read_to_string(&config_path)
        .map_err(|err| format!("读取配置文件失败: {}", err))?;

    let mut config: toml::Value = content.parse()
        .map_err(|err| format!("解析配置文件失败: {}", err))?;

    if provider == "yunyi" {
        // 切换到 yunyi 模式
        config["model_provider"] = toml::Value::String("yunyi".to_string());
        config["model"] = toml::Value::String("gpt-5.4".to_string());
        config["preferred_auth_method"] = toml::Value::String("apikey".to_string());

        // 添加或更新 yunyi 配置
        let mut yunyi_table = toml::map::Map::new();
        yunyi_table.insert("name".to_string(), toml::Value::String("yunyi".to_string()));
        yunyi_table.insert("base_url".to_string(), toml::Value::String("https://yunyi.rdzhvip.com/codex".to_string()));
        yunyi_table.insert("wire_api".to_string(), toml::Value::String("responses".to_string()));
        yunyi_table.insert("experimental_bearer_token".to_string(), toml::Value::String("963UQJE1-FZJP-XKQ5-P3CV-QHYCREJJB9K4".to_string()));
        yunyi_table.insert("requires_openai_auth".to_string(), toml::Value::Boolean(true));

        let mut providers = toml::map::Map::new();
        providers.insert("yunyi".to_string(), toml::Value::Table(yunyi_table));
        config["model_providers"] = toml::Value::Table(providers);
    } else if provider == "account" {
        // 切换到账号模式
        config["model_provider"] = toml::Value::String("openai".to_string());
        config["model"] = toml::Value::String("o3".to_string());
        config["preferred_auth_method"] = toml::Value::String("bearer".to_string());

        // 移除 yunyi 配置（如果存在）
        if let Some(providers) = config.get_mut("model_providers") {
            if let Some(providers_table) = providers.as_table_mut() {
                providers_table.remove("yunyi");
            }
        }
    } else {
        return Err("无效的 provider 参数".to_string());
    }

    let new_content = toml::to_string_pretty(&config)
        .map_err(|err| format!("序列化配置失败: {}", err))?;

    std::fs::write(&config_path, new_content)
        .map_err(|err| format!("写入配置文件失败: {}", err))?;

    if provider == "yunyi" {
        Ok("已切换到 yunyi 模式".to_string())
    } else {
        Ok("已切换到 Codex 账号模式".to_string())
    }
}

#[tauri::command]
async fn get_codex_provider() -> Result<String, String> {
    let home = dirs::home_dir().ok_or("无法获取用户主目录")?;
    let config_path = home.join(".codex").join("config.toml");

    if !config_path.exists() {
        return Ok("unknown".to_string());
    }

    let content = std::fs::read_to_string(&config_path)
        .map_err(|err| format!("读取配置文件失败: {}", err))?;

    let config: toml::Value = content.parse()
        .map_err(|err| format!("解析配置文件失败: {}", err))?;

    let provider = config.get("model_provider")
        .and_then(|v| v.as_str())
        .unwrap_or("unknown");

    Ok(provider.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            ensure_tray_icon(&app.handle())?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if window.label() == "main" {
                if let WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window.hide();
                    let _ = ensure_tray_icon(&window.app_handle());
                    #[cfg(target_os = "macos")]
                    let _ = window
                        .app_handle()
                        .set_activation_policy(tauri::ActivationPolicy::Accessory);
                }
            }
        })
        .invoke_handler(tauri::generate_handler![fetch_wham_usage])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        #[cfg(target_os = "macos")]
        if let tauri::RunEvent::Reopen { .. } = event {
            show_main_window(app_handle);
        }
    });
}
