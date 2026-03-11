#!/usr/bin/env python3
"""
快速账号切换脚本
用法: python3 switch_account.py <账号名称> [--api|--account] [--set-mode] [--yunyi]
"""

import json
import sys
import shutil
from pathlib import Path
from codex_auth import prepare_auth_for_switch, extract_api_key_from_auth, _has_auth_tokens, extract_stored_auth
from config_utils import get_config_paths, get_auth_mode, set_auth_mode
from codex_config import switch_to_yunyi, switch_to_codex_account, get_current_provider


def sync_to_system(auth_file, system_auth_file):
    """同步配置到系统"""
    if auth_file != system_auth_file and auth_file.exists():
        try:
            system_auth_file.parent.mkdir(exist_ok=True)
            shutil.copy2(auth_file, system_auth_file)
            print(f"✅ 已同步配置到系统")
        except Exception as e:
            print(f"⚠️ 同步到系统失败: {e}")


def switch_account(account_name, force_mode=None, use_yunyi=False):
    """切换到指定账号

    Args:
        account_name: 账号名称
        force_mode: 强制认证模式 (api_key/account/None)
        use_yunyi: 是否使用 yunyi 服务
    """
    paths = get_config_paths()
    codex_dir = paths['codex_dir']
    auth_file = paths['auth_file']
    accounts_dir = paths['accounts_dir']
    system_auth_file = paths['system_auth_file']
    account_file = accounts_dir / f"{account_name}.json"

    if not account_file.exists():
        print(f"❌ 账号配置不存在: {account_name}")
        print(f"📁 请确保文件存在: {account_file}")
        return False

    try:
        # 备份当前配置
        if auth_file.exists():
            backup_file = auth_file.with_suffix('.json.backup')
            shutil.copy2(auth_file, backup_file)
            print(f"📦 已备份当前配置")
        if system_auth_file.exists():
            system_backup_file = system_auth_file.with_suffix('.json.backup')
            shutil.copy2(system_auth_file, system_backup_file)
            print(f"📦 已备份系统配置")

        # 读取目标账号配置
        with open(account_file, 'r', encoding='utf-8') as f:
            target_config = json.load(f)

        # 如果使用 yunyi，先切换到 yunyi 模式
        if use_yunyi:
            print("🔄 切换到 yunyi 模式...")
            switch_to_yunyi()
            # yunyi 模式下写入配置但不使用账号 token
            # 只写入一个占位配置
            clean_config = {
                "OPENAI_API_KEY": "yunyi-mode",
                "auth_mode": "api_key"
            }
        else:
            # 切换到账号模式
            current_provider = get_current_provider()
            if current_provider == 'yunyi':
                print("🔄 切换到 Codex 账号模式...")
                switch_to_codex_account()

            # 确定使用的认证模式：force_mode > 全局设置 > 自动
            effective_mode = force_mode
            if not effective_mode:
                global_mode = get_auth_mode()
                if global_mode != 'auto':
                    # 检查账号是否支持全局设置的模式
                    auth_snapshot = extract_stored_auth(target_config)
                    has_api_key = bool(extract_api_key_from_auth(auth_snapshot))
                    has_tokens = _has_auth_tokens(auth_snapshot)

                    if global_mode == 'api_key' and not has_api_key:
                        print(f"⚠️ 全局设置为 API Key 模式，但账号没有 API Key")
                        if has_tokens:
                            print(f"🔄 自动切换到账号模式")
                            effective_mode = 'account'
                        else:
                            print(f"❌ 账号缺少有效的认证信息")
                            return False
                    elif global_mode == 'account' and not has_tokens:
                        print(f"⚠️ 全局设置为账号模式，但账号没有 token")
                        if has_api_key:
                            print(f"🔄 自动切换到 API Key 模式")
                            effective_mode = 'api_key'
                        else:
                            print(f"❌ 账号缺少有效的认证信息")
                            return False
                    else:
                        effective_mode = global_mode
                        mode_desc = "API Key" if effective_mode == 'api_key' else "账号模式"
                        print(f"🌐 使用全局设置: {mode_desc}")
                # 如果 global_mode == 'auto'，effective_mode 保持为 None，会自动检测

            # 处理认证配置
            clean_config = prepare_auth_for_switch(target_config, force_mode=effective_mode)

        # 确保目录存在
        auth_file.parent.mkdir(exist_ok=True)

        # 写入配置
        with open(auth_file, 'w', encoding='utf-8') as f:
            json.dump(clean_config, f, indent=2, ensure_ascii=False)

        # 同步到系统配置
        sync_to_system(auth_file, system_auth_file)

        # 显示使用的模式
        if use_yunyi:
            print(f"✅ 成功切换到账号: {account_name} (yunyi 模式)")
        elif effective_mode == 'api_key':
            print(f"✅ 成功切换到账号: {account_name} (API Key 模式)")
        elif effective_mode == 'account':
            print(f"✅ 成功切换到账号: {account_name} (账号模式)")
        else:
            print(f"✅ 成功切换到账号: {account_name}")

        # 显示账号信息
        account_id = target_config.get('account_id') or target_config.get('tokens', {}).get('account_id', '未知')
        print(f"🔹 账号ID: {account_id}")

        if use_yunyi:
            print(f"🔗 使用 yunyi 服务: https://yunyi.rdzhvip.com/codex")
        else:
            print(f"🔗 使用 Codex 账号模式")

        return True

    except Exception as e:
        print(f"❌ 切换失败: {e}")
        return False


