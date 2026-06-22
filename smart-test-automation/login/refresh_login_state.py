#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刷新登录态。用现有storage_state打开页面，session有效则保存刷新，过期则先尝试无头自动登录再回退手动。"""

import sys
import os
import json
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

# 加载 .env
from config.env_loader import load_env
load_env()

from playwright.sync_api import sync_playwright

STORAGE_STATE_PATH = Path("login_state/storage_state.json")
TARGET_URL = os.environ.get("WEB_DEMAND_URL", "")
LOGIN_URL = os.environ.get("WEB_DEMAND_LOGIN_PAGE_URL", "")
LOGIN_DOMAINS = os.environ.get("WEB_DEMAND_LOGIN_DOMAINS", "").split(",") if os.environ.get("WEB_DEMAND_LOGIN_DOMAINS") else []
ACCOUNT = os.environ.get("WEB_DEMAND_ACCOUNT", "")
PASSWORD = os.environ.get("WEB_DEMAND_PASSWORD", "")


def is_login_state_valid() -> bool:
    """快速检查storage_state是否存在且关键cookie未过期。"""
    if not STORAGE_STATE_PATH.exists():
        return False

    try:
        with open(STORAGE_STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        return False

    cookies = state.get("cookies", [])
    now = time.time()

    auth_names = {"SESSION", "SSOSESSION"}
    found_valid = False

    for cookie in cookies:
        name = cookie.get("name", "")
        if name in auth_names:
            expires = cookie.get("expires", -1)
            if expires == -1 or (expires > 0 and expires > now):
                found_valid = True
            else:
                return False

    return found_valid


def _auto_login_headless() -> bool:
    if not ACCOUNT or not PASSWORD:
        return False

    print("  尝试无头自动登录...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--ignore-certificate-errors"],
            )
            context = browser.new_context(
                viewport={"width": 1366, "height": 768},
                ignore_https_errors=True,
            )
            page = context.new_page()

            page.goto(LOGIN_URL, timeout=30000, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                time.sleep(3)

            # 填写表单
            filled_user = False
            for sel in ["input[name=username]", "input[name=account]", "input[placeholder*=用户]", "input[type=text]"]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=2000):
                        el.fill(ACCOUNT)
                        filled_user = True
                        break
                except Exception:
                    continue

            filled_pwd = False
            for sel in ["input[type=password]", "input[name=password]"]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=2000):
                        el.fill(PASSWORD)
                        filled_pwd = True
                        break
                except Exception:
                    continue

            if not filled_user or not filled_pwd:
                browser.close()
                return False

            # 点击登录
            for sel in ["button:has-text('登 录')", "button:has-text('登录')", "button[type=submit]"]:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        break
                except Exception:
                    continue

            # 等待重定向
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                time.sleep(5)

            current_url = page.url
            is_still_login = any(domain in current_url for domain in LOGIN_DOMAINS)

            if is_still_login:
                browser.close()
                return False

            new_state = context.storage_state()
            seven_days = time.time() + 7 * 24 * 3600
            for c in new_state.get("cookies", []):
                if c.get("expires", 0) == -1:
                    c["expires"] = seven_days

            STORAGE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(STORAGE_STATE_PATH, "w") as f:
                json.dump(new_state, f, ensure_ascii=False, indent=2)

            browser.close()
            print(f"  无头自动登录成功! ({len(new_state.get('cookies', []))} 个 Cookie)")
            return True

    except Exception as e:
        print(f"  无头自动登录失败: {e}")
        return False


def refresh_login_state(manual: bool = False) -> bool:
    """刷新登录态"""
    print("=" * 60)
    print("登录态刷新工具")
    print("=" * 60)
    print(f"\n目标页面: {TARGET_URL}")
    print(f"登录态文件: {STORAGE_STATE_PATH}")

    if not STORAGE_STATE_PATH.exists():
        print("\n没有已有登录态，尝试自动登录...")
        if _auto_login_headless():
            return True
        print("  需要手动登录")
        print("  运行: python3 login/save_login_state.py")
        return False

    with open(STORAGE_STATE_PATH, "r", encoding="utf-8") as f:
        old_state = json.load(f)
    old_cookies = len(old_state.get("cookies", []))
    print(f"\n当前登录态: {old_cookies} 个 Cookie")

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
        print(f"\n正在访问 {TARGET_URL}...")
        page.goto(TARGET_URL, timeout=30000, wait_until="domcontentloaded")

        """关键：domcontentloaded 时 cookie 存在，页面看起来正常
        但 JS 执行后可能发现服务端 session 过期而重定向到登录页
        所以必须等 networkidle 再检查 URL"""
        initial_url = page.url
        print(f"\n domcontentloaded 时 URL: {initial_url}")

        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception as e:
            print(f"networkidle 等待超时: {e}")
            # 即使超时也继续检查 URL

        current_url = page.url
        print(f"networkidle 后 URL: {current_url}")

        # 判断是否被重定向到登录页（关键：用登录域名精确匹配）
        is_redirected_to_login = any(domain in current_url for domain in LOGIN_DOMAINS)

        if is_redirected_to_login:
            print("\n登录态已过期，被重定向到登录页！")

            if manual:
                print("\n请在浏览器中完成登录")
                print("登录成功后回到终端按 Enter 键保存")

                input("按 Enter 保存登录态...")
            else:
                # 先尝试无头自动登录
                browser.close()
                if _auto_login_headless():
                    return True
                print("\n自动登录失败（可能需要验证码）")
                print("运行: python3 refresh_login_state.py --manual 进行手动登录")
                return False
        else:
            print("\n登录态有效！页面正常加载")

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
                print(f"  修复了 {fixed_count} 个 session cookie (expires=-1 -> 7d)")

            STORAGE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(STORAGE_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(new_state, f, ensure_ascii=False, indent=2)

            new_cookies = len(new_state.get("cookies", []))
            print(f"\n登录态已保存!")
            print(f"   Cookie 数量: {old_cookies} -> {new_cookies}")
            print(f"   文件: {STORAGE_STATE_PATH}")
            print(f"   大小: {STORAGE_STATE_PATH.stat().st_size / 1024:.1f} KB")
        except Exception as e:
            print(f"\n保存登录态失败: {e}")

        browser.close()

    return True


def ensure_valid_login_state() -> bool:
    """一键检查 + 刷新登录态（供编程调用）

    检查逻辑:
    1. 如果 storage_state 不存在 -> 自动登录
    2. 如果关键 cookie 已过期 -> 刷新（先自动，再手动）
    3. 如果 cookie 有效 -> 直接返回 True

    Returns:
        True 表示登录态有效，False 表示需要手动干预
    """
    if is_login_state_valid():
        return True

    print("[LOGIN] 登录态无效或已过期，尝试刷新...")
    return refresh_login_state(manual=False)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="刷新登录态")
    parser.add_argument("--manual", action="store_true", help="如果 session 过期，允许手动登录")
    parser.add_argument("--check-only", action="store_true", help="仅检查登录态是否有效，不刷新")

    args = parser.parse_args()

    if args.check_only:
        valid = is_login_state_valid()
        status = "有效" if valid else "无效/已过期"
        print(f"登录态状态: {status}")
        sys.exit(0 if valid else 1)

    success = refresh_login_state(manual=args.manual)
    sys.exit(0 if success else 1)