#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用页面守卫 — 登录自动恢复 + 操作失败自动重试

核心思路（PO 模型最佳实践）:
    - 登录守卫: goto 后被动检测，发现被踢到登录页就自动登录恢复
    - 弹窗守卫: 操作失败时才触发，检查是否有遮挡元素，有则关闭后重试
    - 不主动轮询/不 preemptive 操作，只在异常时介入

所有模块共享同一套守卫逻辑，维护这一个文件即可。
"""

import os
import re
import time
from pathlib import Path


# ============================================================
# 登录恢复
# ============================================================

def do_login(page) -> bool:
    """自动执行 UI 登录

    优先级:
      1. login_state/login_actions.py — 从录制脚本提取的登录操作（最精准）
      2. .env 账号密码 + 通用选择器（备用兜底）

    Returns:
        bool: 是否登录成功
    """
    # 策略 1: 录制的登录操作
    login_actions_path = Path("login_state/login_actions.py")
    if login_actions_path.exists():
        login_code = login_actions_path.read_text(encoding="utf-8")
        if login_code.strip():
            print("   🔐 使用录制登录操作...")
            try:
                exec(login_code, {"page": page})
                # 等待页面离开登录状态，最多15秒
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                if not _is_on_login_page(page):
                    print(f"   ✅ 登录成功, URL: {page.url[:80]}")
                    return True
            except Exception as e:
                print(f"   ⚠️ 录制登录失败: {e}")

    # 策略 2: 环境变量 + 通用选择器
    account = os.environ.get("WEB_DEMAND_ACCOUNT", "")
    password = os.environ.get("WEB_DEMAND_PASSWORD", "")
    if not account or not password:
        print("   ⚠️ 未配置 WEB_DEMAND_ACCOUNT/PASSWORD")
        return False
    try:
        print(f"   🔐 通用选择器登录: {account}")
        uname = page.get_by_role("textbox", name=re.compile(r"用户名|手机|邮箱"))
        if uname.count() > 0:
            uname.first.click()
            uname.first.fill(account)
            time.sleep(0.3)
        pwd = page.get_by_role("textbox", name="密码")
        if pwd.count() > 0:
            pwd.first.click()
            pwd.first.fill(password)
            time.sleep(0.3)
        login_btn = page.get_by_role("button", name=re.compile(r"登\s*录"))
        # 勾选协议复选框
        try:
            checkbox = page.locator('.doraemon-checkbox')
            if checkbox.count() > 0 and not checkbox.is_checked():
                checkbox.click()
                time.sleep(0.2)
        except Exception:
            pass
        if login_btn.count() > 0:
            login_btn.first.click()
        # 等待页面导航完成（登录后跳转）
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        if not _is_on_login_page(page):
            print(f"   ✅ 登录成功, URL: {page.url[:80]}")
            return True
    except Exception as e:
        print(f"   ⚠️ 登录失败: {e}")
    return False


def _is_on_login_page(page) -> bool:
    """检测当前是否在登录页"""
    url = page.url.lower()
    return "login" in url and ("user-login" in url or "sso" in url)


def ensure_logged_in(page, target_url: str = None):
    """登录守卫 — goto 后被动检测

    只在页面跳转到登录页时才触发，不主动干扰正常流程。
    """
    if not _is_on_login_page(page):
        return
    print(f"   🔒 检测到登录页，触发自动登录恢复")
    if do_login(page):
        if target_url and "login" not in target_url.lower():
            page.goto(target_url, timeout=30000)
            page.wait_for_load_state("domcontentloaded", timeout=15000)
    else:
        print("   ❌ 自动登录失败")


# ============================================================
# 弹窗检测与关闭（被动触发）
# ============================================================

_DIALOG_SELECTORS = [
    '[role="dialog"]',
    '.ant-modal-wrap',
    '.el-dialog__wrapper',
    '.doraemon-modal-wrap',
    '.modal.show',
    '.doraemon-message',
    '.ant-message',
]

_CLOSE_BUTTON_SELECTORS = [
    '[aria-label="Close"]', '[aria-label="关闭"]',
    '.close', '.ant-modal-close',
    '.el-dialog__closebtn', '.doraemon-modal-close',
]


def _has_blocking_dialog(page) -> bool:
    """检测页面上是否有遮挡性弹窗"""
    try:
        for sel in _DIALOG_SELECTORS:
            dialog = page.locator(sel)
            if dialog.count() > 0 and dialog.first.is_visible():
                return True
    except Exception:
        pass
    return False


def dismiss_dialogs(page) -> bool:
    """关闭遮挡弹窗 — ESC + 关闭按钮

    Returns:
        bool: 是否成功关闭了弹窗
    """
    closed = False
    try:
        # ESC 关闭（对大多数弹窗有效）
        page.keyboard.press("Escape")
        time.sleep(0.3)

        # 如果 ESC 没关掉，尝试点击关闭按钮
        if _has_blocking_dialog(page):
            for sel in _DIALOG_SELECTORS:
                dialog = page.locator(sel)
                if dialog.count() > 0 and dialog.first.is_visible():
                    for cs in _CLOSE_BUTTON_SELECTORS:
                        close_btn = dialog.first.locator(cs)
                        if close_btn.count() > 0:
                            close_btn.first.click()
                            time.sleep(0.2)
                            closed = True
                            break
                    if closed:
                        break
        elif not _has_blocking_dialog(page):
            # ESC 已经关掉了
            closed = True

        if closed:
            print("   🔄 已关闭异常弹窗")
    except Exception:
        pass
    return closed


# ============================================================
# 安全操作 — 失败时自动重试（弹窗/登录恢复）
# ============================================================

def _safe_action(page, action_fn, description: str, timeout: int = 10000, max_retries: int = 2) -> bool:
    """通用安全操作 — 失败时检查弹窗遮挡/登录状态并重试

    Args:
        page: Playwright page 对象
        action_fn: 执行操作的 callable，接收 timeout 参数
        description: 操作描述（用于日志）
        timeout: 操作超时时间
        max_retries: 最大重试次数

    Returns:
        bool: 操作是否成功
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            action_fn(timeout=timeout)
            return True
        except Exception as e:
            last_error = e
            if attempt >= max_retries:
                break
            # 检查是否被踢到登录页
            if _is_on_login_page(page):
                print(f"   🔒 {description}失败 + 在登录页，触发登录恢复")
                ensure_logged_in(page, page.url)
                continue
            # 检查是否有遮挡弹窗
            if _has_blocking_dialog(page):
                print(f"   ⚠️ {description}失败，检测到遮挡弹窗，尝试关闭")
                dismiss_dialogs(page)
                time.sleep(0.3)
                continue
            # 没有明显原因，尝试 ESC 后重试
            page.keyboard.press("Escape")
            time.sleep(0.3)
    if last_error:
        print(f"   ❌ {description}重试 {max_retries} 次仍失败: {last_error}")
    return False


def safe_click(page, locator, timeout: int = 10000, max_retries: int = 2) -> bool:
    """安全点击 — 失败时检查弹窗遮挡并重试"""
    return _safe_action(page, lambda timeout=timeout: locator.click(timeout=timeout),
                        "click", timeout, max_retries)


def safe_fill(page, locator, value: str, timeout: int = 10000, max_retries: int = 2) -> bool:
    """安全填充 — 失败时检查弹窗遮挡并重试"""
    def _do_fill(timeout=timeout):
        locator.click(timeout=timeout)
        locator.fill(value, timeout=timeout)
    return _safe_action(page, _do_fill, "fill", timeout, max_retries)


# ============================================================
# 页面就绪等待（组合守卫）
# ============================================================

def wait_for_page_ready(page, timeout: int = 15000):
    """等待页面加载 + 登录守卫（goto 后调用）

    不做弹窗处理 — 弹窗只在操作失败时才处理。
    """
    try:
        page.wait_for_load_state("domcontentloaded", timeout=timeout)
    except Exception:
        pass
    ensure_logged_in(page, page.url)
