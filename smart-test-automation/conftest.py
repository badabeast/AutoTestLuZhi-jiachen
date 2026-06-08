"""
smart-test-automation conftest.py

playwright-healer 自动注册 healing_page fixture（通过 pytest entry point）
无需手动 import，只要安装了 playwright-healer 即自动生效。

这里覆盖 healing_config fixture，配置 healer 使用 zcy AI 平台（Anthropic 协议）
作为 AI 自愈的 provider。healer 的 AnthropicProvider 已 patch 支持自定义 api_url。
"""

import os
from config.env_loader import load_env

# 加载 .env（统一工具函数，支持引号和注释）
load_env()

import pytest


@pytest.fixture(scope="session")
def healing_config():
    """覆盖 healer 默认配置，使用 zcy AI 平台作为 AI provider

    zcy AI 平台提供 Anthropic 协议的模型服务（GLM-5.1 等）：
      https://ai-platform.cai-inc.com/api/biz-ai/ai-model/api/11/apps/anthropic

    healer 的 AnthropicProvider 原本硬编码 api.anthropic.com，
    已 patch 改为使用 self._cfg.api_url（可配置），
    所以可以直接指向 zcy 平台。
    """
    from playwright_healer.config import HealerConfig, HealingStrategy
    from playwright_healer.ai_providers import AIProviderConfig, AIProvider

    zcy_key = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    zcy_api_url = os.environ.get("PH_AI_API_URL",
        "https://ai-platform.cai-inc.com/api/biz-ai/ai-model/api/11/apps/anthropic/v1/messages")

    return HealerConfig(
        providers=[
            AIProviderConfig(
                provider=AIProvider.ANTHROPIC,
                api_key=zcy_key,
                model="glm-5.1",
                api_url=zcy_api_url,
            )
        ],
        strategy=HealingStrategy.SMART,
        prefer_aria=True,
        auto_patch_source=True,
        patch_source_backup=True,
    )