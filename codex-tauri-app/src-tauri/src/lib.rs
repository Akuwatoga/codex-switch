// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use reqwest::header::{ACCEPT, AUTHORIZATION, USER_AGENT};
use serde::{Deserialize, Serialize};
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
const OFFICIAL_MODEL_FALLBACK: &str = "gpt-5.4";
const TRAY_ICON: tauri::image::Image<'_> = tauri::include_image!("icons/tray-icon.png");

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ProxyConfig {
    proxy_url: Option<String>,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct ServiceProfilePayload {
    id: String,
    name: String,
    base_url: String,
    wire_api: String,
    bearer_token: String,
    requires_openai_auth: bool,
    model: String,
    reasoning_effort: String,
    auth_method: String,
    disable_response_storage: bool,
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

fn load_codex_config() -> Result<(std::path::PathBuf, toml::Value), String> {
    let home = dirs::home_dir().ok_or("无法获取用户主目录")?;
    let config_path = home.join(".codex").join("config.toml");

    println!("[load_codex_config] 配置文件路径: {:?}", config_path);

    if !config_path.exists() {
        println!("[load_codex_config] 配置文件不存在");
        return Err("Codex 配置文件不存在".to_string());
    }

    let content = std::fs::read_to_string(&config_path)
        .map_err(|err| format!("读取配置文件失败: {}", err))?;

    let config: toml::Value = content
        .parse()
        .map_err(|err| format!("解析配置文件失败: {}", err))?;

    println!("[load_codex_config] 当前 model_provider: {:?}", config.get("model_provider").map(|v| v.to_string()));
    Ok((config_path, config))
}

fn persist_codex_config(config_path: &std::path::PathBuf, config: &toml::Value) -> Result<(), String> {
    let new_content = toml::to_string_pretty(config).map_err(|err| format!("序列化配置失败: {}", err))?;

    std::fs::write(config_path, new_content).map_err(|err| format!("写入配置文件失败: {}", err))?;
    Ok(())
}

fn resolve_official_model(config: &toml::Value) -> String {
    let provider = config
        .get("model_provider")
        .and_then(|value| value.as_str())
        .unwrap_or_default();
    let model = config
        .get("model")
        .and_then(|value| value.as_str())
        .unwrap_or_default()
        .trim();

    if provider == "openai" && !model.is_empty() {
        model.to_string()
    } else {
        OFFICIAL_MODEL_FALLBACK.to_string()
    }
}

fn resolve_official_reasoning_effort(config: &toml::Value) -> String {
    let provider = config
        .get("model_provider")
        .and_then(|value| value.as_str())
        .unwrap_or_default();
    let effort = config
        .get("model_reasoning_effort")
        .and_then(|value| value.as_str())
        .unwrap_or_default()
        .trim();

    if provider == "openai" && !effort.is_empty() {
        effort.to_string()
    } else {
        "high".to_string()
    }
}

#[tauri::command]
async fn switch_codex_provider(provider: String, profile: Option<ServiceProfilePayload>) -> Result<String, String> {
    println!("[Rust switch_codex_provider] 开始切换, provider={}, profile={:?}", provider, profile.as_ref().map(|p| &p.name));
    let (config_path, mut config) = load_codex_config()?;
    let success_message = if provider == "openai" {
        "已切换到官方账号模式".to_string()
    } else {
        let display_name = profile
            .as_ref()
            .map(|item| item.name.as_str())
            .unwrap_or(provider.as_str());
        format!("已切换到 API 服务: {}", display_name)
    };

    println!("[Rust switch_codex_provider] 写入 config.model_provider = {}", provider);
    if provider == "openai" {
        config["model_provider"] = toml::Value::String("openai".to_string());
        config["model"] = toml::Value::String(resolve_official_model(&config));
        config["model_reasoning_effort"] =
            toml::Value::String(resolve_official_reasoning_effort(&config));
        config["disable_response_storage"] = toml::Value::Boolean(true);
        config["preferred_auth_method"] = toml::Value::String("bearer".to_string());
    } else {
        let profile = profile.ok_or("缺少服务配置".to_string())?;
        if profile.id != provider {
            return Err("provider 与服务配置 ID 不一致".to_string());
        }

        config["model_provider"] = toml::Value::String(profile.id.clone());
        config["model"] = toml::Value::String(profile.model.clone());
        config["model_reasoning_effort"] = toml::Value::String(profile.reasoning_effort.clone());
        config["disable_response_storage"] = toml::Value::Boolean(profile.disable_response_storage);
        config["preferred_auth_method"] = toml::Value::String(profile.auth_method.clone());

        let mut provider_table = toml::map::Map::new();
        provider_table.insert("name".to_string(), toml::Value::String(profile.id.clone()));
        provider_table.insert("base_url".to_string(), toml::Value::String(profile.base_url.clone()));
        provider_table.insert("wire_api".to_string(), toml::Value::String(profile.wire_api.clone()));
        provider_table.insert(
            "requires_openai_auth".to_string(),
            toml::Value::Boolean(profile.requires_openai_auth),
        );

        let bearer = profile.bearer_token.trim();
        if !bearer.is_empty() {
            provider_table.insert(
                "experimental_bearer_token".to_string(),
                toml::Value::String(bearer.to_string()),
            );
        }

        let providers = config
            .as_table_mut()
            .ok_or("Codex 配置格式无效".to_string())?
            .entry("model_providers")
            .or_insert_with(|| toml::Value::Table(toml::map::Map::new()));

        let providers_table = providers
            .as_table_mut()
            .ok_or("model_providers 必须是表结构".to_string())?;
        providers_table.insert(profile.id.clone(), toml::Value::Table(provider_table));
    }

    println!("[Rust switch_codex_provider] 持久化配置到 {:?}", config_path);
    persist_codex_config(&config_path, &config)?;
    println!("[Rust switch_codex_provider] 切换成功: {}", success_message);
    Ok(success_message)
}

#[tauri::command]
async fn get_codex_provider() -> Result<String, String> {
    println!("[get_codex_provider] 被调用");
    let Ok((_, config)) = load_codex_config() else {
        println!("[get_codex_provider] 配置文件加载失败，返回 unknown");
        return Ok("unknown".to_string());
    };

    let provider = config.get("model_provider")
        .and_then(|v| v.as_str())
        .unwrap_or("unknown");

    println!("[get_codex_provider] 返回 provider: {}", provider);
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
        .invoke_handler(tauri::generate_handler![
            fetch_wham_usage,
            switch_codex_provider,
            get_codex_provider
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        #[cfg(target_os = "macos")]
        if let tauri::RunEvent::Reopen { .. } = event {
            show_main_window(app_handle);
        }
    });
}
