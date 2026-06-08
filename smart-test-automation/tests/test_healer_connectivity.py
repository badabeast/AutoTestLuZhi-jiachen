#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
healer 连通性测试

验证:
  1. healer 配置正确加载（pytest 测试）
  2. HealingPage fixture 正常注册 + zcy AI 平台 API 响应（独立脚本验证）

注意: HealingPage 是纯 async API，pytest-playwright 和 pytest-asyncio 的 event loop 有冲突，
所以 HealingPage 的浏览器连通性验证放在独立的 verify_healer.py 脚本中。
"""

import pytest


def test_healer_config_loaded(healing_config):
    """验证 healer 配置正确加载"""
    # 配置中有至少一个 provider
    assert len(healing_config.providers) > 0, "至少有一个 AI provider"

    # provider 是 ANTHROPIC，指向 zcy AI 平台
    from playwright_healer.ai_providers import AIProvider

    provider = healing_config.providers[0]
    assert provider.provider == AIProvider.ANTHROPIC, "使用 ANTHROPIC provider"

    # api_url 指向 zcy 平台
    assert provider.api_url and "ai-platform" in provider.api_url, "API URL 指向 zcy AI 平台"

    # model 是 glm-5.1
    assert provider.model == "glm-5.1", "使用 glm-5.1 模型"

    # api_key 不为空
    assert provider.api_key, "API key 不为空"


def test_healer_config_module():
    """验证 self_healing/healer_config.py 模块可独立使用"""
    from self_healing.healer_config import get_healer_config, get_healer_env_vars

    config = get_healer_config()
    assert config is not None, "healer 配置对象不为空"
    assert len(config.providers) > 0, "配置中有 provider"

    env_vars = get_healer_env_vars()
    assert env_vars.get("ANTHROPIC_AUTH_TOKEN"), "环境变量中有 ANTHROPIC_AUTH_TOKEN"
    assert env_vars.get("ZCY_HEALER_API_URL"), "环境变量中有 ZCY_HEALER_API_URL"


def test_healer_env_vars_configured():
    """验证 healer 环境变量已正确配置"""
    import os

    # 加载 .env
    from self_healing.healer_config import load_env
    load_env()

    # 检查关键环境变量
    assert os.environ.get("ANTHROPIC_AUTH_TOKEN"), "ANTHROPIC_AUTH_TOKEN 已配置"

    # 检查 URL 指向 zcy 平台
    api_url = os.environ.get("ZCY_HEALER_API_URL", "")
    assert "ai-platform" in api_url, "API URL 指向 zcy AI 平台"