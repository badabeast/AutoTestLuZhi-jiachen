#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
healer 配置模块 — 供 CLI 和非 pytest 场景使用

功能:
  - 封装 healer 配置加载逻辑
  - 读取 .env 中的 AI 平台 API key
  - 提供 get_healer_config() 函数

AI Provider: Anthropic 协议兼容平台（如 GLM-5.1）
"""

import os
from pathlib import Path
from typing import Optional

from playwright_healer.config import HealerConfig, HealingStrategy
from playwright_healer.ai_providers import AIProviderConfig, AIProvider

# AI 平台配置（默认值为通用示例地址，实际值从环境变量读取）
DEFAULT_API_URL = os.environ.get("ZCY_HEALER_API_URL", "https://your-ai-platform.example.com/api/v1/messages")
DEFAULT_MODEL = os.environ.get("ZCY_HEALER_MODEL", "glm-5.1")


def load_env(env_path: Optional[str] = None) -> None:
    """手动加载 .env 文件到环境变量

    Args:
        env_path: .env 文件路径，默认为项目根目录下的 .env
    """
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
    auto_patch_source: bool = True,
    patch_source_backup: bool = True,
) -> HealerConfig:
    """获取 healer 配置

    默认使用 Anthropic 协议兼容平台作为 AI provider。

    Args:
        strategy: 自愈策略（SMART/HEURISTIC_ONLY/DOM_ONLY/FULL）
        prefer_aria: 优先修复为 ARIA 选择器
        auto_patch_source: 自动修补源码
        patch_source_backup: 修补前备份原文件

    Returns:
        HealerConfig: healer 配置对象
    """
    # 确保 .env 已加载
    load_env()

    ai_key = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    api_url = DEFAULT_API_URL
    model = DEFAULT_MODEL

    if not ai_key:
        print("⚠️ ANTHROPIC_AUTH_TOKEN 未设置，healer AI 修复（L4）将不可用")
        print("   请在 .env 中设置 ANTHROPIC_AUTH_TOKEN")

    # 构建 provider 配置（Anthropic Messages API 协议）
    providers = [
        AIProviderConfig(
            provider=AIProvider.ANTHROPIC,
            api_key=ai_key,
            model=model,
            api_url=api_url,
        )
    ]

    strategy_enum = HealingStrategy(strategy)

    return HealerConfig(
        providers=providers,
        strategy=strategy_enum,
        prefer_aria=prefer_aria,
        auto_patch_source=auto_patch_source,
        patch_source_backup=patch_source_backup,
    )


def get_healer_env_vars() -> dict:
    """获取 healer 需要的环境变量配置（供 subprocess 场景使用）

    Returns:
        dict: 环境变量字典，可用于 subprocess.run(env=...)
    """
    load_env()

    env = {
        "ANTHROPIC_AUTH_TOKEN": os.environ.get("ANTHROPIC_AUTH_TOKEN", ""),
        "ZCY_HEALER_API_URL": os.environ.get("ZCY_HEALER_API_URL", DEFAULT_API_URL),
        "ZCY_HEALER_MODEL": os.environ.get("ZCY_HEALER_MODEL", DEFAULT_MODEL),
        "PH_STRATEGY": os.environ.get("PH_STRATEGY", "SMART"),
        "PH_PREFER_ARIA": os.environ.get("PH_PREFER_ARIA", "true"),
        "PH_AUTO_PATCH_SOURCE": os.environ.get("PH_AUTO_PATCH_SOURCE", "true"),
        "PH_PATCH_SOURCE_BACKUP": os.environ.get("PH_PATCH_SOURCE_BACKUP", "true"),
    }
    return env
