#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BasePage — 页面基础类（全局通用）

封装 Playwright 常用操作，所有业务 Page 类继承此类。
提供：安全点击/填写/选择、智能等待、登录守卫、通用表单填写、自愈错误捕获。
"""

import os
import re
import time

from playwright.sync_api import expect, Locator
from core.locator_error import capture_locator_error, LocatorActionError


class BasePage:
    """页面基础类 — 所有业务 Page 类的父类"""

    # 默认超时配置（秒/毫秒，按测试环境实际响应调优）
    DEFAULT_TIMEOUT = 5000        # 普通操作 5s
    NAVIGATION_TIMEOUT = 30000    # 页面导航 30s
    DROPDOWN_TIMEOUT = 3000       # 下拉选项 3s
    RETRY_COUNT = 2               # 失败重试次数
    RETRY_INTERVAL = 0.5          # 重试间隔（秒）

    def __init__(self, page):
        self.page = page

    # 公用工具方法

    def get_current_username(self) -> str:
        """从页面右上角获取当前登录用户名称（公用方法）

        选择器: #back-sky header 区域 .display-name
        获取失败时返回空字符串。
        """
        selector = (
            "#back-sky > div > div.microlayout-header-wrap > div > "
            "div.microlayout-header-user > div > div.display-name"
        )
        try:
            el = self.page.locator(selector).first
            el.wait_for(state="visible", timeout=5000)
            name = el.text_content(timeout=2000).strip()
            if name:
                print(f"   当前登录用户: '{name}'")
                return name
        except Exception as e:
            print(f"   ⚠️ 获取用户名失败: {e}")
        return ""

    # 智能等待核心

    @capture_locator_error(action="wait")
    def _wait_for_element(self, locator, timeout=None):
        """等待元素可见 + 稳定（核心方法）

        经验: 直接 click/fill 失败的 90% 原因是元素还没渲染完。
        这个方法确保元素可见、不被遮挡、尺寸稳定。

        Args:
            locator: Playwright Locator 对象
            timeout: 超时毫秒数
        """
        timeout = timeout or self.DEFAULT_TIMEOUT
        locator.wait_for(state="visible", timeout=timeout)

    @capture_locator_error(action="click")
    def _safe_click(self, locator, timeout=None):
        """安全点击：等待可见 → 尝试点击 → 被遮挡则处理 → 重试

        经验: 弹窗遮挡是最常见的点击失败原因。
        策略: 先尝试点击，如果被 dialog 遮挡，尝试按 Escape 关闭弹窗后重试。

        Args:
            locator: Playwright Locator 对象
            timeout: 超时毫秒数
        """
        timeout = timeout or self.DEFAULT_TIMEOUT
        for attempt in range(self.RETRY_COUNT + 1):
            try:
                locator.wait_for(state="visible", timeout=timeout)
                locator.click(timeout=timeout)
                return
            except Exception as e:
                error_msg = str(e)
                if "intercepts pointer events" in error_msg or "not stable" in error_msg:
                    # 弹窗遮挡或元素不稳定：尝试 Escape 关闭弹窗
                    try:
                        self.page.keyboard.press("Escape")
                        time.sleep(0.5)
                    except Exception:
                        pass
                if attempt < self.RETRY_COUNT:
                    time.sleep(self.RETRY_INTERVAL)
                else:
                    raise

    @capture_locator_error(action="fill")
    def _safe_fill(self, locator, value, timeout=None):
        """安全填写：等待可见 → 检查已有值 → 有值则跳过 → 无值则填入

        规则: 如果字段已有值，不修改直接跳过；无值才填写

        Args:
            locator: Playwright Locator 对象
            value: 要填入的值
            timeout: 超时毫秒数
        """
        timeout = timeout or self.DEFAULT_TIMEOUT
        locator.wait_for(state="visible", timeout=timeout)
        # 检查已有值，有值则跳过
        current_value = locator.input_value(timeout=timeout)
        if current_value and current_value.strip():
            print(f"   ⏭️ 字段已有值 '{current_value}'，跳过填写")
            return
        # 点击聚焦 → 填入
        locator.click(timeout=timeout)
        locator.fill(value, timeout=timeout)
        # 触发框架事件（Vue/React 等框架需要 input + change 事件同步内部状态）
        try:
            locator.dispatch_event("input")
        except Exception:
            pass
        try:
            locator.dispatch_event("change")
        except Exception:
            pass

    @capture_locator_error(action="check")
    def _safe_check(self, locator, timeout=None):
        """安全勾选：等待可见 → 检查状态 → 勾选

        Args:
            locator: Playwright Locator 对象
            timeout: 超时毫秒数
        """
        timeout = timeout or self.DEFAULT_TIMEOUT
        locator.wait_for(state="visible", timeout=timeout)
        if not locator.is_checked():
            locator.check(timeout=timeout)

    @capture_locator_error(action="select")
    def _wait_and_select_option(self, trigger_locator, option_text, timeout=None):
        """安全下拉选择：点击触发 → 等选项列表 → 选指定文本

        经验: 下拉选择是最容易出问题的操作:
          1. 选项列表是异步加载的 → 点击后要等列表出现
          2. 选项列表可能被其他元素遮挡 → 需要 z-index 处理
          3. 搜索型下拉需要先输入文字触发搜索 → 等搜索结果

        Args:
            trigger_locator: 下拉触发元素
            option_text: 要选择的选项文本
            timeout: 超时毫秒数
        """
        timeout = timeout or self.DEFAULT_TIMEOUT
        # 1. 点击触发下拉
        self._safe_click(trigger_locator, timeout=timeout)
        # 2. 等选项列表出现后选择
        # 3. 选择指定文本的选项
        option = self.page.get_by_text(option_text, exact=False).first
        option.wait_for(state="visible", timeout=self.DROPDOWN_TIMEOUT)
        option.click(timeout=timeout)

    # 页面导航

    def goto(self, url: str, wait_element: str = None):
        """跳转到指定 URL，智能等待页面就绪

        修复说明（SPA 重定向检测）:
          - 原实现在 domcontentloaded 后立即做登录检测，但 SPA 的客户端重定向尚未触发，
            URL 仍然是目标地址，检测不到登录页。
          - 修复后：先等待 networkidle（SPA 重定向在此期间完成），再做第1次登录检测。
          - 第2次检测保留在 wait_for_selector 失败后，覆盖慢跳转场景。
          - 关键修复：raise 语句移到登录检测之后，确保登录守卫不会被跳过。
        """
        self.page.goto(url, timeout=self.NAVIGATION_TIMEOUT, wait_until="domcontentloaded")

        # 等待 SPA 客户端重定向完成（networkidle 或至少 2 秒）
        # domcontentloaded 时 JS 重定向逻辑可能还没执行，需要等待
        try:
            self.page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            # networkidle 超时（正常，SPA 持续有网络活动），
            # 额外等待给 SPA 重定向留时间
            self.page.wait_for_timeout(2000)

        # 第1次登录检测：SPA 重定向完成后检查
        if self._check_and_handle_login(url, wait_element):
            return

        if wait_element:
            selector = f"text={wait_element}"
            try:
                self.page.wait_for_selector(selector, timeout=self.NAVIGATION_TIMEOUT)
            except Exception as e:
                # 第2次登录检测：SPA 慢跳转场景（页面先加载，后续才跳登录页）
                # 关键修复：先检测登录再 raise，避免登录守卫被跳过
                if self._check_and_handle_login(url, wait_element):
                    return
                # 不是登录页，包装成 LocatorActionError 抛出
                if not isinstance(e, LocatorActionError):
                    raise LocatorActionError(
                        selector=selector,
                        action="wait_for_selector",
                        page_url=self.page.url,
                        original_error=e,
                    ) from e
                raise

    def _check_and_handle_login(self, target_url: str = None, wait_element: str = None) -> bool:
        """登录守卫：检测登录页并自动登录。返回 True 表示已处理

        修复说明:
          - 增加 URL 变化检测：不仅检查是否在登录域名，还检查 URL 是否发生跳转
          - 登录成功判断改为检测认证 cookie 存在 + URL 变化双重验证
          - 登录后优先等待 networkidle 而非仅 wait_for_url
          - 增加验证码场景回退提示
        """
        # 登录页域名列表（测试环境 + 预发环境）
        login_domains = ["login.test.zcygov.cn", "login.staging.zcygov.cn", "login.zcygov.cn"]

        # 方式1: URL 包含登录域名
        current_url = self.page.url
        is_login_page = any(domain in current_url for domain in login_domains)

        # 方式2: URL 发生了跳转（从目标页跳到了其他页面，可能是登录页）
        # 只在有 target_url 时检测，且排除 hash 变化（SPA 内部路由）
        if not is_login_page and target_url:
            # 去掉 hash 部分比较基础 URL
            target_base = target_url.split("#")[0] if "#" in target_url else target_url
            current_base = current_url.split("#")[0] if "#" in current_url else current_url
            if current_base != target_base:
                # URL 变了，检查是否跳到了登录相关页面
                if any(domain in current_url for domain in login_domains):
                    is_login_page = True
                else:
                    # 跳到了未知页面，检查是否有登录表单元素
                    pass

        # 方式3: 检查页面是否包含登录表单元素（SPA 异步跳转场景）
        if not is_login_page:
            try:
                login_input = self.page.get_by_role("textbox", name="用户名/手机/邮箱")
                is_login_page = login_input.count() > 0 and login_input.first.is_visible(timeout=1500)
            except Exception:
                pass

        if not is_login_page:
            return False

        print("\n[LOGIN] 检测到登录页，自动登录中...")
        print(f"[LOGIN] 当前 URL: {current_url}")
        try:
            account = os.environ.get("WEB_DEMAND_ACCOUNT", "")
            password = os.environ.get("WEB_DEMAND_PASSWORD", "")
            if not account or not password:
                print("[LOGIN] 环境变量 WEB_DEMAND_ACCOUNT / WEB_DEMAND_PASSWORD 未配置")
                print("[LOGIN] 无法自动登录，请手动执行: python3 login/save_login_state.py")
                return False

            # 等登录表单完全加载
            username_input = self.page.get_by_role("textbox", name="用户名/手机/邮箱")
            username_input.wait_for(state="visible", timeout=10000)
            username_input.fill(account)
            self.page.get_by_role("textbox", name="密码").fill(password)

            # 勾选用户协议（checkbox 可能不存在则跳过）
            try:
                agree_checkbox = self.page.get_by_role("checkbox")
                if agree_checkbox.count() > 0 and not agree_checkbox.first.is_checked():
                    agree_checkbox.first.check()
            except Exception:
                pass

            # 点击登录按钮
            self.page.get_by_role("button", name="登 录").click()

            # 等待登录完成：URL 变化 + 网络稳定
            login_success = False
            try:
                self.page.wait_for_url(
                    lambda url: not any(domain in url for domain in login_domains),
                    timeout=30000,
                )
                login_success = True
            except Exception:
                # wait_for_url 超时，但 URL 可能已经变化了
                if not any(domain in self.page.url for domain in login_domains):
                    login_success = True

            # 额外等待 SPA 加载完成
            try:
                self.page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

            if not login_success:
                # 可能有验证码或其他问题，打印详细信息
                print(f"[LOGIN] 登录后仍在登录页: {self.page.url}")
                print("[LOGIN] 可能需要验证码，请手动执行: python3 login/save_login_state.py")
                # 截图用于调试
                try:
                    screenshot_dir = "output/screenshots"
                    os.makedirs(screenshot_dir, exist_ok=True)
                    self.page.screenshot(path=f"{screenshot_dir}/login_failed_auto.png")
                    print(f"[LOGIN] 截图已保存: {screenshot_dir}/login_failed_auto.png")
                except Exception:
                    pass
                return False

            # 保存登录态（覆盖旧的）
            storage_path = "login_state/storage_state.json"
            try:
                self.page.context.storage_state(path=storage_path)
                # 清洗 expires=-1 的 cookie
                self._fix_storage_state_cookies(storage_path)
                print("[LOGIN] 自动登录成功，登录态已保存")
            except Exception as e:
                print(f"[LOGIN] 保存登录态失败: {e}")

            # 登录后等页面自动跳转到目标页（服务端会 redirect）
            if wait_element:
                try:
                    self.page.wait_for_selector(f"text={wait_element}", timeout=30000)
                    return True
                except Exception:
                    pass

            # 如果自动跳转失败，手动 goto
            if target_url:
                self.page.goto(target_url, timeout=self.NAVIGATION_TIMEOUT, wait_until="domcontentloaded")
                try:
                    self.page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                if wait_element:
                    self.page.wait_for_selector(f"text={wait_element}", timeout=self.NAVIGATION_TIMEOUT)
            return True

        except Exception as e:
            print(f"[LOGIN] 自动登录异常: {e}")
            return False

    @staticmethod
    def _fix_storage_state_cookies(storage_path: str):
        """清洗 storage_state 中 expires=-1 的 session cookie

        Playwright 在新浏览器 context 中会忽略 expires=-1 的 cookie，
        导致 SESSION/SSOSESSION 等认证 cookie 丢失。
        """
        import json
        import time
        try:
            with open(storage_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            seven_days = time.time() + 7 * 24 * 3600
            fixed = 0
            for c in state.get("cookies", []):
                if c.get("expires", 0) == -1:
                    c["expires"] = seven_days
                    fixed += 1
            if fixed:
                with open(storage_path, "w", encoding="utf-8") as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
                print(f"[LOGIN] 修复了 {fixed} 个 session cookie (expires=-1 -> 7d)")
        except Exception as e:
            print(f"[LOGIN] 清洗 cookie 失败: {e}")

    # ── 通用操作（带智能等待）──────────────────────────────

    def click_by_role(self, role: str, name: str = ""):
        """通过 role 安全点击"""
        self._safe_click(self.page.get_by_role(role, name=name))

    def click_by_text(self, text: str, exact: bool = False):
        """通过文本安全点击"""
        self._safe_click(self.page.get_by_text(text, exact=exact).first)

    def click_by_selector(self, selector: str):
        """通过 CSS 选择器安全点击"""
        self._safe_click(self.page.locator(selector).first)

    def fill_by_role(self, role: str, name: str, value: str):
        """通过 role 安全填写"""
        self._safe_fill(self.page.get_by_role(role, name=name), value)

    def fill_by_text(self, label_text: str, value: str):
        """通过标签文本找输入框并填写

        先找标签文本，再从父级区域找 textbox。
        """
        label = self.page.get_by_text(label_text).first
        self._wait_for_element(label)
        parent_area = label.locator("..").locator("..")
        textbox = parent_area.locator("input[type='text'], input:not([type]), textarea").first
        self._safe_fill(textbox, value)

    # ── 通用表单操作（跨表单通用，字段名稳定、位置可变）───────

    def smart_fill(self, label_text: str, value: str, fallback_selector: str = None, required: bool = True):
        """通用表单填写 — 通过字段名定位，位置变了也能找到

        定位策略（按优先级尝试）:
          1. get_by_role("textbox", name=含label_text) — 表单控件有 name/title 属性
          2. 找 label 文本 → 向上找父级表单区域 → 区域内找 input/textarea
          3. 找 placeholder=含label_text 的输入框
          4. 回退到 fallback_selector（录制时的 CSS/ID 选择器）
          5. 全部失败 → 抛异常，让 healer 兜底

        Args:
            label_text: 字段名（如"需求单名称""经费项目号"）
            value: 要填入的值
            fallback_selector: 录制时的原始选择器，作为兜底
        """
        # 策略1: role + name（精确匹配）
        try:
            textbox = self.page.get_by_role("textbox", name=label_text)
            if textbox.count() > 0:
                print(f"   smart_fill[{label_text}]: 策略1命中 (role+name精确)")
                self._safe_fill(textbox.first, value)
                return
        except Exception:
            pass

        # 策略1b: role + name（带 * 号的必填项）
        try:
            textbox = self.page.get_by_role("textbox", name=f"* {label_text}")
            if textbox.count() > 0:
                print(f"   smart_fill[{label_text}]: 策略1b命中 (role+name带*)")
                self._safe_fill(textbox.first, value)
                return
        except Exception:
            pass

        # 策略1c: role + name 模糊匹配（name 属性包含 label_text）
        try:
            all_textboxes = self.page.get_by_role("textbox")
            for i in range(all_textboxes.count()):
                tb = all_textboxes.nth(i)
                tb_name = tb.get_attribute("name") or ""
                tb_title = tb.get_attribute("title") or ""
                tb_aria = tb.get_attribute("aria-label") or ""
                if label_text in tb_name or label_text in tb_title or label_text in tb_aria:
                    print(f"   smart_fill[{label_text}]: 策略1c命中 (模糊匹配name属性)")
                    self._safe_fill(tb, value)
                    return
        except Exception:
            pass

        # 策略2: 找 label 文本 → 父级区域内找 input
        try:
            label = self.page.get_by_text(label_text, exact=False).first
            if label.count() > 0 and label.is_visible(timeout=1000):
                # 逐级向上找包含 input 的表单区域
                for level in range(1, 5):
                    area = label
                    for _ in range(level):
                        area = area.locator("..")
                    textbox = area.locator(
                        "input[type='text'], input:not([type]), textarea, "
                        ".doraemon-input input, .ant-input, .el-input input"
                    ).first
                    if textbox.count() > 0 and textbox.is_visible(timeout=500):
                        print(f"   smart_fill[{label_text}]: 策略2命中 (label→父级区域→input, level={level})")
                        self._safe_fill(textbox, value)
                        return
        except Exception:
            pass

        # 策略3: placeholder 匹配
        try:
            input_el = self.page.locator(
                f"input[placeholder*='{label_text}'], textarea[placeholder*='{label_text}']"
            ).first
            if input_el.count() > 0:
                print(f"   smart_fill[{label_text}]: 策略3命中 (placeholder匹配)")
                self._safe_fill(input_el, value)
                return
        except Exception:
            pass

        # 策略4: 回退到录制时的 CSS 选择器
        if fallback_selector:
            try:
                print(f"   smart_fill[{label_text}]: 策略4回退到 fallback_selector={fallback_selector}")
                self._safe_fill(self.page.locator(fallback_selector).first, value)
                return
            except Exception as e:
                print(f"   smart_fill[{label_text}]: 策略4也失败了: {e}")

        if required:
            raise RuntimeError(f"smart_fill 失败: 找不到字段 '{label_text}' 的输入框")
        else:
            print(f"   ⚠️ smart_fill[{label_text}]: 字段不存在，跳过")

    def smart_select(self, label_text: str, option_text: str, fallback_selector: str = None, required: bool = True):
        """通用下拉选择 — 通过字段名定位下拉框，选择指定选项

        规则: 如果字段已有值，不修改直接跳过；无值才选择

        Args:
            label_text: 字段名（如"采购方式""费用类型"）
            option_text: 要选择的选项文本（如"分散采购""办公用品"）
            fallback_selector: 录制时的原始选择器，作为兜底
        """
        # 先检查是否已有值（找 label 区域内的已选文本）
        try:
            label = self.page.get_by_text(label_text, exact=False).first
            if label.count() > 0 and label.is_visible(timeout=1000):
                for level in range(1, 5):
                    area = label
                    for _ in range(level):
                        area = area.locator("..")
                    # 检查下拉框是否已有选中值
                    selected = area.locator(".doraemon-select-selection-selected-value, .ant-select-selection-selected-value, .el-select__selected-item")
                    if selected.count() > 0:
                        val = selected.first.text_content(timeout=500)
                        if val and val.strip() and val.strip() != "请选择":
                            print(f"   ⏭️ smart_select[{label_text}]: 已有值 '{val.strip()}'，跳过")
                            return
        except Exception:
            pass

        clicked_trigger = False

        # 策略0: doraemon form-item 结构定位（label + control-wrapper 同级）
        # 优先用组件库 DOM 结构，避免全页面 get_by_text 误匹配导航栏
        try:
            label_els = self.page.locator(".doraemon-form-item-label").all()
            for label_el in label_els:
                try:
                    text = label_el.text_content(timeout=300).strip()
                    if label_text not in text:
                        continue
                    # label 匹配 → 取父级 form-item → 找同级 control-wrapper
                    form_item = label_el.locator("..")
                    control = form_item.locator(
                        ".doraemon-form-item-control-wrapper"
                    ).first
                    if control.count() == 0:
                        continue
                    trigger = control.locator(
                        ".doraemon-select-selection, .ant-select-selection, "
                        ".doraemon-cascader-input, .doraemon-cascader-picker, "
                        "[role='combobox'], select"
                    ).first
                    if trigger.count() > 0 and trigger.is_visible(timeout=500):
                        self._safe_click(trigger)
                        clicked_trigger = True
                        break
                except Exception:
                    continue
        except Exception:
            pass

        # 策略1: 找 label 文本 → 父级区域内找下拉触发器
        try:
            label = self.page.get_by_text(label_text, exact=False).first
            if label.count() > 0 and label.is_visible(timeout=1000):
                for level in range(1, 5):
                    area = label
                    for _ in range(level):
                        area = area.locator("..")
                    # 常见下拉框触发器选择器
                    triggers = [
                        area.locator(".doraemon-select-selection").first,
                        area.locator(".ant-select-selection").first,
                        area.locator(".el-select").first,
                        area.locator("select").first,
                        area.locator("[role='combobox']").first,
                        area.locator(".doraemon-select-selection__rendered").first,
                    ]
                    for trigger in triggers:
                        if trigger.count() > 0 and trigger.is_visible(timeout=500):
                            self._safe_click(trigger)
                            clicked_trigger = True
                            break
                    if clicked_trigger:
                        break
        except Exception:
            pass

        # 策略2: role + name
        if not clicked_trigger:
            try:
                trigger = self.page.get_by_role("textbox", name=label_text)
                if trigger.count() > 0:
                    self._safe_click(trigger.first)
                    clicked_trigger = True
            except Exception:
                pass

        # 策略2b: 带 * 号
        if not clicked_trigger:
            try:
                trigger = self.page.get_by_role("textbox", name=f"* {label_text}")
                if trigger.count() > 0:
                    self._safe_click(trigger.first)
                    clicked_trigger = True
            except Exception:
                pass

        # 策略3: 回退到录制选择器
        if not clicked_trigger and fallback_selector:
            try:
                self._safe_click(self.page.locator(fallback_selector).first)
                clicked_trigger = True
            except Exception:
                pass

        if not clicked_trigger:
            if required:
                raise RuntimeError(f"smart_select 失败: 找不到字段 '{label_text}' 的下拉框")
            else:
                print(f"   ⚠️ smart_select[{label_text}]: 字段不存在，跳过")
                return

        # 等选项列表出现，然后选择
        print(f"   smart_select[{label_text}]: 触发器已点击，等待选项 '{option_text}' 出现...")
        # 先尝试精确匹配，再模糊匹配
        try:
            option = self.page.get_by_text(option_text, exact=True).first
            option.wait_for(state="visible", timeout=self.DROPDOWN_TIMEOUT)
            option.click()
            print(f"   smart_select[{label_text}]: 精确匹配选中 '{option_text}'")
        except Exception:
            try:
                option = self.page.get_by_text(option_text, exact=False).first
                option.wait_for(state="visible", timeout=self.DROPDOWN_TIMEOUT)
                option.click()
                print(f"   smart_select[{label_text}]: 模糊匹配选中 '{option_text}'")
            except Exception:
                # 打印当前可见的下拉选项，辅助排查
                try:
                    visible_opts = self.page.locator(
                        ".doraemon-select-dropdown:visible li, "
                        ".ant-select-dropdown:visible li, "
                        '[role="option"]:visible, '
                        '[role="menuitem"]:visible'
                    ).all()
                    opt_texts = []
                    for opt in visible_opts[:10]:
                        try:
                            t = opt.text_content(timeout=300).strip()
                            if t:
                                opt_texts.append(t)
                        except Exception:
                            pass
                    if opt_texts:
                        print(f"   📋 当前可见下拉选项: {opt_texts}")
                except Exception:
                    pass
                if required:
                    raise
                else:
                    print(f"   ⚠️ smart_select[{label_text}]: 选项 '{option_text}' 未出现，跳过")

    def smart_radio(self, label_text: str, option_text: str, required: bool = True):
        """通用单选 — 通过字段名定位单选组，选择指定选项

        规则: 如果选项已选中则跳过

        Args:
            label_text: 字段名（如"是否需要指标编码"）
            option_text: 选项文本（如"是""否"）
            required: True=字段必须存在(失败报错), False=字段可能不存在(失败跳过)
        """
        # 找到 label 对应的祖先区域（扩大搜索范围）
        label_area = None
        try:
            label = self.page.get_by_text(label_text, exact=False).first
            if label.count() > 0 and label.is_visible(timeout=1000):
                # 逐级向上，找到一个同时包含"是"和"否"文本的区域（即完整 radio 组容器）
                for level in range(1, 10):
                    area = label
                    for _ in range(level):
                        area = area.locator("..")
                    yes_text = area.get_by_text("是", exact=True)
                    no_text = area.get_by_text("否", exact=True)
                    if yes_text.count() > 0 and no_text.count() > 0:
                        label_area = area
                        print(f"   smart_radio[{label_text}]: 定位到 radio 组容器 (level={level})")
                        break
        except Exception:
            pass

        # 策略1: 在 label 祖先区域内找 radio role
        if label_area:
            try:
                radio = label_area.get_by_role("radio", name=option_text).first
                if radio.count() > 0 and radio.is_visible(timeout=500):
                    if not radio.is_checked():
                        self._safe_check(radio)
                        print(f"   smart_radio[{label_text}]: 策略1 选中 '{option_text}'")
                    else:
                        print(f"   ⏭️ smart_radio[{label_text}]: '{option_text}' 已选中，跳过")
                    return
            except Exception:
                pass
            # 策略1b: 区域内点击文本选项
            try:
                option = label_area.get_by_text(option_text, exact=True).first
                if option.count() > 0 and option.is_visible(timeout=500):
                    option.click()
                    print(f"   smart_radio[{label_text}]: 策略1b 点击 '{option_text}'")
                    return
            except Exception:
                pass

        # 策略2: 在 label 附近文本"是"/"否"中找最近的（非全局）
        if label_area is None:
            try:
                label = self.page.get_by_text(label_text, exact=False).first
                if label.count() > 0 and label.is_visible(timeout=1000):
                    # 用 label 的 bounding box 定位，找距离最近的"否"文本
                    label_box = label.bounding_box()
                    if label_box:
                        best_option = None
                        best_dist = float('inf')
                        for opt_text in [option_text]:
                            for opt_el in self.page.get_by_text(opt_text, exact=True).all():
                                try:
                                    if not opt_el.is_visible(timeout=300):
                                        continue
                                    opt_box = opt_el.bounding_box()
                                    if not opt_box:
                                        continue
                                    # 计算垂直距离（同一行或下一行）+ 水平距离
                                    dy = abs(opt_box["y"] - label_box["y"])
                                    dx = opt_box["x"] - label_box["x"]
                                    if dy < 50 and dx > 0:
                                        dist = dy + dx * 0.01
                                        if dist < best_dist:
                                            best_dist = dist
                                            best_option = opt_el
                                except Exception:
                                    continue
                        if best_option:
                            best_option.click()
                            print(f"   smart_radio[{label_text}]: 策略2 距离定位点击 '{option_text}'")
                            return
            except Exception:
                pass

        # 策略3: 全局 radio role（最后兜底，仅在 label 不存在时使用）
        try:
            radio = self.page.get_by_role("radio", name=option_text)
            if radio.count() > 0:
                self._safe_check(radio.first)
                print(f"   smart_radio[{label_text}]: 策略3 全局选中 '{option_text}'")
                return
        except Exception:
            pass

        if required:
            raise RuntimeError(f"smart_radio 失败: 找不到字段 '{label_text}' 的选项 '{option_text}'")
        else:
            print(f"   ⚠️ smart_radio[{label_text}]: 字段不存在，跳过")

    def check_by_label(self, label: str):
        """安全勾选复选框"""
        self._safe_check(self.page.get_by_label(label))

    def check_radio_by_text(self, text: str):
        """通过文本找单选按钮并勾选"""
        self._safe_check(self.page.get_by_role("radio", name=text))

    # ── 断言 ─────────────────────────────────────────────

    def assert_visible(self, text: str, timeout: int = None):
        """断言文本可见"""
        timeout = timeout or self.DEFAULT_TIMEOUT
        expect(self.page.get_by_text(text).first).to_be_visible(timeout=timeout)

    def assert_url_contains(self, url_part: str):
        """断言 URL 包含指定内容"""
        expect(self.page).to_have_url(re.compile(url_part))

    # ── 兼容接口（推荐用 _safe_* 系列）──────────

    def wait_for_selector(self, selector: str, timeout: int = 10000):
        """等待选择器出现"""
        self.page.wait_for_selector(selector, timeout=timeout)

    # ── 智能必填项填充 ────────────────────────────────────

    REQUIRED_FIELD_DEFAULTS = {
        "需求单名称": "自动测试需求单",
        "需求名称": "自动测试需求单",
        "联系人": "测试",
        "联系人姓名": "测试",
        "联系电话": "13800138000",
        "联系电话/手机": "13800138000",
        "手机号": "13800138000",
        "备注": "自动化测试",
        "说明": "自动化测试",
        "地址": "测试地址",
        "邮编": "310000",
        "数量": "1",
        "单价": "100",
        "金额": "100",
        "预算金额": "100",
        "预算金额(元)": "100",
        "本次预算金额(元)": "100",
        "项目号": "TEST001",
        "经费项目号": "1111YCS2233",
        "采购内容": "自动化测试采购内容",
        "采购目的": "自动化测试采购目的",
        "工程名称": "自动测试工程",
        "工号": "AUTO001",
        "需求单编号": "AUTO001",
        "需求单类型": "测试类型",
        "采购目录": "测试目录",
        "单位名称": "测试单位",
        "部门负责人": "测试",
        "是否需要指标编码": "否",
        "是否上报建议书": "否",
        "采购实施主体": "采购中心",
        "申请人部门": "采购部",
        "费用项名称": "测试费用项",
        "预算项名称": "测试预算项",
        "经费负责人": "测试",
    }

    def auto_fill_required_fields(self, filled_labels: set = None, value_overrides: dict = None):
        """扫描页面所有必填字段（带 * 标记），自动填充未填的字段

        优先用 doraemon form-item 结构（label + control-wrapper 同级），
        回退到 label/span 全局扫描。
        """
        if filled_labels is None:
            filled_labels = set()
        if value_overrides is None:
            value_overrides = {}
        self._value_overrides = value_overrides

        """策略1: doraemon form-item 结构扫描（只填必填项）
        优先用 .doraemon-form-item-required class 识别必填（伪元素星号不在 text_content 里）
        兜底用文本 * 匹配"""
        required_label_els = []
        # 方式1: 通过 required class 定位（只取可见的）
        for el in self.page.locator(".doraemon-form-item-required").all():
            try:
                if not el.is_visible():
                    continue
            except Exception:
                continue
            parent_row = el.locator("xpath=ancestor::*[contains(@class,'doraemon-row')][1]")
            label_in_row = parent_row.locator(".doraemon-form-item-label").first
            if label_in_row.count() > 0:
                required_label_els.append(label_in_row)
        # 方式2: 文本包含 * 的（兼容，只取可见的）
        for el in self.page.locator(".doraemon-form-item-label").all():
            try:
                text = el.text_content(timeout=300).strip()
                if text and "*" in text and el not in required_label_els:
                    required_label_els.append(el)
            except Exception:
                continue

        scan_count = 0
        required_found = []
        for label_el in required_label_els:
            try:
                label_text = label_el.text_content(timeout=300).strip()
                if not label_text:
                    continue
                clean_label = label_text.replace("*", "").strip()
                if not clean_label:
                    continue
                required_found.append(clean_label)
                if clean_label in filled_labels:
                    continue
                scan_count += 1
                # 用 doraemon 结构判断是否已填
                is_filled = self._is_field_filled_by_form_item(label_el, clean_label)
                if is_filled:
                    print(f"   ✅ auto_fill 已填: {clean_label}")
                    continue
                # 未填，尝试填充
                print(f"   🔍 auto_fill 发现未填: {clean_label}")
                self._try_fill_by_form_item(label_el, clean_label)
            except Exception:
                continue
        print(f"   📋 页面必填字段: {required_found}")
        print(f"   📋 已处理字段: {filled_labels}")
        if scan_count > 0:
            print(f"   📋 auto_fill 新发现 {scan_count} 个未填必填项")

        # 策略2: 兜底 — 扫描 label 和 span（兼容非 doraemon 表单）
        all_label_els = []
        for el in self.page.locator("label").all():
            all_label_els.append(el)
        for el in self.page.locator("span.doraemon-form-item-label").all():
            if el not in all_label_els:
                all_label_els.append(el)
        for label_el in all_label_els:
            try:
                label_text = label_el.text_content(timeout=300).strip()
                if not label_text or "*" not in label_text:
                    continue
                clean_label = label_text.replace("*", "").strip()
                if not clean_label or clean_label in filled_labels:
                    continue
                if self._is_field_filled(label_el):
                    continue
                self._try_fill_field(label_el, clean_label)
            except Exception:
                continue

    def _find_control_wrapper(self, label_el):
        """从 label 元素出发，找到 control-wrapper

        优先用 doraemon-form-item 祖先，兜底逐级向上（限制 3 级）
        """
        # 策略1: 最近的 doraemon-form-item 祖先
        fi = label_el.locator("xpath=ancestor::*[contains(@class,'doraemon-form-item')][1]")
        if fi.count() > 0:
            c = fi.locator(".doraemon-form-item-control-wrapper").first
            if c.count() > 0:
                # 调试：打印 control-wrapper 中的 input 信息
                try:
                    inputs_in_c = c.locator("input, textarea").all()
                    inp_ids = []
                    for inp in inputs_in_c:
                        iid = inp.get_attribute("id") or ""
                        inp_ids.append(iid)
                    label_txt = label_el.text_content(timeout=300).strip() if label_el.count() > 0 else ""
                    print(f"   🏗️ [{label_text}] form-item 匹配到 control-wrapper, inputs={inp_ids}")
                except Exception:
                    pass
                return c
        # 策略2: 逐级向上（限制 3 级）
        for level in range(1, 4):
            parent = label_el
            for _ in range(level):
                parent = parent.locator("..")
            c = parent.locator(".doraemon-form-item-control-wrapper").first
            if c.count() > 0:
                return c
        return None

    def _find_best_input_in_control(self, control, label_text: str):
        """在 control-wrapper 中找到最匹配 label_text 的 input

        如果有多个 input，优先选 id/name 包含关键字匹配的；否则选第一个
        """
        all_inputs = control.locator("input:visible, textarea:visible").all()
        if len(all_inputs) <= 1:
            return control.locator("input:visible, textarea:visible").first
        # 多个 input 时，尝试用 label 关键字匹配 id/name
        label_keywords = {
            "需求单名称": "projectName", "需求单编号": "demandNo",
            "联系人姓名": "contactName", "联系电话": "contactPhone",
            "工号": "contactSchoolNo", "单位名称": "contactOrgName",
            "领用人": "recipient", "采购内容": "purchaseContent",
            "申购理由": "purchasePurpose", "时间要求": "times",
        }
        keyword = label_keywords.get(label_text)
        if keyword:
            for inp in all_inputs:
                try:
                    inp_id = inp.get_attribute("id") or ""
                    if keyword in inp_id:
                        return inp
                except Exception:
                    pass
        # 兜底：返回第一个可见 input
        return control.locator("input:visible, textarea:visible").first

    def _find_input_by_label(self, label_text: str):
        """直接通过 input ID 匹配 label，绕过 control-wrapper 遍历

        返回匹配的 input locator，找不到返回 None
        """
        label_to_id = {
            "需求单名称": "demandPurchase.projectName",
            "需求单编号": "demandPurchase.demandNo",
            "联系人姓名": "demandBase.contactName",
            "联系电话": "demandBase.contactPhone",
            "工号": "demandBase.contactSchoolNo",
            "单位名称": "demandBase.contactOrgName",
            "领用人": "demandBase.recipient",
            "采购内容": "demandPurchase.purchaseContent",
            "申购理由": "demandPurchase.purchasePurpose",
            "时间要求": "demandPurchase.times",
            "本次预算金额 (元)": "amount",
            "经费项目号": "costId",
        }
        inp_id = label_to_id.get(label_text)
        if inp_id:
            el = self.page.locator(f'[id="{inp_id}"]').first
            if el.count() > 0:
                return el
        return None

    def _is_field_filled_by_form_item(self, label_el, label_text: str = "") -> bool:
        """基于 doraemon form-item 结构判断字段是否已有值"""
        try:
            # 优先：直接通过 input ID 匹配
            inp = self._find_input_by_label(label_text)
            if inp is not None and inp.count() > 0:
                try:
                    val = inp.input_value(timeout=300)
                    if val and val.strip() and val.strip() != "请选择":
                        return True
                except Exception:
                    pass
                # ID 匹配到了但值为空，直接返回 False（不走 control-wrapper）
                return False

            # 兜底：control-wrapper 遍历
            control = self._find_control_wrapper(label_el)
            if control is None:
                return False

            # 检查 input/textarea
            try:
                inp = self._find_best_input_in_control(control, label_text)
                if inp.count() > 0:
                    val = inp.input_value(timeout=300)
                    # 调试：打印检测到的 input 信息
                    try:
                        inp_id = inp.get_attribute("id") or ""
                        inp_placeholder = inp.get_attribute("placeholder") or ""
                        print(f"   🔍 [{label_text}] 检测 input id={inp_id} placeholder={inp_placeholder} val='{val}'")
                    except Exception:
                        pass
                    if val and val.strip() and val.strip() != "请选择":
                        print(f"   🔍 [{label_text}] 检测到已填 input id={inp_id} val='{val}'")
                        return True
            except Exception:
                pass
            # 检查 select 已选值
            try:
                sel = control.locator(
                    ".doraemon-select-selection-selected-value"
                ).first
                if sel.count() > 0:
                    val = sel.text_content(timeout=300).strip()
                    if val and val != "请选择":
                        return True
            except Exception:
                pass
            # 检查 cascader 已选值
            try:
                cas = control.locator(
                    ".doraemon-cascader-picker-label"
                ).first
                if cas.count() > 0:
                    val = cas.text_content(timeout=300).strip()
                    if val and val != "请选择" and val != "请选择 /":
                        return True
            except Exception:
                pass
            # 检查 radio 已选
            try:
                radio = control.locator("input[type='radio']:checked").first
                if radio.count() > 0:
                    return True
            except Exception:
                pass
        except Exception:
            pass
        return False

    def _try_fill_by_form_item(self, label_el, label_text: str):
        """基于 doraemon form-item 结构填充字段"""
        try:
            # 优先：直接通过 input ID 匹配
            inp = self._find_input_by_label(label_text)
            if inp is not None and inp.count() > 0:
                try:
                    val = inp.input_value(timeout=300)
                    if val and val.strip():
                        return  # 已有值
                    fill_value = self._get_default_value(label_text)
                    self._safe_fill(inp, fill_value)
                    print(f"   ✅ 自动填充必填项(ID匹配): {label_text} = {fill_value}")
                    return
                except Exception:
                    pass

            # 兜底：control-wrapper 遍历
            control = self._find_control_wrapper(label_el)
            if control is None:
                print(f"   ⚠️ auto_fill: {label_text} 未找到 control-wrapper，跳过")
                return

            # 调试: 看 control 内子元素
            if label_text in ["采购内容", "采购目的", "联系电话", "工号"]:
                try:
                    ta_count = control.locator("textarea").count()
                    inp_count = control.locator("input").count()
                    sel_count = control.locator(".doraemon-select-selection").count()
                    cas_count = control.locator(".doraemon-cascader-input").count()
                    radio_count = control.locator("input[type='radio']").count()
                    print(f"   🔧 {label_text}: textarea={ta_count} input={inp_count} select={sel_count} cascader={cas_count} radio={radio_count}")
                except Exception:
                    pass

            # 策略1: textarea（优先，因为"采购内容"等大文本框）
            textarea = control.locator("textarea").first
            if textarea.count() > 0:
                try:
                    val = textarea.input_value(timeout=300)
                    if val and val.strip():
                        return  # 已有值
                    fill_value = self._get_default_value(label_text)
                    self._safe_fill(textarea, fill_value)
                    print(f"   ✅ 自动填充必填项(textarea): {label_text} = {fill_value}")
                    return
                except Exception:
                    pass

            # 策略2: input textbox
            textbox = self._find_best_input_in_control(control, label_text)
            if textbox.count() > 0:
                try:
                    val = textbox.input_value(timeout=300)
                    # 调试：打印 input 的 id/name/value
                    try:
                        inp_id = textbox.get_attribute("id") or ""
                        inp_name = textbox.get_attribute("name") or ""
                        print(f"   🔧 [{label_text}] 匹配到 input id={inp_id} name={inp_name} val='{val}'")
                    except Exception:
                        pass
                    if val and val.strip() and val.strip() != "请选择":
                        return  # 已有值
                    fill_value = self._get_default_value(label_text)
                    self._safe_fill(textbox, fill_value)
                    print(f"   ✅ 自动填充必填项(input): {label_text} = {fill_value}")
                    return
                except Exception:
                    pass

            # 策略3: select 下拉 — 用默认值匹配选项
            trigger = control.locator(
                ".doraemon-select-selection:visible"
            ).first
            if trigger.count() > 0:
                try:
                    default_val = self._get_default_value(label_text)
                    self._safe_click(trigger)
                    # 等待下拉菜单出现
                    self.page.wait_for_timeout(300)
                    # 尝试匹配默认值
                    opt = self.page.locator(
                        f".doraemon-select-dropdown:visible li:has-text('{default_val}')"
                    ).first
                    if opt.count() > 0 and opt.is_visible():
                        opt.click()
                        print(f"   ✅ 自动选择必填项(select): {label_text} = {default_val}")
                        return
                    # 没匹配到默认值，选第一个
                    first_opt = self.page.locator(
                        ".doraemon-select-dropdown:visible li:first-child"
                    ).first
                    if first_opt.is_visible():
                        first_opt.click()
                        first_text = first_opt.text_content(timeout=300).strip()
                        print(f"   ✅ 自动选择必填项(select): {label_text} = {first_text}")
                        return
                except Exception:
                    pass

            # 策略4: cascader 级联
            cas = control.locator(
                ".doraemon-cascader-input:visible"
            ).first
            if cas.count() > 0:
                try:
                    self._safe_click(cas)
                    first_opt = self.page.locator(
                        ".doraemon-cascader-menu:first-child .doraemon-cascader-menu-item:first-child"
                    ).first
                    first_opt.wait_for(state="visible", timeout=self.DROPDOWN_TIMEOUT)
                    first_opt.click()
                    print(f"   ✅ 自动选择必填项(cascader): {label_text} = 第一个选项")
                    return
                except Exception:
                    pass

            # 策略5: radio — 用默认值匹配选项文本
            default_val = self._get_default_value(label_text)
            radios = control.locator("input[type='radio']").all()
            if radios:
                try:
                    # 先检查是否已选
                    for r in radios:
                        if r.is_checked():
                            return
                    # 尝试匹配默认值对应的 radio
                    # radio 的 label 文本在父级或相邻元素中
                    for r in radios:
                        try:
                            parent = r.locator("xpath=..")
                            text = parent.text_content(timeout=300).strip()
                            if default_val in text:
                                r.click()
                                print(f"   ✅ 自动选择必填项(radio): {label_text} = {default_val}")
                                return
                        except Exception:
                            continue
                    # 没匹配到默认值，选第一个未选的
                    for r in radios:
                        try:
                            if not r.is_checked():
                                parent = r.locator("xpath=..")
                                text = parent.text_content(timeout=300).strip()
                                r.click()
                                print(f"   ✅ 自动选择必填项(radio): {label_text} = {text}")
                                return
                        except Exception:
                            continue
                except Exception:
                    pass

            # 策略6: 兜底 — 任何可见 input
            any_input = control.locator("input:visible").first
            if any_input.count() > 0:
                try:
                    val = any_input.input_value(timeout=300)
                    if val and val.strip() and val.strip() != "请选择":
                        return
                    fill_value = self._get_default_value(label_text)
                    self._safe_fill(any_input, fill_value)
                    print(f"   ✅ 自动填充必填项(any_input): {label_text} = {fill_value}")
                    return
                except Exception:
                    pass

            # 策略7: 最终兜底 — 用 smart_fill
            try:
                fill_value = self._get_default_value(label_text)
                self.smart_fill(label_text, fill_value, required=False)
                print(f"   ✅ 自动填充必填项(smart_fill): {label_text} = {fill_value}")
            except Exception as e:
                print(f"   ⚠️ auto_fill 无法填充: {label_text} ({e})")
        except Exception:
            pass

    def _is_field_filled(self, label_el) -> bool:
        """检查 label 对应的字段是否已有值（扩大搜索层级到 8 层）"""
        # 逐级向上搜索，找到包含有效值的区域就返回 True
        for level in range(1, 9):
            area = label_el
            for _ in range(level):
                area = area.locator("..")
            # 检查 input
            try:
                textbox = area.locator(
                    "input[type='text'], input:not([type]), textarea"
                ).first
                if textbox.count() > 0 and textbox.is_visible(timeout=300):
                    val = textbox.input_value(timeout=300)
                    if val and val.strip():
                        return True
            except Exception:
                pass
            # 检查下拉已有值
            try:
                selected = area.locator(
                    ".doraemon-select-selection-selected-value, .ant-select-selection-selected-value"
                ).first
                if selected.count() > 0:
                    val = selected.text_content(timeout=300).strip()
                    if val and val != "请选择":
                        return True
            except Exception:
                pass
        return False

    def _try_fill_field(self, label_el, label_text: str):
        """尝试智能填充单个必填字段（扩大搜索层级到 8 层）"""
        # 逐级向上搜索，找到可操作的表单控件
        for level in range(1, 9):
            area = label_el
            for _ in range(level):
                area = area.locator("..")

            # 策略1: textbox
            textbox = area.locator("input[type='text'], input:not([type]), textarea").first
            try:
                if textbox.count() > 0 and textbox.is_visible(timeout=300):
                    current_val = textbox.input_value(timeout=300)
                    if current_val:
                        return  # 已有值，跳过
                    fill_value = self._get_default_value(label_text)
                    self._safe_fill(textbox, fill_value)
                    print(f"   ✅ 自动填充必填项: {label_text} = {fill_value}")
                    return
            except Exception:
                pass

            # 策略2: dropdown
            dropdown = area.locator(
                ".doraemon-select, .ant-select, .el-select, select"
            ).first
            try:
                if dropdown.count() > 0 and dropdown.is_visible(timeout=300):
                    dropdown.click(timeout=1000)
                    first_option = self.page.locator(
                        ".doraemon-select-dropdown-menu-item:first-child, "
                        ".ant-select-dropdown-menu-item:first-child, "
                        ".el-select-dropdown__item:first-child, "
                        "option:not([disabled]):not([value='']):first-child"
                    ).first
                    first_option.wait_for(state="visible", timeout=self.DROPDOWN_TIMEOUT)
                    if first_option.count() > 0:
                        first_option.click(timeout=1000)
                        print(f"   ✅ 自动选择必填项: {label_text} = 第一个选项")
                    return
            except Exception:
                pass

            # 策略3: radio
            radio = area.locator("input[type='radio']").first
            try:
                if radio.count() > 0 and radio.is_visible(timeout=300):
                    if not radio.is_checked():
                        radio.click(timeout=1000)
                        print(f"   ✅ 自动选择必填项: {label_text} = 第一个选项")
                    return
            except Exception:
                pass

    def _get_default_value(self, label_text: str) -> str:
        """根据字段标签推断默认填充值"""
        # 优先用外部传入的值覆盖
        overrides = getattr(self, '_value_overrides', {})
        if label_text in overrides:
            return overrides[label_text]
        for key, val in self.REQUIRED_FIELD_DEFAULTS.items():
            if key == label_text:
                return val
        keyword_map = {
            "名称": "自动测试", "联系": "测试", "电话": "13800138000",
            "手机": "13800138000", "地址": "测试地址", "备注": "自动化测试",
            "说明": "自动化测试", "数量": "1", "金额": "100",
            "项目号": "TEST001", "编号": "AUTO001", "日期": "2026",
        }
        for keyword, default_val in keyword_map.items():
            if keyword in label_text:
                return default_val
        return "测试数据"
