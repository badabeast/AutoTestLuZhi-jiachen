"""
smart-test-automation conftest.py

playwright-healer 自动注册 healing_page fixture（通过 pytest entry point）
无需手动 import，只要安装了 playwright-healer 即自动生效。

这里覆盖 healing_config fixture，配置 healer 使用 AI 平台（Anthropic 协议）
作为 AI 自愈的 provider。healer 的 AnthropicProvider 已 patch 支持自定义 api_url。
"""

import os
from config.env_loader import load_env

# 加载 .env（统一工具函数，支持引号和注释）
load_env()

import pytest


@pytest.fixture(scope="session")
def healing_config():
    """覆盖 healer 默认配置，使用 AI 平台作为 AI provider

    AI 平台配置从环境变量读取：
      PH_AI_API_URL: AI 平台 API 地址
      ANTHROPIC_AUTH_TOKEN: API 密钥
      PH_AI_MODEL: 模型名称
    """
    from playwright_healer.config import HealerConfig, HealingStrategy
    from playwright_healer.ai_providers import AIProviderConfig, AIProvider

    ai_key = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    ai_api_url = os.environ.get("PH_AI_API_URL", "https://your-ai-platform.example.com/api/v1/messages")
    ai_model = os.environ.get("PH_AI_MODEL", "glm-5.1")

    return HealerConfig(
        providers=[
            AIProviderConfig(
                provider=AIProvider.ANTHROPIC,
                api_key=ai_key,
                model=ai_model,
                api_url=ai_api_url,
            )
        ],
        strategy=HealingStrategy.SMART,
        prefer_aria=True,
        auto_patch_source=True,
        patch_source_backup=True,
    )