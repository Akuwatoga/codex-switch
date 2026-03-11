#!/usr/bin/env python3
"""
配置工具模块

Tauri 应用标识: com.codex.switch
应用配置目录:
- macOS: ~/Library/Application Support/com.codex.switch
- Windows: %APPDATA%/com.codex.switch
- Linux: $XDG_CONFIG_HOME/com.codex.switch 或 ~/.config/com.codex.switch
"""

import json
import os
import re
import sys
from pathlib import Path


def _app_config_base_dir() -> Path:
    """获取与 Tauri 一致的应用配置基础目录"""
    ident = "com.codex.switch"
    if sys.platform == "darwin":  # macOS
        return Path.home() / "Library" / "Application Support" / ident
    if sys.platform.startswith("win"):
        appdata = os.getenv("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(appdata) / ident
    # Linux / others
    xdg = os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(xdg) / ident


def get_config_paths():
    """获取配置文件路径 - 与 Tauri 端一致的 appConfigDir/codex-config 结构"""
    base = _app_config_base_dir()
    codex_dir = base / "codex-config"
    system_auth_file = Path.home() / ".codex" / "auth.json"
    usage_cache_dir = codex_dir / "usage_cache"

    return {
        'codex_dir': codex_dir,
        'auth_file': codex_dir / "auth.json",
        'accounts_dir': codex_dir / "accounts",
        'usage_cache_dir': usage_cache_dir,
        'system_auth_file': system_auth_file,
        'settings_file': codex_dir / "settings.json"
    }


def generate_account_name(email):
    """根据邮箱生成安全的账号名称"""
    if not email:
        return "current_backup"

    # 直接用邮箱用户名，替换特殊字符为下划线
    username = email.split('@')[0]
    return re.sub(r'[^a-zA-Z0-9_]', '_', username)


# 默认设置
DEFAULT_SETTINGS = {
    "maxLogEntries": 500,
    "proxy": {
        "proxyUrl": ""
    },
    "settingsVersion": 3,
    "authMode": "auto"  # "auto" | "api_key" | "account"
}


def load_settings() -> dict:
    """加载应用设置"""
    paths = get_config_paths()
    settings_file = paths['settings_file']

    if not settings_file.exists():
        return DEFAULT_SETTINGS.copy()

    try:
        with open(settings_file, 'r', encoding='utf-8') as f:
            settings = json.load(f)

        # 验证并填充默认值
        result = DEFAULT_SETTINGS.copy()
        if 'maxLogEntries' in settings:
            result['maxLogEntries'] = settings['maxLogEntries']
        if 'proxy' in settings and isinstance(settings['proxy'], dict):
            if 'proxyUrl' in settings['proxy']:
                result['proxy']['proxyUrl'] = settings['proxy']['proxyUrl']
        if 'authMode' in settings and settings['authMode'] in ('auto', 'api_key', 'account'):
            result['authMode'] = settings['authMode']

        return result
    except (json.JSONDecodeError, IOError):
        return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict) -> bool:
    """保存应用设置"""
    paths = get_config_paths()
    settings_file = paths['settings_file']

    try:
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        with open(settings_file, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        return True
    except IOError:
        return False


def get_auth_mode() -> str:
    """获取当前全局认证模式"""
    settings = load_settings()
    return settings.get('authMode', 'auto')


def set_auth_mode(mode: str) -> bool:
    """设置全局认证模式"""
    if mode not in ('auto', 'api_key', 'account'):
        return False

    settings = load_settings()
    settings['authMode'] = mode
    return save_settings(settings)
