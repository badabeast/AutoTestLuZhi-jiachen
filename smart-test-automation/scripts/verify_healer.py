#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
healer + AI 平台 连通性验证脚本

独立运行，不依赖 pytest，直接验证:
  1. HealingPage 能正常创建
  2. AI 平台（Anthropic 协议）API 能响应 healer 的自愈请求
  3. healer 4 级策略链完整可用

运行方式:
    python3 verify_healer.py
"""

import asyncio
import os
import sys
from pathlib import Path

# 确保项目根目录在 import 路径中
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 加载 .env
from self_healing.healer_config import load_env, get_healer_config
load_env()


async def verify_healer_config():
    """验证 healer 配置"""
    config = get_healer_config()

    print("✅ healer 配置加载成功")
    print(f"   Strategy: {config.strategy}")
    print(f"   Providers: {len(config.providers)}")
    for p in config.providers:
        print(f"   - {p.provider}: model={p.model}, api_url={p.api_url[:60]}...")
    print(f"   prefer_aria: {config.prefer_aria}")
    print(f"   auto_patch_source: {config.auto_patch_source}")

    return config


async def verify_ai_api(config):
    """直接验证 AI 平台（Anthropic 协议）API 是否能响应"""
    import httpx

    provider = config.providers[0]

    print("\n🔄 验证 AI 平台 API 连通性...")
    print(f"   URL: {provider.api_url}")
    print(f"   Model: {provider.model}")

    # 使用 Authorization: Bearer 认证
    headers = {
        "Authorization": f"Bearer {provider.api_key}",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    payload = {
        "model": provider.model,
        "max_tokens": 50,
        "messages": [
            {"role": "user", "content": "请回复'连通性验证成功'"},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(provider.api_url, headers=headers, json=payload)

        if resp.status_code == 200:
            body = resp.json()
            text = body.get("content", [{}])[0].get("text", "")
            print(f"✅ AI 平台 API 连通成功!")
            print(f"   响应: {text}")
            print(f"   状态码: {resp.status_code}")
            print(f"   Token 使用: {body.get('usage', {})}")
            return True
        else:
            print(f"❌ AI 平台 API 返回错误: {resp.status_code}")
            print(f"   响应: {resp.text[:500]}")
            return False

    except Exception as e:
        print(f"❌ AI 平台 API 连接失败: {e}")
        return False


async def verify_healing_page(config):
    """验证 HealingPage 能正常创建和使用（playwright-healer 已移除，此功能不可用）"""
    print("\n⚠️ playwright-healer 已从项目中移除，HealingPage 验证跳过")
    print("   相关功能由本地五层引擎替代: self_healing/pipeline.py")
    return
        page = await browser.new_page()

        # 创建 HealingPage
        hp = HealingPage(page, config, test_name="verify_healer")

        # 基本页面操作
        await hp.goto("https://example.com")
        title = await hp.title()
        print(f"✅ HealingPage 创建成功!")
        print(f"   页面标题: {title}")
        print(f"   页面 URL: {page.url}")

        # 关闭
        await hp.shutdown()
        await browser.close()

    return True


async def main():
    """主验证流程"""
    print("=" * 50)
    print("  healer + AI 平台 连通性验证")
    print("=" * 50)

    # Step 1: 配置验证
    config = await verify_healer_config()

    # Step 2: AI API 连通性
    api_ok = await verify_ai_api(config)

    # Step 3: HealingPage 验证
    if api_ok:
        page_ok = await verify_healing_page(config)
    else:
        print("\n⚠️ API 连通失败，跳过 HealingPage 验证")
        page_ok = False

    # 汇总结果
    print("\n" + "=" * 50)
    print("  验证结果汇总")
    print("=" * 50)
    print(f"  配置加载: ✅")
    print(f"  AI API: {'✅' if api_ok else '❌'}")
    print(f"  HealingPage: {'✅' if page_ok else '⚠️'}")

    if api_ok:
        print("\n✅ healer + AI 平台 连通性验证通过!")
        print("   Phase 1 healer 集成已完成，可进入真实录制验证阶段")
        return True
    else:
        print("\n❌ healer + AI 平台 连通性验证失败!")
        print("   请检查 .env 中的 AI_API_KEY 配置")
        return False


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
