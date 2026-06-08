#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
healer 配置模块 — 供 CLI 和非 pytest 场景使用

功能:
  - 封装 healer 配置加载逻辑
  - 读取 .env 中的 zcy AI 平台 API key
  - 提供 get_healer_config() 函数

pytest 场景不需要此模块，直接在 conftest.py 中覆盖 healing_config fixture 即可。
此模块供 CLI heal 命令、手动脚本等非 pytest 场景调用 healer 时使用。

AI Provider: zcy AI 平台（Anthropic 协议，GLM-5.1）
healer 的 AnthropicProvider 已 patch 支持自定义 api_url。
"""

import os
from pathlib import Path
from typing import Optional

from playwright_healer.config import HealerConfig, HealingStrategy
from playwright_healer.ai_providers import AIProviderConfig, AIProvider

# zcy AI 平台配置
ZCY_API_URL = "https://ai-platform.cai-inc.com/api/biz-ai/ai-model/api/11/apps/anthropic/v1/messages"
ZCY_MODEL = "glm-5.1"


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

    默认使用 zcy AI 平台（Anthropic 协议，GLM-5.1）作为 AI provider。
    healer 的 AnthropicProvider 已 patch 支持自定义 api_url，
    可以指向 zcy 平台的 Anthropic 协议代理。

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

    zcy_key = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")

    # 构建 provider 配置
    # zcy AI 平台走 Anthropic Messages API 协议
    providers = [
        AIProviderConfig(
            provider=AIProvider.ANTHROPIC,
            api_key=zcy_key,
            model=os.environ.get("ZCY_HEALER_MODEL", ZCY_MODEL),
            api_url=os.environ.get("ZCY_HEALER_API_URL", ZCY_API_URL),
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
        "ZCY_HEALER_MODEL": os.environ.get("ZCY_HEALER_MODEL", ZCY_MODEL),
        "ZCY_HEALER_API_URL": os.environ.get("ZCY_HEALER_API_URL", ZCY_API_URL),
        "PH_STRATEGY": os.environ.get("PH_STRATEGY", "SMART"),
        "PH_PREFER_ARIA": os.environ.get("PH_PREFER_ARIA", "true"),
        "PH_AUTO_PATCH_SOURCE": os.environ.get("PH_AUTO_PATCH_SOURCE", "true"),
        "PH_PATCH_SOURCE_BACKUP": os.environ.get("PH_PATCH_SOURCE_BACKUP", "true"),
    }
    return env