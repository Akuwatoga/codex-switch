#!/usr/bin/env python3
"""
Codex 配置管理模块
用于管理 Codex 的 config.toml 配置
"""

import os
import toml
from pathlib import Path


# Codex 配置路径
CODEX_CONFIG_PATH = Path.home() / ".codex" / "config.toml"

# 默认 yunyi 配置
YUNYI_CONFIG = {
    "model_provider": "yunyi",
    "model": "gpt-5.4",
    "model_reasoning_effort": "high",
    "disable_response_storage": True,
    "preferred_auth_method": "apikey",
    "model_providers": {
        "yunyi": {
            "name": "yunyi",
            "base_url": "https://yunyi.rdzhvip.com/codex",
            "wire_api": "responses",
            "experimental_bearer_token": "963UQJE1-FZJP-XKQ5-P3CV-QHYCREJJB9K4",
            "requires_openai_auth": True
        }
    }
}

# OpenAI 账号模式配置
OPENAI_ACCOUNT_CONFIG = {
    "model_provider": "openai",
    "model": "o3",
    "model_reasoning_effort": "high",
    "disable_response_storage": True,
    "preferred_auth_method": "bearer"
}


def load_codex_config() -> dict:
    """加载 Codex 配置"""
    if not CODEX_CONFIG_PATH.exists():
        return {}

    try:
        with open(CODEX_CONFIG_PATH, 'r', encoding='utf-8') as f:
            return toml.load(f)
    except Exception as e:
        print(f"⚠️ 读取配置失败: {e}")
        return {}


def save_codex_config(config: dict) -> bool:
    """保存 Codex 配置"""
    try:
        CODEX_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CODEX_CONFIG_PATH, 'w', encoding='utf-8') as f:
            toml.dump(config, f)
        return True
    except Exception as e:
        print(f"⚠️ 保存配置失败: {e}")
        return False


def get_current_provider() -> str:
    """获取当前使用的模型提供商"""
    config = load_codex_config()
    return config.get('model_provider', 'unknown')


def switch_to_yunyi() -> bool:
    """切换到 yunyi 模式"""
    config = load_codex_config()

    # 更新配置
    config.update(YUNYI_CONFIG)

    # 确保 model_providers 存在
    if 'model_providers' not in config:
        config['model_providers'] = {}

    config['model_providers'].update(YUNYI_CONFIG.get('model_providers', {}))

    if save_codex_config(config):
        print("✅ 已切换到 yunyi 模式")
        print(f"   模型: {config.get('model', 'gpt-5.4')}")
        print(f"   Base URL: {YUNYI_CONFIG['model_providers']['yunyi']['base_url']}")
        return True
    return False


def switch_to_openai_account() -> bool:
    """切换到 OpenAI 账号模式（直接使用 auth.json）"""
    config = load_codex_config()

    # 移除 yunyi 相关配置
    config.update(OPENAI_ACCOUNT_CONFIG)

    # 移除 yunyi model_providers
    if 'model_providers' in config and 'yunyi' in config['model_providers']:
        del config['model_providers']['yunyi']

    # 如果 model_providers 为空，删除它
    if 'model_providers' in config and not config['model_providers']:
        del config['model_providers']

    if save_codex_config(config):
        print("✅ 已切换到 OpenAI 账号模式")
        print(f"   模型: {config.get('model', 'o3')}")
        print("   将使用 ~/.codex/auth.json 中的账号认证")
        return True
    return False


def switch_to_codex_account(auth_file: str = None) -> bool:
    """
    切换到 Codex 账号模式（使用指定账号的认证）

    Args:
        auth_file: 账号配置文件路径，如果为 None 则使用系统当前的 auth.json
    """
    config = load_codex_config()

    # Codex 账号模式配置
    config.update({
        "model_provider": "openai",
        "model": "o3",
        "model_reasoning_effort": "high",
        "disable_response_storage": True,
        "preferred_auth_method": "bearer"
    })

    # 移除 yunyi model_providers
    if 'model_providers' in config and 'yunyi' in config['model_providers']:
        del config['model_providers']['yunyi']

    # 如果 model_providers 为空，删除它
    if 'model_providers' in config and not config['model_providers']:
        del config['model_providers']

    if save_codex_config(config):
        print("✅ 已切换到 Codex 账号模式")
        print(f"   模型: {config.get('model', 'o3')}")
        print("   将使用 ~/.codex/auth.json 中的账号认证")
        return True
    return False


if __name__ == "__main__":
    import sys

    provider = get_current_provider()
    print(f"当前模型提供商: {provider}")

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "yunyi":
            switch_to_yunyi()
        elif cmd == "account":
            switch_to_codex_account()
        elif cmd == "status":
            provider = get_current_provider()
            print(f"当前模式: {provider}")
        else:
            print(f"未知命令: {cmd}")
            print("用法: python3 codex_config.py [yunyi|account|status]")
    else:
        print("用法: python3 codex_config.py [yunyi|account|status]")
