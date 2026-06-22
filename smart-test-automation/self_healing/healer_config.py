#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""healer配置模块。统一读AI_API_KEY/AI_BASE_URL/AI_MODEL，向后兼容旧变量名。"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class HealerConfig:
    """自愈引擎配置

    Attributes:
        api_key: AI API 密钥
        base_url: AI API 地址
        model: 模型名称
        strategy: 自愈策略
        prefer_aria: 优先使用 ARIA 选择器
        auto_patch_source: 自动回写源码
        patch_source_backup: 回写前备份
    """
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    strategy: str = "SMART"
    prefer_aria: bool = True
    auto_patch_source: bool = False
    patch_source_backup: bool = True


def _resolve_ai_key() -> str:
    return os.environ.get("AI_API_KEY", "") or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")


def _resolve_ai_base_url() -> str:
    return os.environ.get(
        "AI_BASE_URL",
        os.environ.get(
            "OPENAI_COMPAT_BASE_URL",
            os.environ.get(
                "ZCY_HEALER_API_URL",
                "https://ai-platform.cai-inc.com/api/biz-ai/ai-model/api/11/compatible-mode/v1",
            ),
        ),
    )


def _resolve_ai_model() -> str:
    return os.environ.get(
        "AI_MODEL",
        os.environ.get(
            "OPENAI_COMPAT_MODEL",
            os.environ.get("ZCY_HEALER_MODEL", "glm-5.1"),
        ),
    )


def load_env(env_path: Optional[str] = None) -> None:
    if env_path is None:
        env_path = str(Path(__file__).parent.parent / ".env")

    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


def get_healer_config(
    strategy: str = "SMART",
    prefer_aria: bool = True,
    auto_patch_source: bool = False,
    patch_source_backup: bool = True,
) -> HealerConfig:
    """获取healer配置"""
    load_env()

    ai_key = _resolve_ai_key()
    api_url = _resolve_ai_base_url()
    model = _resolve_ai_model()

    if not ai_key:
        print("⚠️ AI_API_KEY 未设置，healer AI 修复将不可用")
        print("   请在 .env 中设置 AI_API_KEY（兼容旧名 ANTHROPIC_AUTH_TOKEN）")

    return HealerConfig(
        api_key=ai_key,
        base_url=api_url,
        model=model,
        strategy=strategy,
        prefer_aria=prefer_aria,
        auto_patch_source=auto_patch_source,
        patch_source_backup=patch_source_backup,
    )


def get_healer_env_vars() -> dict:
    """返回healer需要的环境变量dict，新变量+旧变量都带上，给子进程用。"""
    load_env()

    ai_key = _resolve_ai_key()
    base_url = _resolve_ai_base_url()
    model = _resolve_ai_model()

    env = {
        "AI_API_KEY": ai_key,
        "AI_BASE_URL": base_url,
        "AI_MODEL": model,
        "ANTHROPIC_AUTH_TOKEN": ai_key,
        "OPENAI_COMPAT_BASE_URL": base_url,
        "OPENAI_COMPAT_MODEL": model,
        "ZCY_HEALER_API_URL": base_url,
        "ZCY_HEALER_MODEL": model,
    }
    return env
