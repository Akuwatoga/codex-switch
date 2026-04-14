#!/usr/bin/env python3
"""
Codex config.toml 管理模块。

账号认证(auth.json)与 provider(config.toml)是两条独立状态：
- auth.json 决定当前使用哪个官方账号/API Key
- config.toml 决定 Codex 当前走官方 OpenAI 还是第三方 API 服务
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import toml

from config_utils import get_active_service_profile, get_service_profile


CODEX_CONFIG_PATH = Path.home() / ".codex" / "config.toml"
OFFICIAL_MODEL_FALLBACK = "gpt-5.4"

OFFICIAL_ACCOUNT_CONFIG = {
    "model_provider": "openai",
    "model_reasoning_effort": "high",
    "disable_response_storage": True,
    "preferred_auth_method": "bearer",
}


def load_codex_config() -> dict:
    """加载 Codex 配置。"""
    if not CODEX_CONFIG_PATH.exists():
        return {}

    try:
        with open(CODEX_CONFIG_PATH, "r", encoding="utf-8") as f:
            return toml.load(f)
    except Exception as e:
        print(f"⚠️ 读取配置失败: {e}")
        return {}


def save_codex_config(config: dict) -> bool:
    """保存 Codex 配置。"""
    try:
        CODEX_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CODEX_CONFIG_PATH, "w", encoding="utf-8") as f:
            toml.dump(config, f)
        return True
    except Exception as e:
        print(f"⚠️ 保存配置失败: {e}")
        return False


def get_current_provider() -> str:
    """获取当前 model_provider。"""
    config = load_codex_config()
    return str(config.get("model_provider", "openai"))


def _service_profile_to_config(profile: dict) -> Tuple[dict, dict]:
    profile_id = profile["id"]
    provider_table = {
        "name": profile_id,
        "base_url": profile["baseUrl"],
        "wire_api": profile["wireApi"],
        "requires_openai_auth": bool(profile.get("requiresOpenaiAuth", True)),
    }

    bearer_token = str(profile.get("bearerToken") or "").strip()
    if bearer_token:
        provider_table["experimental_bearer_token"] = bearer_token

    config_update = {
        "model_provider": profile_id,
        "model": profile["model"],
        "model_reasoning_effort": profile["reasoningEffort"],
        "disable_response_storage": bool(profile.get("disableResponseStorage", True)),
        "preferred_auth_method": profile["authMethod"],
    }

    return config_update, provider_table


def _build_official_account_config(config: dict) -> dict:
    provider = str(config.get("model_provider") or "").strip()
    current_model = str(config.get("model") or "").strip()
    reasoning_effort = str(config.get("model_reasoning_effort") or "").strip()

    update = dict(OFFICIAL_ACCOUNT_CONFIG)
    update["model"] = current_model if provider == "openai" and current_model else OFFICIAL_MODEL_FALLBACK
    if provider == "openai" and reasoning_effort:
        update["model_reasoning_effort"] = reasoning_effort
    return update


def switch_to_service(profile_id: Optional[str] = None) -> bool:
    """切换到指定 API 服务。"""
    profile = get_service_profile(profile_id)
    if not profile:
        print(f"❌ 未找到服务配置: {profile_id}")
        return False

    config = load_codex_config()
    config_update, provider_table = _service_profile_to_config(profile)
    config.update(config_update)

    providers = config.get("model_providers")
    if not isinstance(providers, dict):
        providers = {}
    config["model_providers"] = providers

    config["model_providers"][profile["id"]] = provider_table

    if save_codex_config(config):
        print(f"✅ 已切换到 API 服务: {profile['name']}")
        print(f"   Provider ID: {profile['id']}")
        print(f"   Base URL: {profile['baseUrl']}")
        print(f"   模型: {profile['model']}")
        return True
    return False


def switch_to_openai_account() -> bool:
    """切换到官方账号模式。"""
    config = load_codex_config()
    config.update(_build_official_account_config(config))

    if save_codex_config(config):
        print("✅ 已切换到官方账号模式")
        print(f"   Provider: {config.get('model_provider', 'openai')}")
        print(f"   模型: {config.get('model', OFFICIAL_MODEL_FALLBACK)}")
        return True
    return False


def switch_to_codex_account(auth_file: Optional[str] = None) -> bool:
    """兼容旧接口，等价于切换到官方账号模式。"""
    _ = auth_file
    return switch_to_openai_account()


def describe_current_provider() -> str:
    provider = get_current_provider()
    if provider == "openai":
        return "官方账号"

    profile = get_service_profile(provider)
    if profile:
        return f"{profile['name']} ({profile['baseUrl']})"
    return provider


if __name__ == "__main__":
    import sys

    provider = get_current_provider()
    print(f"当前模型提供商: {provider}")
    print(f"当前连接说明: {describe_current_provider()}")

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd in ("service", "provider"):
            profile_id = sys.argv[2] if len(sys.argv) > 2 else get_active_service_profile()["id"]
            switch_to_service(profile_id)
        elif cmd in ("account", "official"):
            switch_to_openai_account()
        elif cmd == "status":
            print(f"当前模式: {describe_current_provider()}")
        else:
            print(f"未知命令: {cmd}")
            print("用法: python3 codex_config.py [service <id>|official|status]")
    else:
        print("用法: python3 codex_config.py [service <id>|official|status]")
