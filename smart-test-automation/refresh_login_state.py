#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
刷新登录态 — 用现有 storage_state 打开采购需求页面，刷新 session cookie

原理:
  1. 用 storage_state 启动浏览器
  2. 访问采购需求页面
  3. 如果 session 有效 → 页面正常加载 → 保存刷新后的 storage_state
  4. 如果 session 过期 → 被重定向到登录页 → 需要手动登录

用法:
    python3 refresh_login_state.py
    # 如果需要手动登录:
    python3 refresh_login_state.py --manual
"""

import sys
import os
import json
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright

STORAGE_STATE_PATH = Path("login_state/storage_state.json")
TARGET_URL = "https://www.test.zcygov.cn/demand_front/#/overview?_app_=zcy.demand&app=demand&pageSize=20"


def refresh_login_state(manual: bool = False):
    """刷新登录态"""
    print("=" * 60)
    print("🔄 登录态刷新工具")
    print("=" * 60)
    print(f"\n📌 目标页面: {TARGET_URL}")
    print(f"📁 登录态文件: {STORAGE_STATE_PATH}")

    if not STORAGE_STATE_PATH.exists():
        print("\n❌ 没有已有登录态，需要先手动登录")
        print("   运行: python3 save_login_state.py")
        return False

    with open(STORAGE_STATE_PATH, "r", encoding="utf-8") as f:
        old_state = json.load(f)
    old_cookies = len(old_state.get("cookies", []))
    print(f"\n📊 当前登录态: {old_cookies} 个 Cookie")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--ignore-certificate-errors",
            ],
        )
        context = browser.new_context(
            storage_state=str(STORAGE_STATE_PATH),
            viewport={"width": 1366, "height": 768},
            ignore_https_errors=True,
            permissions=["geolocation", "local-network-access"],
        )
        page = context.new_page()

        # 访问目标页面
        print(f"\n🚀 正在访问 {TARGET_URL}...")
        page.goto(TARGET_URL, timeout=30000, wait_until="domcontentloaded")

        # 关键：domcontentloaded 时 cookie 存在，页面看起来正常
        # 但 JS 执行后可能发现服务端 session 过期而重定向到登录页
        # 所以必须等 networkidle 再检查 URL
        initial_url = page.url
        print(f"\n📍 domcontentloaded 时 URL: {initial_url}")

        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception as e:
            print(f"⚠️ networkidle 等待超时: {e}")
            # 即使超时也继续检查 URL

        current_url = page.url
        print(f"📍 networkidle 后 URL: {current_url}")

        # 判断是否被重定向到登录页（关键：用 networkidle 后的 URL 判断）
        is_redirected_to_login = "login" in current_url.lower()

        if is_redirected_to_login:
            print("\n⚠️ 登录态已过期，被重定向到登录页！")
            print("   需要手动登录后保存登录态")

            if manual:
                print("\n👉 请在浏览器中完成登录")
                print("👉 登录成功后回到终端按 Enter 键保存")

                input("⏳ 按 Enter 保存登录态...")
            else:
                print("\n👉 运行: python3 refresh_login_state.py --manual 进行手动登录")
                browser.close()
                return False
        else:
            print("\n✅ 登录态有效！页面正常加载")

        # 保存刷新后的登录态
        try:
            new_state = context.storage_state()

            # 关键修复：将 expires=-1 的 session cookie 改为 7 天后过期
            seven_days_later = time.time() + 7 * 24 * 3600
            fixed_count = 0
            for cookie in new_state.get("cookies", []):
                if cookie.get("expires", 0) == -1:
                    cookie["expires"] = seven_days_later
                    fixed_count += 1

            if fixed_count:
                print(f"   🔄 修复了 {fixed_count} 个 session cookie (expires=-1 → 7d)")

            STORAGE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(STORAGE_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(new_state, f, ensure_ascii=False, indent=2)

            new_cookies = len(new_state.get("cookies", []))
            print(f"\n✅ 登录态已保存!")
            print(f"   Cookie 数量: {old_cookies} → {new_cookies}")
            print(f"   文件: {STORAGE_STATE_PATH}")
            print(f"   大小: {STORAGE_STATE_PATH.stat().st_size / 1024:.1f} KB")
        except Exception as e:
            print(f"\n❌ 保存登录态失败: {e}")

        browser.close()

    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="刷新登录态")
    parser.add_argument("--manual", action="store_true", help="如果 session 过期，允许手动登录")

    args = parser.parse_args()
    success = refresh_login_state(manual=args.manual)
    sys.exit(0 if success else 1)