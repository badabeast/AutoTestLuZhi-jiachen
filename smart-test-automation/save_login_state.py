#!/usr/bin/env python3
"""
登录态保存工具

人工登录后保存 storage_state，供后续录制器自动复用。

使用方式:
    # 交互式登录（弹出浏览器，手动完成登录+验证码）
    python3 save_login_state.py

    # 直接访问指定 URL 登录
    python3 save_login_state.py --url <从配置文件获取，默认取 web-demand 的 login_page_url>

    # 账号预设（自动填写，但验证码仍需手动）
    python3 save_login_state.py --account test001 --password <从环境变量或配置获取>

登录完成后按 Enter 保存登录态并退出。
"""
import sys
import os
import json
import time
import argparse
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

# 加载 .env
from config.env_loader import load_env
load_env()

from playwright.sync_api import sync_playwright

STORAGE_STATE_PATH = Path("login_state/storage_state.json")


def save_login_state(url: str, account: str = "", password: str = ""):
    """打开浏览器进行交互式登录，保存 storage_state"""

    print("=" * 60)
    print("🔐 登录态保存工具")
    print("=" * 60)
    print()
    print(f"📌 登录页: {url}")
    print(f"📁 保存位置: {STORAGE_STATE_PATH}")
    print()

    # 检查已有登录态
    if STORAGE_STATE_PATH.exists():
        with open(STORAGE_STATE_PATH, "r", encoding="utf-8") as f:
            old_state = json.load(f)
        old_cookies = len(old_state.get("cookies", []))
        print(f"⚠️  已有登录态（{old_cookies} 个 Cookie），重新登录将覆盖")
        print()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            ignore_https_errors=True,
            permissions=["geolocation", "local-network-access"],
        )
        page = context.new_page()

        # 加载已有登录态（如果有的话可以跳过登录）
        page.goto(url, timeout=30000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)

        # 自动填写账号密码（如果提供了）
        time.sleep(int(os.environ.get("LOGIN_WAIT_SECONDS", "3")))
        if account:
            try:
                uname = page.locator("input[name=username], input[name=account], #username")
                if uname.first.is_visible(timeout=3000):
                    uname.first.fill(account)
                    print(f"✏️  已填写用户名: {account}")
            except Exception:
                pass

        if password:
            try:
                pwd = page.locator("input[type=password], #password")
                if pwd.first.is_visible(timeout=3000):
                    pwd.first.fill(password)
                    print(f"✏️  已填写密码: {'*' * len(password)}")
            except Exception:
                pass

        print()
        print("👉 请在浏览器中完成登录（包括验证码）")
        print("👉 登录成功后回到终端按 Enter 键保存登录态")
        print()

        try:
            input("⏳ 按 Enter 保存登录态...")
        except (EOFError, KeyboardInterrupt):
            print("\n⚠️  操作取消")
            browser.close()
            return

        # 保存登录态
        try:
            state = context.storage_state()

            # 关键修复：将 expires=-1 的 session cookie 改为 7 天后过期
            # Playwright storage_state 保存时，expires=-1 的 cookie 在新浏览器中会被忽略
            # 改为远期时间戳后，cookie 可以跨浏览器进程持久化
            seven_days_later = time.time() + 7 * 24 * 3600  # 7 天后的 Unix 时间戳
            for cookie in state.get("cookies", []):
                if cookie.get("expires", 0) == -1:
                    cookie["expires"] = seven_days_later
                    print(f"   🔄 修复 session cookie: {cookie['name']} → expires=7d")

            STORAGE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(STORAGE_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)

            cookies = state.get("cookies", [])
            origins = state.get("origins", [])
            auth_cookies = [
                c["name"]
                for c in cookies
                if any(kw in c.get("name", "").lower() for kw in ["token", "session", "auth", "jwt"])
            ]

            print()
            print("=" * 60)
            print(f"✅ 登录态已保存!")
            print(f"   Cookie 数量: {len(cookies)}")
            print(f"   localStorage 源: {len(origins)}")
            if auth_cookies:
                print(f"   认证 Cookie: {', '.join(auth_cookies[:5])}")
            print(f"   文件: {STORAGE_STATE_PATH}")
            print(f"   大小: {STORAGE_STATE_PATH.stat().st_size / 1024:.1f} KB")
            print("=" * 60)
            print()
            print("📝 后续录制会自动复用此登录态，无需重复登录")
            print("🔄 如需切换账号，运行: python3 save_login_state.py --fresh")

        except Exception as e:
            print(f"❌ 保存登录态失败: {e}")

        finally:
            browser.close()


def clear_login_state():
    """清除已保存的登录态"""
    if STORAGE_STATE_PATH.exists():
        STORAGE_STATE_PATH.unlink()
        print(f"🗑️  登录态已清除: {STORAGE_STATE_PATH}")
    else:
        print("⚠️  没有已保存的登录态")


def show_login_state():
    """显示已有登录态信息"""
    if not STORAGE_STATE_PATH.exists():
        print("⚠️  没有已保存的登录态")
        return

    with open(STORAGE_STATE_PATH, "r", encoding="utf-8") as f:
        state = json.load(f)

    cookies = state.get("cookies", [])
    origins = state.get("origins", [])

    print(f"📁 登录态文件: {STORAGE_STATE_PATH}")
    print(f"📏 文件大小: {STORAGE_STATE_PATH.stat().st_size / 1024:.1f} KB")
    print(f"🍪 Cookie 数量: {len(cookies)}")
    print(f"💾 localStorage 源: {len(origins)}")

    if cookies:
        domains = sorted({c.get("domain", "?") for c in cookies})
        print(f"🌐 域名列表: {', '.join(domains[:10])}")

        auth_cookies = [
            c["name"]
            for c in cookies
            if any(kw in c.get("name", "").lower() for kw in ["token", "session", "auth", "jwt"])
        ]
        if auth_cookies:
            print(f"🔑 认证 Cookie: {', '.join(auth_cookies[:5])}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="登录态保存工具")
    parser.add_argument("--url", default=os.environ.get("WEB_DEMAND_LOGIN_PAGE_URL", "https://login.test.zcygov.cn/user-login/#/login"),
                        help="默认打开登录页")
    parser.add_argument("--project", default="web-demand",
                        help="项目名称，用于从配置获取默认URL (web-demand)")
    parser.add_argument("--account", default="", help="预设账号（自动填写）")
    parser.add_argument("--password", default="", help="预设密码（自动填写）")
    parser.add_argument("--fresh", action="store_true", help="清除已有登录态并重新登录")
    parser.add_argument("--clear", action="store_true", help="清除登录态")
    parser.add_argument("--info", action="store_true", help="查看已有登录态信息")

    args = parser.parse_args()

    if args.clear:
        clear_login_state()
    elif args.info:
        show_login_state()
    else:
        if args.fresh:
            clear_login_state()
        # URL: 优先命令行参数 → 配置文件中的 login_page_url
        url = args.url
        if not url:
            try:
                from config.accounts import AccountManager
                project_config = AccountManager.get_project_config(args.project)
                if project_config:
                    url = project_config.login_page_url
                    print(f"📌 使用配置文件中的登录URL ({args.project}): {url}")
                else:
                    print(f"⚠️ 未找到项目 {args.project} 的配置，请通过 --url 指定登录页")
            except Exception as e:
                print(f"⚠️ 加载配置失败: {e}，请通过 --url 指定登录页")
        save_login_state(url=url, account=args.account, password=args.password)
