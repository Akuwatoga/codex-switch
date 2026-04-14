#!/usr/bin/env python3
"""
配置工具模块

Tauri 应用标识: com.codex.switch
应用配置目录:
- macOS: ~/Library/Application Support/com.codex.switch
- Windows: %APPDATA%/com.codex.switch
- Linux: $XDG_CONFIG_HOME/com.codex.switch 或 ~/.config/com.codex.switch
"""

import copy
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional


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


# 默认 API 服务配置
DEFAULT_SERVICE_PROFILES = [
    {
        "id": "yunyi",
        "name": "Yunyi",
        "baseUrl": "https://yunyi.rdzhvip.com/codex",
        "wireApi": "responses",
        "bearerToken": "963UQJE1-FZJP-XKQ5-P3CV-QHYCREJJB9K4",
        "requiresOpenaiAuth": True,
        "model": "gpt-5.3-codex",
        "reasoningEffort": "high",
        "authMethod": "apikey",
        "disableResponseStorage": True,
    }
]


def _normalize_service_profile(profile: dict, index: int = 0) -> Optional[dict]:
    """规范化单个服务配置，忽略明显无效的数据。"""
    if not isinstance(profile, dict):
        return None

    raw_id = str(profile.get("id") or "").strip()
    profile_id = re.sub(r"[^a-zA-Z0-9_-]", "-", raw_id).strip("-").lower()
    if not profile_id:
        profile_id = f"service-{index + 1}"

    base_url = str(profile.get("baseUrl") or "").strip()
    if not base_url:
        return None

    auth_method = str(profile.get("authMethod") or "apikey").strip().lower()
    if auth_method not in ("apikey", "bearer"):
        auth_method = "apikey"

    return {
        "id": profile_id,
        "name": str(profile.get("name") or profile_id).strip() or profile_id,
        "baseUrl": base_url,
        "wireApi": str(profile.get("wireApi") or "responses").strip() or "responses",
        "bearerToken": str(profile.get("bearerToken") or "").strip(),
        "requiresOpenaiAuth": bool(profile.get("requiresOpenaiAuth", True)),
        "model": str(profile.get("model") or "gpt-5.3-codex").strip() or "gpt-5.3-codex",
        "reasoningEffort": str(profile.get("reasoningEffort") or "high").strip() or "high",
        "authMethod": auth_method,
        "disableResponseStorage": bool(profile.get("disableResponseStorage", True)),
    }


def normalize_service_profiles(profiles) -> list[dict]:
    """规范化服务配置列表，确保至少保留一个可用默认项。"""
    normalized = []
    seen_ids = set()

    if isinstance(profiles, list):
        for index, profile in enumerate(profiles):
            item = _normalize_service_profile(profile, index)
            if not item or item["id"] in seen_ids:
                continue
            normalized.append(item)
            seen_ids.add(item["id"])

    if normalized:
        return normalized

    return copy.deepcopy(DEFAULT_SERVICE_PROFILES)


# 默认设置
DEFAULT_SETTINGS = {
    "maxLogEntries": 500,
    "proxy": {
        "proxyUrl": ""
    },
    "settingsVersion": 4,
    "authMode": "auto",  # "auto" | "api_key" | "account"
    "activeServiceProfile": DEFAULT_SERVICE_PROFILES[0]["id"],
    "serviceProfiles": copy.deepcopy(DEFAULT_SERVICE_PROFILES),
}


def load_settings() -> dict:
    """加载应用设置"""
    paths = get_config_paths()
    settings_file = paths['settings_file']

    if not settings_file.exists():
        return copy.deepcopy(DEFAULT_SETTINGS)

    try:
        with open(settings_file, 'r', encoding='utf-8') as f:
            settings = json.load(f)

        # 验证并填充默认值
        result = copy.deepcopy(DEFAULT_SETTINGS)
        if 'maxLogEntries' in settings:
            result['maxLogEntries'] = settings['maxLogEntries']
        if 'proxy' in settings and isinstance(settings['proxy'], dict):
            if 'proxyUrl' in settings['proxy']:
                result['proxy']['proxyUrl'] = settings['proxy']['proxyUrl']
        if 'authMode' in settings and settings['authMode'] in ('auto', 'api_key', 'account'):
            result['authMode'] = settings['authMode']
        result['serviceProfiles'] = normalize_service_profiles(settings.get('serviceProfiles'))
        active_service = str(settings.get('activeServiceProfile') or '').strip().lower()
        available_ids = {profile['id'] for profile in result['serviceProfiles']}
        result['activeServiceProfile'] = (
            active_service if active_service in available_ids else result['serviceProfiles'][0]['id']
        )

        return result
    except (json.JSONDecodeError, IOError):
        return copy.deepcopy(DEFAULT_SETTINGS)


def save_settings(settings: dict) -> bool:
    """保存应用设置"""
    paths = get_config_paths()
    settings_file = paths['settings_file']

    try:
        normalized = copy.deepcopy(DEFAULT_SETTINGS)
        normalized['maxLogEntries'] = settings.get('maxLogEntries', normalized['maxLogEntries'])
        proxy = settings.get('proxy') if isinstance(settings.get('proxy'), dict) else {}
        normalized['proxy']['proxyUrl'] = proxy.get('proxyUrl', normalized['proxy']['proxyUrl'])
        if settings.get('authMode') in ('auto', 'api_key', 'account'):
            normalized['authMode'] = settings['authMode']
        normalized['serviceProfiles'] = normalize_service_profiles(settings.get('serviceProfiles'))
        active_service = str(settings.get('activeServiceProfile') or '').strip().lower()
        available_ids = {profile['id'] for profile in normalized['serviceProfiles']}
        normalized['activeServiceProfile'] = (
            active_service if active_service in available_ids else normalized['serviceProfiles'][0]['id']
        )

        settings_file.parent.mkdir(parents=True, exist_ok=True)
        with open(settings_file, 'w', encoding='utf-8') as f:
            json.dump(normalized, f, indent=2, ensure_ascii=False)
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


def get_service_profiles() -> list[dict]:
    """返回全部服务配置。"""
    return load_settings().get('serviceProfiles', copy.deepcopy(DEFAULT_SERVICE_PROFILES))


def get_active_service_profile() -> dict:
    """返回当前激活的服务配置。"""
    settings = load_settings()
    active_id = settings.get('activeServiceProfile')
    for profile in settings.get('serviceProfiles', []):
        if profile.get('id') == active_id:
            return profile
    return copy.deepcopy(DEFAULT_SERVICE_PROFILES[0])


def get_service_profile(profile_id: Optional[str]) -> Optional[dict]:
    """按 ID 查找服务配置；未传时返回当前激活项。"""
    if not profile_id:
        return get_active_service_profile()

    target_id = str(profile_id).strip().lower()
    for profile in get_service_profiles():
        if profile.get('id') == target_id:
            return profile
    return None
