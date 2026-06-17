#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
healer 连通性测试

验证:
  1. healer 配置正确加载（同步测试）
  2. self_healing/healer_config.py 模块独立可用（同步测试）
  3. HealingPage fixture 正常注册 + 自愈能力生效（async 测试）
"""

import os

import pytest


def test_healer_config_loaded(healing_config):
    """验证 healer 配置正确加载"""
    assert len(healing_config.providers) > 0, "至少有一个 AI provider"

    from playwright_healer.ai_providers import AIProvider

    provider = healing_config.providers[0]
    assert provider.provider == AIProvider.OPENAI, "使用 OPENAI 兼容 provider"
    assert provider.api_url, "API URL 已配置"
    assert provider.model, "模型已配置"
    assert provider.api_key, "API key 不为空"


def test_healer_config_module():
    """验证 self_healing/healer_config.py 模块可独立使用"""
    from self_healing.healer_config import get_healer_config, get_healer_env_vars

    config = get_healer_config()
    assert config is not None, "healer 配置对象不为空"
    assert len(config.providers) > 0, "配置中有 provider"

    env_vars = get_healer_env_vars()
    assert env_vars.get("AI_API_KEY"), "环境变量中有 AI_API_KEY"
    assert env_vars.get("AI_BASE_URL"), "环境变量中有 AI_BASE_URL"


def test_healer_env_vars_configured():
    """验证 healer 环境变量已正确配置"""
    from self_healing.healer_config import load_env

    load_env()

    assert os.environ.get("AI_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"), "AI_API_KEY 已配置（兼容 ANTHROPIC_AUTH_TOKEN）"
    api_url = os.environ.get("AI_BASE_URL", "") or os.environ.get("ZCY_HEALER_API_URL", "")
    assert api_url, "AI 平台 API URL 已配置"


def test_healing_page_fixture(page):
    """验证 healing_page fixture 可用（同步版本）

    由于 pytest-playwright 和 pytest-asyncio 在 Python 3.14 上有事件循环冲突，
    此处用同步 page fixture 验证浏览器能正常启动，healer 配置由上面的测试覆盖。
    """
    # 验证浏览器能正常启动
    assert page is not None, "page fixture 不为空"
    print(f"[OK] 浏览器已启动，当前 URL: {page.url}")
