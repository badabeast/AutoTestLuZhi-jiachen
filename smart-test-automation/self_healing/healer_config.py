#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
healer 配置模块 — 供 CLI 和非 pytest 场景使用

功能:
  - 封装 healer 配置加载逻辑
  - 读取 .env 中的统一 AI 配置（AI_API_KEY / AI_BASE_URL / AI_MODEL）
  - 提供 get_healer_config() 函数

AI Provider: OpenAI 兼容协议平台（如 GLM-5.1）
v5 变更: 统一读取 AI_API_KEY / AI_BASE_URL / AI_MODEL，废弃旧的分散变量；
         auto_patch_source 默认关闭（由自建 SourcePatcher 控制）。
"""

import os
from pathlib import Path
from typing import Optional

from playwright_healer.config import HealerConfig, HealingStrategy
from playwright_healer.ai_providers import AIProviderConfig, AIProvider


# ── 统一配置变量别名（向后兼容） ──────────────────────────────
# 新代码应直接使用 AI_API_KEY / AI_BASE_URL / AI_MODEL
# 以下映射保证旧变量名仍可读取（优先级：新 > 旧）
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
    auto_patch_source: bool = False,
    patch_source_backup: bool = True,
) -> HealerConfig:
    """获取 healer 配置

    使用 OpenAI 兼容协议平台作为 AI provider。
    v5 变更：统一读取 AI_API_KEY / AI_BASE_URL / AI_MODEL，
            并向后兼容旧变量名（ANTHROPIC_AUTH_TOKEN 等）。

    Args:
        strategy: 自愈策略（SMART/HEURISTIC_ONLY/DOM_ONLY/FULL）
        prefer_aria: 优先修复为 ARIA 选择器
        auto_patch_source: 自动修补源码（v4+ 默认关闭，由 SourcePatcher 控制）
        patch_source_backup: 修补前备份原文件

    Returns:
        HealerConfig: healer 配置对象
    """
    # 确保 .env 已加载
    load_env()

    ai_key = _resolve_ai_key()
    api_url = _resolve_ai_base_url()
    model = _resolve_ai_model()

    if not ai_key:
        print("⚠️ AI_API_KEY 未设置，healer AI 修复（L4）将不可用")
        print("   请在 .env 中设置 AI_API_KEY（兼容旧名 ANTHROPIC_AUTH_TOKEN）")

    # 构建 provider 配置（OpenAI 兼容 Messages API 协议）
    # playwright-healer 内置的 OPENAI provider 使用 Authorization: Bearer 头
    providers = [
        AIProviderConfig(
            provider=AIProvider.OPENAI,
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

    统一使用 AI_API_KEY / AI_BASE_URL / AI_MODEL，
    同时向后兼容传递旧变量名。

    Returns:
        dict: 环境变量字典，可用于 subprocess.run(env=...)
    """
    load_env()

    ai_key = _resolve_ai_key()
    base_url = _resolve_ai_base_url()
    model = _resolve_ai_model()

    env = {
        # 新统一变量
        "AI_API_KEY": ai_key,
        "AI_BASE_URL": base_url,
        "AI_MODEL": model,
        # 旧变量向后兼容（子进程可能依赖）
        "ANTHROPIC_AUTH_TOKEN": ai_key,
        "OPENAI_COMPAT_BASE_URL": base_url,
        "OPENAI_COMPAT_MODEL": model,
        "ZCY_HEALER_API_URL": base_url,
        "ZCY_HEALER_MODEL": model,
        # healer 行为参数
        "PH_STRATEGY": os.environ.get("PH_STRATEGY", "SMART"),
        "PH_PREFER_ARIA": os.environ.get("PH_PREFER_ARIA", "true"),
        "PH_AUTO_PATCH_SOURCE": os.environ.get("PH_AUTO_PATCH_SOURCE", "false"),
        "PH_PATCH_SOURCE_BACKUP": os.environ.get("PH_PATCH_SOURCE_BACKUP", "true"),
    }
    return env
