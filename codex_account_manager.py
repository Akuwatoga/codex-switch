#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenAI Codex 账号配置管理器
用于管理和切换多个 OpenAI 账号配置
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from codex_auth import build_account_record, extract_account_id_from_auth, extract_email_from_auth, extract_stored_auth, validate_auth_config
from usage_checker import CodexUsageChecker
from config_utils import get_config_paths, generate_account_name


class CodexAccountManager:
    def __init__(self):
        # 使用项目内配置路径
        config = get_config_paths()
        self.codex_dir = config['codex_dir']
        self.auth_file = config['auth_file']
        self.accounts_dir = config['accounts_dir']
        self.system_auth_file = config['system_auth_file']
        
        # 确保目录存在
        self.codex_dir.mkdir(parents=True, exist_ok=True)
        self.accounts_dir.mkdir(parents=True, exist_ok=True)
    
    def _load_config(self, file_path):
        """加载 JSON 配置文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"❌ 读取配置失败: {e}")
            return None
    
    def _save_config(self, file_path, config):
        """保存 JSON 配置文件"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            return True
        except (OSError, IOError) as e:
            print(f"❌ 保存配置失败: {e}")
            return False
    
    def _copy_to_system(self):
        """将当前账号复制到系统 Codex 配置"""
        try:
            if self.auth_file.exists():
                self.system_auth_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.auth_file, self.system_auth_file)
        except (OSError, IOError) as e:
            print(f"❌ 复制到系统失败: {e}")
            return False
    
    def save_current_account(self, account_name):
        """保存当前账号配置（从系统 Codex 配置读取）"""
        if not self.system_auth_file.exists():
            print("错误: 系统 Codex 配置不存在")
            print(f"请检查: {self.system_auth_file}")
            return False
        
        try:
            # 从系统 Codex 配置读取
            current_config = self._load_config(self.system_auth_file)
            account_record = build_account_record(current_config, account_name, saved_at=datetime.now().isoformat())
            
            # 保存到accounts目录
            account_file = self.accounts_dir / f"{account_name}.json"
            if self._save_config(account_file, account_record):
                print(f"✅ 成功保存账号配置: {account_name}")
                print(f"📁 保存位置: {account_file}")
                return True
            return False
            
        except Exception as e:
            print(f"❌ 保存失败: {e}")
            return False
    
    def save_account_from_config(self, account_name, config_data):
        """从提供的配置数据保存账号"""
        try:
            config = json.loads(config_data) if isinstance(config_data, str) else config_data
            account_record = build_account_record(config, account_name, saved_at=datetime.now().isoformat())
            
            account_file = self.accounts_dir / f"{account_name}.json"
            if self._save_config(account_file, account_record):
                print(f"✅ 成功保存账号配置: {account_name}")
                return True
            return False
        except json.JSONDecodeError as e:
            print(f"❌ JSON 格式错误: {e}")
            return False
    
    def list_accounts(self):
        """列出所有保存的账号"""
        account_files = list(self.accounts_dir.glob("*.json"))
        
        if not account_files:
            print("📭 没有保存的账号配置")
            return []
        
        accounts = []
        print("\n📋 已保存的账号配置:")
        print("-" * 60)
        
        for account_file in sorted(account_files):
            try:
                with open(account_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                account_name = account_file.stem
                saved_at = config.get('saved_at', '未知时间')
                account_id = config.get('account_id') or extract_account_id_from_auth(config) or '未知ID'
                
                print(f"🔹 {account_name}")
                print(f"   账号ID: {account_id}")
                print(f"   保存时间: {saved_at}")
                print()
                
                accounts.append(account_name)
                
            except Exception as e:
                print(f"❌ 读取 {account_file.name} 失败: {e}")
        
        return accounts
    
    def switch_account(self, account_name):
        """切换到指定账号"""
        account_file = self.accounts_dir / f"{account_name}.json"
        
        if not account_file.exists():
            print(f"❌ 账号配置不存在: {account_name}")
            return False
        
        try:
            # 读取目标账号配置
            target_config = self._load_config(account_file)
            clean_config = extract_stored_auth(target_config)
            validate_auth_config(clean_config)
            
            if self.system_auth_file.exists():
                backup_file = self.system_auth_file.with_suffix('.json.backup')
                shutil.copy2(self.system_auth_file, backup_file)

            # 直接写入系统 Codex 配置
            self.system_auth_file.parent.mkdir(parents=True, exist_ok=True)
            if self._save_config(self.system_auth_file, clean_config):
                print(f"✅ 成功切换到账号: {account_name}")
                
                # 显示账号信息
                account_id = target_config.get('account_id') or extract_account_id_from_auth(target_config) or '未知'
                print(f"🔹 账号ID: {account_id}")
                print(f"📂 系统配置: {self.system_auth_file}")
                return True
            
        except Exception as e:
            print(f"❌ 切换失败: {e}")
            return False
    
    
    def delete_account(self, account_name):
        """删除指定账号配置"""
        account_file = self.accounts_dir / f"{account_name}.json"
        
        if not account_file.exists():
            print(f"❌ 账号配置不存在: {account_name}")
            return False
        
        try:
            account_file.unlink()
            print(f"🗑️ 已删除账号配置: {account_name}")
            return True
        except Exception as e:
            print(f"❌ 删除失败: {e}")
            return False
    
    def show_current_account(self):
        """显示当前账号信息"""
        if not self.system_auth_file.exists():
            print("❌ 当前没有活跃的账号配置")
            print(f"请检查: {self.system_auth_file}")
            return
        
        try:
            config = self._load_config(self.system_auth_file)
            
            account_id = extract_account_id_from_auth(config) or '未知'
            last_refresh = config.get('last_refresh', '未知')
            
            print("\n🔄 当前活跃账号:")
            print(f"账号ID: {account_id}")
            print(f"最后刷新: {last_refresh}")
            print(f"系统配置: {self.system_auth_file}")
            
        except Exception as e:
            print(f"❌ 读取当前配置失败: {e}")

    def check_account_usage(self, account_name=None, force_refresh=False):
        """检查账号用量"""
        try:
            # 如果指定了账号名称，读取该账号配置
            if account_name:
                account_file = self.accounts_dir / f"{account_name}.json"
                if not account_file.exists():
                    print(f"❌ 账号配置不存在: {account_name}")
                    return False
                
                config = self._load_config(account_file)
                print(f"\n📊 正在查询账号 {account_name} 的用量...")
            else:
                # 检查当前账号
                if not self.system_auth_file.exists():
                    print("❌ 当前没有活跃的账号配置")
                    return False
                
                config = self._load_config(self.system_auth_file)
                print("\n📊 正在查询当前账号的用量...")
            
            # 提取邮箱
            email = extract_email_from_auth(config)
            
            if not email:
                print("❌ 未能提取账号邮箱信息")
                return False
            
            # 创建用量检查器
            checker = CodexUsageChecker()
            
            if force_refresh:
                # 强制从官方接口刷新
                summary = checker.get_usage_summary(email, auth_data=config)
            else:
                # 先尝试从缓存读取
                cached_data = checker.load_usage_data(email)
                if cached_data:
                    print("📁 从缓存读取用量数据...")
                    summary = {
                        "email": email,
                        "check_time": cached_data.get("check_time", ""),
                        "status": "success",
                        "plan_type": cached_data.get("plan_type"),
                        "token_usage": cached_data.get("token_usage", {}),
                        "rate_limits": cached_data.get("rate_limits", {}),
                        "additional_rate_limits": cached_data.get("additional_rate_limits", []),
                        "errors": cached_data.get("errors", []),
                        "from_cache": True
                    }
                else:
                    print("⚠️ 没有缓存数据，请先切换到该账号后执行刷新")
                    print("💡 提示: 刷新会直接查询官方用量接口")
                    return False
            
            # 显示格式化的结果
            print("\n" + "=" * 60)
            formatted_summary = checker.format_usage_summary(summary)
            print(formatted_summary)
            print("=" * 60)
            
            return True
            
        except Exception as e:
            print(f"❌ 检查用量失败: {e}")
            return False



def main():
    print("🚀 Codex Switch")
    print(f"📁 配置存储: {Path(__file__).parent / 'codex-config'}")
    
    manager = CodexAccountManager()
    
    while True:
        print("\n" + "=" * 50)
        print("🚀 Codex Switch")
        print("=" * 50)
        print("1. 保存当前账号配置")
        print("2. 从配置内容添加账号")
        print("3. 列出所有账号")
        print("4. 切换账号")
        print("5. 删除账号配置")
        print("6. 显示当前账号")
        print("7. 查看当前账号用量（缓存）")
        print("8. 查看指定账号用量（缓存）")
        print("9. 刷新当前账号用量（官方接口）")
        print("0. 退出")
        print("-" * 50)
        
        try:
            choice = input("请选择操作 (0-9): ").strip()
        except KeyboardInterrupt:
            print("\n👋 再见！")
            break
        
        if choice == "1":
            try:
                account_name = input("请输入账号名称: ").strip()
                if account_name:
                    manager.save_current_account(account_name)
                else:
                    print("❌ 账号名称不能为空")
            except KeyboardInterrupt:
                print("\n⚠️ 操作取消")
                continue
        
        elif choice == "2":
            try:
                account_name = input("请输入账号名称: ").strip()
                if not account_name:
                    print("❌ 账号名称不能为空")
                    continue
                
                print("请粘贴完整的 auth.json 配置内容 (以 {} 开始和结束):")
                print("输入完成后按 Ctrl+D (Linux/Mac) 或 Ctrl+Z (Windows) 结束:")
                
                config_lines = []
                try:
                    while True:
                        line = input()
                        config_lines.append(line)
                except EOFError:
                    pass
                except KeyboardInterrupt:
                    print("\n⚠️ 操作取消")
                    continue
                
                config_text = '\n'.join(config_lines).strip()
                if config_text:
                    manager.save_account_from_config(account_name, config_text)
                else:
                    print("❌ 配置内容不能为空")
            except KeyboardInterrupt:
                print("\n⚠️ 操作取消")
                continue
        
        elif choice == "3":
            manager.list_accounts()
        
        elif choice == "4":
            accounts = manager.list_accounts()
            if accounts:
                try:
                    account_name = input("请输入要切换的账号名称: ").strip()
                    if account_name in accounts:
                        manager.switch_account(account_name)
                    else:
                        print("❌ 账号名称不存在")
                except KeyboardInterrupt:
                    print("\n⚠️ 操作取消")
                    continue
        
        elif choice == "5":
            accounts = manager.list_accounts()
            if accounts:
                try:
                    account_name = input("请输入要删除的账号名称: ").strip()
                    if account_name in accounts:
                        try:
                            confirm = input(f"确认删除账号 '{account_name}' 吗? (y/N): ").strip().lower()
                            if confirm == 'y':
                                manager.delete_account(account_name)
                        except KeyboardInterrupt:
                            print("\n⚠️ 操作取消")
                            continue
                    else:
                        print("❌ 账号名称不存在")
                except KeyboardInterrupt:
                    print("\n⚠️ 操作取消")
                    continue
        
        elif choice == "6":
            manager.show_current_account()
        
        elif choice == "7":
            manager.check_account_usage()
        
        elif choice == "8":
            accounts = manager.list_accounts()
            if accounts:
                try:
                    account_name = input("请输入要查看用量的账号名称: ").strip()
                    if account_name in accounts:
                        manager.check_account_usage(account_name)
                    else:
                        print("❌ 账号名称不存在")
                except KeyboardInterrupt:
                    print("\n⚠️ 操作取消")
                    continue
        
        elif choice == "9":
            manager.check_account_usage(force_refresh=True)
        
        elif choice == "0":
            print("👋 再见!")
            break
        
        else:
            print("❌ 无效选择，请重试")


if __name__ == "__main__":
    main()
