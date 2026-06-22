#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
self_healing/locator_error.py — 定位错误异常与装饰器（全局通用）

所有 Page 类的 _safe_* 方法通过 @capture_locator_error 装饰器
自动捕获 Playwright 定位异常，包装为 LocatorActionError。
conftest.py 的 hook 会采集此异常写入 JSON 报告供 heal_runner 使用。

用法:
    from self_healing.locator_error import capture_locator_error, LocatorActionError

    class MyPage(BasePage):
        @capture_locator_error(action="click")
        def _safe_click(self, locator, timeout=None):
            ...
"""

import functools


class LocatorActionError(Exception):
    """定位操作失败异常 — 包含结构化信息，供自愈模块解析

    Attributes:
        action: 操作类型 (click/fill/check/select/wait)
        selector: 失效的选择器字符串
        page_url: 出错时的页面 URL
        original_error: Playwright 原始异常
        description: 选择器描述（可选）
    """

    def __init__(self, action, selector, page_url, original_error, description=""):
        self.action = action
        self.selector = selector
        self.page_url = page_url
        self.original_error = original_error
        self.description = description
        self.strict_violation_message: str = ""  # Playwright strict violation 原始错误文本
        msg = (
            f"[{action}] selector={selector!r} "
            f"url={page_url!r}"
        )
        if description:
            msg += f" desc={description!r}"
        msg += f" | {type(original_error).__name__}: {str(original_error)[:200]}"
        super().__init__(msg)


def _extract_selector_from_locator(locator) -> str:
    """从 Playwright Locator 对象提取选择器字符串"""
    # Locator 内部有 _selector 属性（Playwright sync API）
    for attr in ("_selector", "_impl_obj"):
        obj = getattr(locator, attr, None)
        if obj is not None:
            sel = getattr(obj, "_selector", None) or getattr(obj, "selector", None)
            if sel:
                return str(sel)
    # 对于 .first / .nth() 等链式调用，_selector 在内部
    try:
        s = str(locator)
        if "locator(" in s or "get_by_" in s:
            return s
    except Exception:
        pass
    return ""


def capture_locator_error(action: str):
    """装饰器：捕获 Playwright 定位异常，包装为 LocatorActionError

    用法:
        @capture_locator_error(action="click")
        def _safe_click(self, locator, timeout=None):
            ...

    装饰器会:
      1. 成功时直接返回，零开销
      2. 失败时提取 selector + page_url，包装成 LocatorActionError 抛出
      3. conftest.py 的 hook 会捕获此异常写入 JSON 报告
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, locator, *args, **kwargs):
            try:
                return func(self, locator, *args, **kwargs)
            except LocatorActionError:
                raise  # 已经是 LocatorActionError，不再包装
            except Exception as e:
                selector = _extract_selector_from_locator(locator)
                page_url = ""
                # 安全获取 page URL
                page = getattr(self, 'page', None)
                if page:
                    try:
                        page_url = getattr(page, 'url', '') or ""
                    except Exception:
                        pass
                raise LocatorActionError(
                    action=action,
                    selector=selector,
                    page_url=page_url,
                    original_error=e,
                ) from e
        return wrapper
    return decorator
