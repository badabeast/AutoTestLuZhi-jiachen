#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自愈模块连通性测试

验证:
  1. self_healing/healer_config.py 模块独立可用
  2. 环境变量配置正确
  3. 浏览器 page fixture 正常
"""

import os

import pytest


def test_healer_config_module():
    """验证 self_healing/healer_config.py 模块可独立使用"""
    from self_healing.healer_config import HealerConfig, get_healer_config, get_healer_env_vars

    config = get_healer_config()
    assert config is not None, "healer 配置对象不为空"
    assert isinstance(config, HealerConfig), "返回 HealerConfig 实例"

    env_vars = get_healer_env_vars()
    assert env_vars.get("AI_API_KEY"), "环境变量中有 AI_API_KEY"
    assert env_vars.get("AI_BASE_URL"), "环境变量中有 AI_BASE_URL"


def test_healer_env_vars_configured():
    """验证 healer 环境变量已正确配置"""
    from self_healing.healer_config import load_env

    load_env()

    assert os.environ.get("AI_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"), \
        "AI_API_KEY 已配置（兼容 ANTHROPIC_AUTH_TOKEN）"
    api_url = os.environ.get("AI_BASE_URL", "") or os.environ.get("ZCY_HEALER_API_URL", "")
    assert api_url, "AI 平台 API URL 已配置"


def test_healing_page_fixture(page):
    """验证 healing_page fixture 可用（同步版本）

    由于 pytest-playwright 和 pytest-asyncio 在 Python 3.14 上有事件循环冲突，
    此处用同步 page fixture 验证浏览器能正常启动，healer 配置由上面的测试覆盖。
    """
    assert page is not None, "page fixture 不为空"
    print(f"[OK] 浏览器已启动，当前 URL: {page.url}")
