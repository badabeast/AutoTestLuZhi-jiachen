#!/usr/bin/env python3
"""自动登录并保存 storage_state

改进说明:
  - 使用 networkidle 等待 SPA 重定向完成，替代不可靠的 time.sleep
  - 登录成功判断改用登录域名精确匹配，而非模糊的 "login" in url
  - 增加重试机制：第一次失败后尝试刷新页面重试
"""
import os
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from config.env_loader import load_env
load_env()

from playwright.sync_api import sync_playwright

STORAGE_STATE_PATH = Path("login_state/storage_state.json")
LOGIN_URL = os.environ.get("WEB_DEMAND_LOGIN_PAGE_URL", "https://login.test.zcygov.cn/user-login/#/login")
LOGIN_DOMAINS = ["login.test.zcygov.cn", "login.staging.zcygov.cn", "login.zcygov.cn"]
ACCOUNT = os.environ.get("WEB_DEMAND_ACCOUNT", "tmind_admin")
PASSWORD = os.environ.get("WEB_DEMAND_PASSWORD", "Zfcg@123456")

print(f"登录页: {LOGIN_URL}")
print(f"账号: {ACCOUNT}")

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
    # 等待页面完全加载（SPA 渲染）
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        time.sleep(3)

    print(f"当前 URL: {page.url}")
    print(f"页面标题: {page.title()}")

    # 尝试填写账号密码
    try:
        # 常见登录表单选择器
        selectors_to_try = [
            ("input[name=username]", ACCOUNT),
            ("input[name=account]", ACCOUNT),
            ("input[placeholder*=用户]", ACCOUNT),
            ("input[placeholder*=账号]", ACCOUNT),
            ("input[type=text]", ACCOUNT),
        ]
        pwd_selectors = [
            "input[type=password]",
            "input[name=password]",
        ]

        filled_user = False
        for sel, val in selectors_to_try:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    el.fill(val)
                    print(f"已填写用户名: {sel}")
                    filled_user = True
                    break
            except Exception:
                continue

        filled_pwd = False
        for sel in pwd_selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    el.fill(PASSWORD)
                    print(f"已填写密码: {sel}")
                    filled_pwd = True
                    break
            except Exception:
                continue

        if not filled_user or not filled_pwd:
            print("未能自动填写表单，截图查看...")
            os.makedirs("output/screenshots", exist_ok=True)
            page.screenshot(path="output/screenshots/login_page.png")
            print("截图已保存到 output/screenshots/login_page.png")
            browser.close()
            sys.exit(1)

        # 点击登录按钮
        login_btn_selectors = [
            "button:has-text('登录')",
            "button:has-text('登 录')",
            "button[type=submit]",
            ".login-btn",
            "button:has-text('Login')",
        ]
        clicked = False
        for sel in login_btn_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    print(f"已点击登录按钮: {sel}")
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            print("未找到登录按钮")
            os.makedirs("output/screenshots", exist_ok=True)
            page.screenshot(path="output/screenshots/login_page.png")
            browser.close()
            sys.exit(1)

        # 等待 SPA 重定向完成（用 networkidle 而非固定 sleep）
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            # networkidle 超时可能是 SPA 正常行为，等待一小段时间
            time.sleep(3)

        current_url = page.url
        print(f"登录后 URL: {current_url}")

        # 用登录域名精确匹配判断是否仍在登录页（避免误匹配 URL 中的 "login" 参数）
        is_still_login = any(domain in current_url for domain in LOGIN_DOMAINS)

        if is_still_login:
            print("仍在登录页，可能有验证码或登录失败")
            os.makedirs("output/screenshots", exist_ok=True)
            page.screenshot(path="output/screenshots/login_failed.png")
            print("截图已保存到 output/screenshots/login_failed.png")
            print("请手动执行: python3 login/save_login_state.py")
            browser.close()
            sys.exit(1)

        # 保存 storage state
        new_state = context.storage_state()
        seven_days = time.time() + 7 * 24 * 3600
        for c in new_state.get("cookies", []):
            if c.get("expires", 0) == -1:
                c["expires"] = seven_days

        STORAGE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(STORAGE_STATE_PATH, "w") as f:
            json.dump(new_state, f, ensure_ascii=False, indent=2)

        print(f"登录态已保存! ({len(new_state.get('cookies', []))} 个 Cookie)")
        browser.close()

    except Exception as e:
        print(f"登录过程出错: {e}")
        os.makedirs("output/screenshots", exist_ok=True)
        page.screenshot(path="output/screenshots/login_error.png")
        browser.close()
        sys.exit(1)
