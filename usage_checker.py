#!/usr/bin/env python3
"""
Codex/ChatGPT usage queries aligned with the official Codex desktop client.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from codex_auth import extract_email_from_auth
from config_utils import get_config_paths

WHAM_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
REQUEST_TIMEOUT_SECONDS = 20


def extract_access_token_from_auth(auth_data: Optional[Dict[str, Any]]) -> Optional[str]:
    """Extract the current access token from auth.json-compatible data."""
    if not isinstance(auth_data, dict):
        return None

    tokens = auth_data.get("tokens")
    if not isinstance(tokens, dict):
        return None

    access_token = tokens.get("access_token")
    return access_token if isinstance(access_token, str) and access_token else None


class CodexUsageChecker:
    """Usage checker backed by the same /wham/usage endpoint as the official app."""

    def __init__(self, usage_cache_dir=None):
        if usage_cache_dir:
            self.usage_cache_dir = Path(usage_cache_dir)
        else:
            self.usage_cache_dir = get_config_paths()["usage_cache_dir"]

        self.usage_cache_dir.mkdir(parents=True, exist_ok=True)

        try:
            self.cache_ttl_hours = int(os.getenv("CODEX_USAGE_CACHE_TTL_HOURS", "720"))
        except ValueError:
            self.cache_ttl_hours = 720

    def _remaining_percent(self, limit: Dict[str, Any]) -> Optional[float]:
        used_percent = limit.get("used_percent")
        if used_percent is None:
            return None

        try:
            remaining_percent = 100 - float(used_percent)
        except (TypeError, ValueError):
            return None

        return max(0.0, min(100.0, remaining_percent))

    def _read_auth_data(self) -> Optional[Dict[str, Any]]:
        auth_path = get_config_paths()["system_auth_file"]
        if not auth_path.exists():
            return None

        try:
            with open(auth_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, IOError, json.JSONDecodeError):
            return None

    def _normalize_window(self, window: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(window, dict):
            return None

        limit_window_seconds = window.get("limit_window_seconds")
        reset_after_seconds = window.get("reset_after_seconds")
        reset_at = window.get("reset_at")
        used_percent = window.get("used_percent")

        try:
            used_percent = float(used_percent) if used_percent is not None else None
        except (TypeError, ValueError):
            used_percent = None

        try:
            limit_window_seconds = int(limit_window_seconds) if limit_window_seconds is not None else None
        except (TypeError, ValueError):
            limit_window_seconds = None

        try:
            reset_after_seconds = int(reset_after_seconds) if reset_after_seconds is not None else None
        except (TypeError, ValueError):
            reset_after_seconds = None

        try:
            reset_at = int(reset_at) if reset_at is not None else None
        except (TypeError, ValueError):
            reset_at = None

        normalized = {
            "used_percent": used_percent,
            "window_minutes": (limit_window_seconds / 60) if limit_window_seconds is not None else None,
            "limit_window_seconds": limit_window_seconds,
            "resets_in_seconds": reset_after_seconds,
            "resets_at": reset_at,
        }
        return normalized

    def _normalize_rate_limit(self, rate_limit: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(rate_limit, dict):
            return {}

        primary = self._normalize_window(rate_limit.get("primary_window"))
        secondary = self._normalize_window(rate_limit.get("secondary_window"))

        result: Dict[str, Any] = {
            "allowed": rate_limit.get("allowed"),
            "limit_reached": rate_limit.get("limit_reached"),
        }
        if primary:
            result["primary"] = primary
        if secondary:
            result["secondary"] = secondary
        return result

    def _normalize_additional_limits(self, limits: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        if not isinstance(limits, list):
            return normalized

        for item in limits:
            if not isinstance(item, dict):
                continue

            limit_name = item.get("limit_name")
            rate_limit = self._normalize_rate_limit(item.get("rate_limit"))
            if not rate_limit:
                continue

            normalized.append(
                {
                    "limit_name": limit_name,
                    "metered_feature": item.get("metered_feature"),
                    "allowed": rate_limit.get("allowed"),
                    "limit_reached": rate_limit.get("limit_reached"),
                    "primary": rate_limit.get("primary"),
                    "secondary": rate_limit.get("secondary"),
                }
            )

        return normalized

    def _request_usage_payload(self, access_token: str) -> Dict[str, Any]:
        request = urllib.request.Request(
            WHAM_USAGE_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "User-Agent": "codex-switch/1.0.0",
            },
        )

        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            payload = response.read().decode(charset)
            data = json.loads(payload)
            if not isinstance(data, dict):
                raise ValueError("usage payload is not a JSON object")
            return data

    def save_usage_data(self, email: str, usage_data: Dict[str, Any]) -> bool:
        if not email:
            return False

        try:
            safe_email = email.replace("@", "_at_").replace(".", "_").replace("+", "_plus_")
            cache_file = self.usage_cache_dir / f"{safe_email}_usage.json"

            cache_data = {
                "email": email,
                "last_updated": datetime.now().isoformat(),
                "usage_data": usage_data,
            }

            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)

            return True
        except (OSError, IOError):
            return False

    def load_usage_data(self, email: str) -> Optional[Dict[str, Any]]:
        if not email:
            return None

        try:
            safe_email = email.replace("@", "_at_").replace(".", "_").replace("+", "_plus_")
            cache_file = self.usage_cache_dir / f"{safe_email}_usage.json"

            if not cache_file.exists():
                return None

            with open(cache_file, "r", encoding="utf-8") as f:
                cache_data = json.load(f)

            last_updated = datetime.fromisoformat(cache_data.get("last_updated", ""))
            if datetime.now() - last_updated > timedelta(hours=self.cache_ttl_hours):
                return None

            return cache_data.get("usage_data")
        except (OSError, IOError, json.JSONDecodeError, ValueError):
            return None

    def get_usage_summary(self, email: str = None, auth_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        summary = {
            "check_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "checking...",
            "email": email,
            "plan_type": None,
            "token_usage": {},
            "rate_limits": {},
            "additional_rate_limits": [],
            "errors": [],
        }

        active_auth = auth_data or self._read_auth_data()
        if not active_auth:
            summary["status"] = "failed"
            summary["errors"].append("未找到当前 Codex 认证配置")
            return summary

        access_token = extract_access_token_from_auth(active_auth)
        if not access_token:
            summary["status"] = "failed"
            summary["errors"].append("当前账号缺少 access_token")
            return summary

        resolved_email = email or extract_email_from_auth(active_auth)
        if resolved_email:
            summary["email"] = resolved_email

        try:
            payload = self._request_usage_payload(access_token)
        except urllib.error.HTTPError as exc:
            summary["status"] = "failed"
            if exc.code == 401:
                summary["errors"].append("官方用量接口返回 401，当前 access_token 可能已失效")
            else:
                summary["errors"].append(f"官方用量接口返回 HTTP {exc.code}")
            return summary
        except urllib.error.URLError as exc:
            summary["status"] = "failed"
            summary["errors"].append(f"请求官方用量接口失败: {exc.reason}")
            return summary
        except (ValueError, json.JSONDecodeError) as exc:
            summary["status"] = "failed"
            summary["errors"].append(f"解析官方用量数据失败: {exc}")
            return summary

        summary["status"] = "success"
        summary["email"] = summary["email"] or payload.get("email")
        summary["plan_type"] = payload.get("plan_type")
        summary["rate_limits"] = self._normalize_rate_limit(payload.get("rate_limit"))
        summary["additional_rate_limits"] = self._normalize_additional_limits(payload.get("additional_rate_limits"))
        summary["raw_usage"] = payload

        if summary["email"]:
            self.save_usage_data(
                summary["email"],
                {
                    "check_time": summary["check_time"],
                    "status": summary["status"],
                    "plan_type": summary["plan_type"],
                    "token_usage": summary["token_usage"],
                    "rate_limits": summary["rate_limits"],
                    "additional_rate_limits": summary["additional_rate_limits"],
                    "raw_usage": summary["raw_usage"],
                    "errors": summary["errors"],
                },
            )

        return summary

    def format_usage_summary(self, summary: Dict[str, Any]) -> str:
        lines = [
            "Codex 官方用量查询",
            f"查询时间: {summary['check_time']}",
            f"状态: {summary['status']}",
            "-" * 50,
        ]

        if summary["status"] == "failed":
            lines.extend(["❌ 查询失败:", *[f"  - {error}" for error in summary.get("errors", [])]])
            return "\n".join(lines)

        if summary.get("email"):
            lines.append(f"账号: {summary['email']}")

        if summary.get("plan_type"):
            lines.append(f"计划: {summary['plan_type']}")

        if summary.get("rate_limits"):
            lines.append("\n⏰ 全局额度:")
            for key, title in (("primary", "5小时"), ("secondary", "1周")):
                limit = summary["rate_limits"].get(key)
                if not isinstance(limit, dict):
                    continue

                remaining_percent = self._remaining_percent(limit)
                reset_at = limit.get("resets_at")
                reset_str = "-"
                if reset_at is not None:
                    reset_time = datetime.fromtimestamp(reset_at)
                    reset_str = reset_time.strftime("%m/%d %H:%M") if key == "secondary" else reset_time.strftime("%H:%M")

                lines.append(
                    f"  {title}: {(remaining_percent if remaining_percent is not None else 0):.1f}% 剩余，重置时间 {reset_str}"
                )

        additional_limits = summary.get("additional_rate_limits") or []
        if additional_limits:
            lines.append("\n🧩 模型附加额度:")
            for item in additional_limits:
                name = item.get("limit_name") or "未知额度"
                primary = item.get("primary") or {}
                secondary = item.get("secondary") or {}
                primary_remaining = self._remaining_percent(primary)
                secondary_remaining = self._remaining_percent(secondary)
                lines.append(
                    f"  {name}: 5小时 {(primary_remaining if primary_remaining is not None else 0):.1f}% / 1周 {(secondary_remaining if secondary_remaining is not None else 0):.1f}%"
                )

        return "\n".join(lines)


class OpenAIUsageChecker(CodexUsageChecker):
    """Compatibility wrapper used by older modules in this repo."""

    def __init__(self, access_token: str = None, usage_cache_dir=None):
        super().__init__(usage_cache_dir)
        self.access_token = access_token

    def get_account_summary(self, email: str = None, auth_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        summary = self.get_usage_summary(email=email, auth_data=auth_data)
        return {
            "email": summary.get("email") or email or "Codex CLI",
            "check_time": summary["check_time"],
            "status": summary["status"],
            "usage_data": summary.get("token_usage", {}),
            "rate_limits": summary.get("rate_limits", {}),
            "additional_rate_limits": summary.get("additional_rate_limits", []),
            "plan_type": summary.get("plan_type"),
            "errors": summary.get("errors", []),
        }


if __name__ == "__main__":
    checker = CodexUsageChecker()
    summary = checker.get_usage_summary()
    print(checker.format_usage_summary(summary))
