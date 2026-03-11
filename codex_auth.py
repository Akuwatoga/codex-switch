#!/usr/bin/env python3
"""
Codex auth helpers.

The goal is to preserve the full auth.json shape used by the installed Codex
version while still allowing this project to attach its own metadata.
"""

from __future__ import annotations

import base64
import copy
import json
from datetime import datetime
from typing import Any, Dict, Optional


MANAGER_KEY = "_manager"
MANAGER_SCHEMA_VERSION = 2
MANAGER_METADATA_FIELDS = {
    "saved_at",
    "account_name",
    "email",
    "account_id",
    "plan",
    MANAGER_KEY,
}

TOKEN_KEYS = ("refresh_token", "access_token", "id_token")


def _has_auth_tokens(auth_data: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(auth_data, dict):
        return False
    tokens = auth_data.get("tokens")
    if not isinstance(tokens, dict):
        return False
    return any(tokens.get(key) for key in TOKEN_KEYS)


def detect_auth_mode(auth_data: Optional[Dict[str, Any]]) -> Optional[str]:
    """Infer auth_mode when missing to distinguish api_key vs account tokens."""
    if not isinstance(auth_data, dict):
        return None

    auth_mode = auth_data.get("auth_mode")
    if auth_mode:
        return str(auth_mode)

    api_key = extract_api_key_from_auth(auth_data)
    has_tokens = _has_auth_tokens(auth_data)

    if api_key and not has_tokens:
        return "api_key"
    if has_tokens:
        return "account"
    if api_key:
        return "api_key"
    return None


def parse_jwt_payload(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Best-effort JWT payload parser for both base64 and base64url tokens."""
    if not token or not isinstance(token, str):
        return None

    parts = token.split(".")
    if len(parts) < 2:
        return None

    payload = parts[1]
    payload += "=" * ((4 - len(payload) % 4) % 4)

    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            decoded = decoder(payload.encode("utf-8"))
            data = json.loads(decoded.decode("utf-8"))
            if isinstance(data, dict):
                return data
        except (ValueError, json.JSONDecodeError, TypeError):
            continue

    return None


def strip_manager_fields(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return the Codex auth payload without account-manager metadata."""
    if not isinstance(config, dict):
        return {}

    return {
        key: copy.deepcopy(value)
        for key, value in config.items()
        if key not in MANAGER_METADATA_FIELDS
    }


def extract_stored_auth(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Read the exact auth snapshot from a stored account record."""
    if not isinstance(config, dict):
        return {}

    manager = config.get(MANAGER_KEY)
    if isinstance(manager, dict):
        auth_snapshot = manager.get("auth_snapshot")
        if isinstance(auth_snapshot, dict):
            return strip_manager_fields(auth_snapshot)

    return strip_manager_fields(config)


def validate_auth_config(config: Optional[Dict[str, Any]]) -> None:
    """Reject clearly invalid auth snapshots before writing system auth.json."""
    if not isinstance(config, dict):
        raise ValueError("账号配置格式无效")

    auth_mode = config.get("auth_mode")
    tokens = config.get("tokens")
    api_key = config.get("OPENAI_API_KEY")

    if auth_mode == "api_key":
        if not api_key:
            raise ValueError("API Key 账号缺少 OPENAI_API_KEY")
        return

    if isinstance(tokens, dict) and any(tokens.get(key) for key in ("refresh_token", "access_token", "id_token")):
        return

    if api_key:
        return

    raise ValueError("账号配置缺少可用的认证字段")


def extract_email_from_auth(auth_data: Optional[Dict[str, Any]]) -> Optional[str]:
    """Extract account email from auth data or stored account metadata."""
    if not isinstance(auth_data, dict):
        return None

    manager = auth_data.get(MANAGER_KEY)
    if isinstance(manager, dict):
        email = manager.get("email")
        if email:
            return email

    email = auth_data.get("email")
    if email:
        return email

    tokens = auth_data.get("tokens", {})
    id_payload = parse_jwt_payload(tokens.get("id_token"))
    if id_payload and id_payload.get("email"):
        return id_payload["email"]

    access_payload = parse_jwt_payload(tokens.get("access_token"))
    if access_payload:
        if access_payload.get("email"):
            return access_payload["email"]

        profile = access_payload.get("https://api.openai.com/profile")
        if isinstance(profile, dict) and profile.get("email"):
            return profile["email"]

    return None


def extract_api_key_from_auth(auth_data: Optional[Dict[str, Any]]) -> Optional[str]:
    """Extract OPENAI_API_KEY from auth data."""
    if not isinstance(auth_data, dict):
        return None

    api_key = auth_data.get("OPENAI_API_KEY")
    if isinstance(api_key, str) and api_key:
        return api_key

    return None


def extract_account_id_from_auth(auth_data: Optional[Dict[str, Any]]) -> Optional[str]:
    """Extract the most stable account identifier available."""
    if not isinstance(auth_data, dict):
        return None

    manager = auth_data.get(MANAGER_KEY)
    if isinstance(manager, dict):
        account_id = manager.get("account_id")
        if account_id:
            return str(account_id)

    account_id = auth_data.get("account_id")
    if account_id:
        return str(account_id)

    tokens = auth_data.get("tokens", {})
    for key in ("account_id", "chatgpt_account_id", "user_id"):
        value = tokens.get(key)
        if value:
            return str(value)

    for token_name in ("access_token", "id_token"):
        payload = parse_jwt_payload(tokens.get(token_name))
        if not payload:
            continue

        auth_claims = payload.get("https://api.openai.com/auth")
        if isinstance(auth_claims, dict):
            for key in ("chatgpt_account_id", "account_id", "user_id", "chatgpt_user_id"):
                value = auth_claims.get(key)
                if value:
                    return str(value)

        for key in ("sub", "user_id"):
            value = payload.get(key)
            if value:
                return str(value)

    return None


def extract_plan_from_auth(auth_data: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(auth_data, dict):
        return None

    manager = auth_data.get(MANAGER_KEY)
    if isinstance(manager, dict):
        plan = manager.get("plan")
        if plan:
            return str(plan)

    plan = auth_data.get("plan")
    if plan:
        return str(plan)

    tokens = auth_data.get("tokens", {})
    payload = parse_jwt_payload(tokens.get("access_token"))
    if not payload:
        return None

    auth_claims = payload.get("https://api.openai.com/auth")
    if isinstance(auth_claims, dict):
        value = auth_claims.get("chatgpt_plan_type")
        if value:
            return str(value)

    return None


def build_account_record(auth_data: Dict[str, Any], account_name: str, saved_at: Optional[str] = None) -> Dict[str, Any]:
    """Build a stored account record with metadata and a lossless auth snapshot."""
    auth_snapshot = extract_stored_auth(auth_data)
    validate_auth_config(auth_snapshot)
    auth_mode = detect_auth_mode(auth_snapshot)

    metadata = {
        "schema_version": MANAGER_SCHEMA_VERSION,
        "account_name": account_name,
        "saved_at": saved_at or datetime.now().isoformat(),
        "email": extract_email_from_auth(auth_snapshot),
        "account_id": extract_account_id_from_auth(auth_snapshot),
        "plan": extract_plan_from_auth(auth_snapshot),
        "auth_mode": auth_mode,
        "auth_snapshot": copy.deepcopy(auth_snapshot),
    }

    record = copy.deepcopy(auth_snapshot)
    record.update(
        {
            "account_name": metadata["account_name"],
            "saved_at": metadata["saved_at"],
            "email": metadata["email"],
            "account_id": metadata["account_id"],
            "plan": metadata["plan"],
            "auth_mode": metadata["auth_mode"],
            MANAGER_KEY: metadata,
        }
    )
    return record


def prepare_auth_for_switch(
    auth_record: Optional[Dict[str, Any]],
    force_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a clean auth config for ~/.codex/auth.json based on intended mode."""
    auth_snapshot = extract_stored_auth(auth_record)
    auth_mode = None
    if isinstance(auth_record, dict):
        auth_mode = auth_record.get("auth_mode")

    if force_mode:
        force_mode = str(force_mode)
        if force_mode not in ("api_key", "account"):
            raise ValueError("未知的切换模式")
        auth_mode = force_mode

    auth_mode = auth_mode or detect_auth_mode(auth_snapshot)

    if auth_mode == "api_key":
        if not extract_api_key_from_auth(auth_snapshot):
            raise ValueError("API 模式需要 OPENAI_API_KEY")
        auth_snapshot["auth_mode"] = "api_key"
    else:
        if not _has_auth_tokens(auth_snapshot):
            raise ValueError("账号模式需要可用的 token")
        # Prefer account tokens; strip API key so Codex doesn't force api_key mode.
        auth_snapshot.pop("OPENAI_API_KEY", None)
        if auth_snapshot.get("auth_mode") == "api_key" or auth_mode == "account":
            auth_snapshot.pop("auth_mode", None)

    validate_auth_config(auth_snapshot)
    return auth_snapshot


def same_account(left: Optional[Dict[str, Any]], right: Optional[Dict[str, Any]]) -> bool:
    """Compare account snapshots using the strongest identifiers available."""
    left_auth = extract_stored_auth(left)
    right_auth = extract_stored_auth(right)

    if not left_auth or not right_auth:
        return False

    left_id = extract_account_id_from_auth(left_auth)
    right_id = extract_account_id_from_auth(right_auth)
    if left_id and right_id:
        return left_id == right_id

    left_tokens = left_auth.get("tokens", {})
    right_tokens = right_auth.get("tokens", {})
    for token_key in ("refresh_token", "id_token", "access_token"):
        left_token = left_tokens.get(token_key)
        right_token = right_tokens.get(token_key)
        if left_token and right_token:
            return left_token == right_token

    left_api_key = extract_api_key_from_auth(left_auth)
    right_api_key = extract_api_key_from_auth(right_auth)
    if left_api_key and right_api_key:
        return left_api_key == right_api_key

    left_email = extract_email_from_auth(left_auth)
    right_email = extract_email_from_auth(right_auth)
    if left_email and right_email:
        return left_email == right_email

    return False
