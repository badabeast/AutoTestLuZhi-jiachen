#!/usr/bin/env python3
"""自动登录并保存storage_state。用networkidle等SPA重定向，登录域名精确匹配判断成功。"""
import os
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.env_loader import load_env
load_env()

from playwright.sync_api import sync_playwright

STORAGE_STATE_PATH = Path("login_state/storage_state.json")
LOGIN_URL = os.environ.get("WEB_DEMAND_LOGIN_PAGE_URL", "")
LOGIN_DOMAINS = os.environ.get("WEB_DEMAND_LOGIN_DOMAINS", "").split(",") if os.environ.get("WEB_DEMAND_LOGIN_DOMAINS") else []
ACCOUNT = os.environ.get("WEB_DEMAND_ACCOUNT", "")
PASSWORD = os.environ.get("WEB_DEMAND_PASSWORD", "")


def auto_login():
    """自动登录并保存storage_state"""
    login_url = LOGIN_URL
    target_url = os.environ.get("WEB_DEMAND_URL", "")
    print(f"登录页: {login_url}")
    print(f"目标页: {target_url}")
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

        # 先去业务页 → 自动跳到 login 页（获取最准确的redirect target）
        first_url = target_url if target_url else login_url
        page.goto(first_url, timeout=30000, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            time.sleep(3)

        print(f"初始 URL: {page.url}")
        print(f"页面标题: {page.title()}")

        # 是否已经在业务页（已登录）
        if target_url and not any(domain in page.url for domain in LOGIN_DOMAINS):
            print("已在业务页，登录态有效，直接保存")
            _save_state_and_exit(context, STORAGE_STATE_PATH)
            browser.close()
            return

        try:
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

            # 勾选"我已阅读并同意"（新登录页需要）
            try:
                checkbox = page.get_by_role("checkbox", name="我已阅读并同意")
                if checkbox.is_visible(timeout=2000):
                    checkbox.check()
                    print("已勾选同意条款")
            except Exception:
                print("未找到同意条款勾选框，跳过")

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

            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                time.sleep(3)

            current_url = page.url
            print(f"登录后 URL: {current_url}")

            # 判断是否登录成功：不再在登录页 hash，或已重定向到业务域
            is_still_login_page = "#/login" in current_url or "#login" in current_url

            if is_still_login_page:
                print("仍在登录页面，可能有验证码或登录失败")
                os.makedirs("output/screenshots", exist_ok=True)
                page.screenshot(path="output/screenshots/login_failed.png")
                print("截图已保存到 output/screenshots/login_failed.png")
                # 再试一次：可能是点击后需要等待重定向
                try:
                    page.wait_for_url("**/demand_front/**", timeout=15000)
                    print(f"等待后 URL: {page.url}")
                    is_still_login_page = False
                except Exception:
                    pass

            if is_still_login_page:
                print("请手动执行: python3 login/save_login_state.py")
                browser.close()
                sys.exit(1)

            _save_state_and_exit(context, STORAGE_STATE_PATH)
            browser.close()

        except Exception as e:
            print(f"登录过程出错: {e}")
            os.makedirs("output/screenshots", exist_ok=True)
            page.screenshot(path="output/screenshots/login_error.png")
            browser.close()
            sys.exit(1)


def _save_state_and_exit(context, state_path):
    """保存storage_state到文件"""
    new_state = context.storage_state()
    seven_days = time.time() + 7 * 24 * 3600
    for c in new_state.get("cookies", []):
        if c.get("expires", 0) == -1:
            c["expires"] = seven_days

    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w") as f:
        json.dump(new_state, f, ensure_ascii=False, indent=2)

    print(f"登录态已保存! ({len(new_state.get('cookies', []))} 个 Cookie)")


if __name__ == "__main__":
    auto_login()