def list_accounts():
    """列出所有可用账号"""
    accounts_dir = get_config_paths()['accounts_dir']
    account_files = list(accounts_dir.glob("*.json"))

    if not account_files:
        print("📭 没有保存的账号配置")
        return []

    print("📋 可用的账号配置:")
    accounts = []
    for account_file in sorted(account_files):
        try:
            with open(account_file, 'r', encoding='utf-8') as f:
                config = json.load(f)

            account_name = account_file.stem
            account_id = config.get('tokens', {}).get('account_id', '未知ID')
            saved_at = config.get('saved_at', '未知时间')

            # 检测支持的认证模式
            auth_snapshot = extract_stored_auth(config)
            has_api_key = bool(extract_api_key_from_auth(auth_snapshot))
            has_tokens = _has_auth_tokens(auth_snapshot)
            modes = []
            if has_api_key:
                modes.append("API")
            if has_tokens:
                modes.append("Token")
            mode_str = ", ".join(modes) if modes else "未知"

            print(f"  🔹 {account_name}")
            print(f"     ID: {account_id}")
            print(f"     模式: {mode_str}")
            print(f"     保存时间: {saved_at}")
            accounts.append(account_name)
        except:
            account_name = account_file.stem
            print(f"  - {account_name}")
            accounts.append(account_name)

    return accounts


if __name__ == "__main__":
    # 显示当前模式状态
    def show_status():
        current_provider = get_current_provider()
        current_auth_mode = get_auth_mode()
        provider_desc = {'yunyi': 'Yunyi 服务', 'openai': 'Codex 账号模式'}
        auth_desc = {'auto': '自动', 'api_key': 'API Key', 'account': '账号模式'}
        print(f"🔗 当前连接模式: {provider_desc.get(current_provider, current_provider)}")
        print(f"📋 当前认证模式: {auth_desc.get(current_auth_mode, current_auth_mode)}")

    # 处理特殊命令
    if len(sys.argv) >= 2 and sys.argv[1] == '--set-mode':
        if len(sys.argv) < 3:
            print("📖 用法: python3 switch_account.py --set-mode <auto|api|account>")
            sys.exit(1)
        mode = sys.argv[2]
        if mode in ('auto', 'api', 'account'):
            mode_map = {'auto': 'auto', 'api': 'api_key', 'account': 'account'}
            if set_auth_mode(mode_map[mode]):
                mode_desc = {'auto': '自动', 'api': 'API Key', 'account': '账号模式'}
                print(f"✅ 已设置全局认证模式为: {mode_desc[mode]}")
            else:
                print(f"❌ 设置失败")
            sys.exit(0)
        else:
            print(f"❌ 无效的模式: {mode}")
            print("📖 有效模式: auto, api, account")
            sys.exit(1)

    # 处理 yunyi 切换命令
    if len(sys.argv) >= 2 and sys.argv[1] == '--yunyi':
        if len(sys.argv) >= 3 and sys.argv[2] == 'on':
            switch_to_yunyi()
        elif len(sys.argv) >= 3 and sys.argv[2] == 'off':
            switch_to_codex_account()
        else:
            current_provider = get_current_provider()
            if current_provider == 'yunyi':
                print("当前使用 Yunyi 服务")
            else:
                print("当前使用 Codex 账号模式")
        sys.exit(0)

    if len(sys.argv) < 2:
        print("\n" + "=" * 50)
        print("📋 Codex Switch 状态")
        print("=" * 50)
        show_status()
        print("\n📖 用法:")
        print("   切换账号: python3 switch_account.py <账号名称> [--api|--account] [--yunyi]")
        print("   设置认证: python3 switch_account.py --set-mode <auto|api|account>")
        print("   切换yunyi: python3 switch_account.py --yunyi [on|off]")
        print("\n可用账号:")
        list_accounts()
        sys.exit(1)

    account_name = sys.argv[1]
    force_mode = None
    use_yunyi = False

    # 解析参数
    args = sys.argv[2:] if len(sys.argv) > 2 else []
    for arg in args:
        arg = arg.strip()
        if arg in ("--api", "--api-key"):
            force_mode = "api_key"
        elif arg in ("--account", "--token"):
            force_mode = "account"
        elif arg == "--yunyi":
            use_yunyi = True
        else:
            print(f"❌ 未知参数: {arg}")
            print("📖 用法: python3 switch_account.py <账号名称> [--api|--account] [--yunyi]")
            sys.exit(1)

    switch_account(account_name, force_mode=force_mode, use_yunyi=use_yunyi)
