"""MonkeyPatchPage — 全局错误捕获层

独创性：通过 monkey-patch 机制将 Playwright 原生 page 对象的定位方法
替换为自愈感知版本，使录制生成的 raw Playwright API 调用也能被统一
捕获为结构化 LocatorActionError，无需修改业务代码。

设计要点：
- HealingLocator 维护完整的链式选择器字符串和 SelectorExpr 结构
- 终端操作失败时自动包装为 LocatorActionError
- 非终端操作（链式方法）返回新的 HealingLocator，延迟执行
- _resolve_real_locator() 在终端操作时才实际调用 Playwright 定位
"""
from __future__ import annotations

import functools
from typing import Any, Optional

from playwright.sync_api import Page, Locator, FrameLocator

from core.locator_error import LocatorActionError, _extract_selector_from_locator
from self_healing.selector_parser import parse_selector, SelectorExpr, MethodCall


# 终端操作集合 — 这些操作失败时需要捕获
_TERMINAL_ACTIONS = {
    "click", "fill", "check", "uncheck", "type", "press",
    "select_option", "set_input_files", "hover", "focus",
    "blur", "tap", "dispatch_event", "wait_for",
}

# 需要拦截的定位方法
_LOCATOR_METHODS = {
    "get_by_role", "get_by_text", "get_by_label",
    "get_by_test_id", "get_by_placeholder", "get_by_alt_text",
    "get_by_title", "locator",
}

# 链式过滤方法 — 返回新 Locator
_CHAIN_METHODS = {
    "nth", "first", "last", "filter", "and_", "or_",
}


class HealingLocator:
    """自愈感知的 Locator 包装器

    核心功能：
    1. 维护完整的链式选择器字符串（如 get_by_role("textbox", name="请输入").nth(1)）
    2. 拦截终端操作失败时，自动包装为 LocatorActionError
    3. 携带 page_url 上下文
    """

    def __init__(self, original_locator: Optional[Locator], page: Page, selector_expr: SelectorExpr):
        # 不存储 original_locator 以避免已被销毁的 locator
        self._page = page
        self._selector_expr = selector_expr
        self._selector_str = selector_expr.to_string()

    def __repr__(self) -> str:
        return f"HealingLocator({self._selector_str})"

    def __str__(self) -> str:
        return self._selector_str

    @property
    def selector_str(self) -> str:
        """返回完整的选择器字符串"""
        return self._selector_str

    @property
    def selector_expr(self) -> SelectorExpr:
        """返回结构化的选择器表达式"""
        return self._selector_expr

    # ---- 链式方法（返回新的 HealingLocator）----

    def nth(self, index: int) -> "HealingLocator":
        """返回第 N 个匹配元素的 HealingLocator"""
        new_calls = list(self._selector_expr.calls) + [MethodCall(method="nth", args=[index])]
        return HealingLocator(
            original_locator=None,
            page=self._page,
            selector_expr=SelectorExpr(calls=new_calls),
        )

    @property
    def first(self) -> "HealingLocator":
        """返回第一个匹配元素的 HealingLocator"""
        new_calls = list(self._selector_expr.calls) + [MethodCall(method="first")]
        return HealingLocator(
            original_locator=None,
            page=self._page,
            selector_expr=SelectorExpr(calls=new_calls),
        )

    @property
    def last(self) -> "HealingLocator":
        """返回最后一个匹配元素的 HealingLocator"""
        new_calls = list(self._selector_expr.calls) + [MethodCall(method="last")]
        return HealingLocator(
            original_locator=None,
            page=self._page,
            selector_expr=SelectorExpr(calls=new_calls),
        )

    def filter(self, *, has_text: str = None, has: Any = None) -> "HealingLocator":
        """返回过滤后的 HealingLocator"""
        kwargs: dict[str, Any] = {}
        if has_text is not None:
            kwargs["has_text"] = has_text
        if has is not None:
            kwargs["has"] = str(has)  # 简化处理，将 Locator 转为字符串
        new_calls = list(self._selector_expr.calls) + [MethodCall(method="filter", kwargs=kwargs)]
        return HealingLocator(
            original_locator=None,
            page=self._page,
            selector_expr=SelectorExpr(calls=new_calls),
        )

    def and_(self, locator: Any) -> "HealingLocator":
        """返回交集 HealingLocator"""
        new_calls = list(self._selector_expr.calls) + [MethodCall(method="and_", args=[str(locator)])]
        return HealingLocator(
            original_locator=None,
            page=self._page,
            selector_expr=SelectorExpr(calls=new_calls),
        )

    def or_(self, locator: Any) -> "HealingLocator":
        """返回并集 HealingLocator"""
        new_calls = list(self._selector_expr.calls) + [MethodCall(method="or_", args=[str(locator)])]
        return HealingLocator(
            original_locator=None,
            page=self._page,
            selector_expr=SelectorExpr(calls=new_calls),
        )

    # ---- 真实定位器解析 ----

    def _resolve_real_locator(self) -> Locator:
        """将 selector_expr 解析回真实的 Playwright Locator 并返回

        逐步构建原始 Locator：
        1. 第一层调用使用 page 的定位方法
        2. 后续链式方法使用上一层的 Locator 结果
        """
        result: Optional[Locator] = None
        page = self._page

        for call in self._selector_expr.calls:
            method = call.method
            args = call.args
            kwargs = call.kwargs

            if method in _LOCATOR_METHODS:
                fn = getattr(page, method)
                result = fn(*args, **kwargs)
            elif method == "nth":
                if result is not None:
                    result = result.nth(*args)
            elif method == "first":
                if result is not None:
                    result = result.first
            elif method == "last":
                if result is not None:
                    result = result.last
            elif method == "filter":
                # 过滤掉 has 参数（Locator 类型不好序列化）
                clean_kwargs = {k: v for k, v in kwargs.items() if k != "has"}
                if result is not None:
                    result = result.filter(**clean_kwargs)
            elif method == "and_":
                # 简化处理：尝试用选择器字符串创建 Locator
                if result is not None and args:
                    other = page.locator(str(args[0]))
                    result = result.and_(other)
            elif method == "or_":
                if result is not None and args:
                    other = page.locator(str(args[0]))
                    result = result.or_(other)
            elif method == "__replaced__":
                # replace_base() 生成的方法，用第一个 arg 作为 CSS 选择器
                if args:
                    result = page.locator(str(args[0]))

        if result is None:
            raise RuntimeError(f"无法解析 HealingLocator: {self._selector_str}")

        return result

    # ---- 终端操作（拦截异常，包装为 LocatorActionError）----

    def __getattr__(self, name: str) -> Any:
        """拦截终端操作和其他未定义的方法调用"""
        if name in _TERMINAL_ACTIONS:
            def wrapped_action(*args, **kwargs):
                locator = self._resolve_real_locator()
                action = getattr(locator, name)
                try:
                    return action(*args, **kwargs)
                except LocatorActionError:
                    raise
                except Exception as e:
                    page_url = ""
                    try:
                        page_url = self._page.url or ""
                    except Exception:
                        pass
                    error = LocatorActionError(
                        action=name,
                        selector=self._selector_str,
                        page_url=page_url,
                        original_error=e,
                    )
                    # L0: 附带 strict violation 原始错误文本
                    error_message = str(e)
                    if "strict mode violation" in error_message.lower():
                        error.strict_violation_message = error_message
                    raise error from e
            return wrapped_action

        # 非终端操作，直接委托给真实 Locator
        locator = self._resolve_real_locator()
        return getattr(locator, name)

    # ---- 常用的非终端查询方法委托 ----

    def count(self) -> int:
        """返回匹配元素数量"""
        locator = self._resolve_real_locator()
        return locator.count()

    def is_visible(self) -> bool:
        """返回元素是否可见"""
        locator = self._resolve_real_locator()
        return locator.is_visible()

    def is_enabled(self) -> bool:
        """返回元素是否可用"""
        locator = self._resolve_real_locator()
        return locator.is_enabled()

    def is_disabled(self) -> bool:
        """返回元素是否禁用"""
        locator = self._resolve_real_locator()
        return locator.is_disabled()

    def is_checked(self) -> bool:
        """返回复选框是否选中"""
        locator = self._resolve_real_locator()
        return locator.is_checked()

    def is_hidden(self) -> bool:
        """返回元素是否隐藏"""
        locator = self._resolve_real_locator()
        return locator.is_hidden()

    def inner_text(self) -> str:
        """返回元素内部文本"""
        locator = self._resolve_real_locator()
        return locator.inner_text()

    def inner_html(self) -> str:
        """返回元素内部 HTML"""
        locator = self._resolve_real_locator()
        return locator.inner_html()

    def input_value(self) -> str:
        """返回输入框的值"""
        locator = self._resolve_real_locator()
        return locator.input_value()

    def text_content(self) -> str:
        """返回元素文本内容"""
        locator = self._resolve_real_locator()
        return locator.text_content()

    def get_attribute(self, name: str) -> Optional[str]:
        """返回元素属性值"""
        locator = self._resolve_real_locator()
        return locator.get_attribute(name)

    def scroll_into_view_if_needed(self) -> None:
        """滚动到元素可见位置"""
        locator = self._resolve_real_locator()
        return locator.scroll_into_view_if_needed()

    def wait_for(self, state: str = "visible", **kwargs) -> None:
        """等待元素达到指定状态（终端操作）"""
        locator = self._resolve_real_locator()
        try:
            return locator.wait_for(state=state, **kwargs)
        except LocatorActionError:
            raise
        except Exception as e:
            page_url = ""
            try:
                page_url = self._page.url or ""
            except Exception:
                pass
            error = LocatorActionError(
                action="wait_for",
                selector=self._selector_str,
                page_url=page_url,
                original_error=e,
            )
            # L0: 附带 strict violation 原始错误文本
            error_message = str(e)
            if "strict mode violation" in error_message.lower():
                error.strict_violation_message = error_message
            raise error from e

    def highlight(self) -> None:
        """高亮元素（调试用）"""
        locator = self._resolve_real_locator()
        return locator.highlight()

    def screenshot(self, **kwargs) -> bytes:
        """截取元素截图"""
        locator = self._resolve_real_locator()
        return locator.screenshot(**kwargs)

    def bounding_box(self) -> Optional[dict]:
        """返回元素边界框"""
        locator = self._resolve_real_locator()
        return locator.bounding_box()


class MonkeyPatchPage:
    """全局错误捕获层 — 对 Playwright Page 对象进行 monkey-patch

    拦截所有定位方法（get_by_role/get_by_text/locator等），
    返回 HealingLocator 而非原始 Locator，
    使录制生成的 raw Playwright API 调用也能被统一捕获。

    用法:
        from self_healing.monkey_patch_page import MonkeyPatchPage

        # 在 fixture 中包装
        healing_page = MonkeyPatchPage(page)
        locator = healing_page.get_by_role("textbox", name="用户名")
        locator.fill("admin")  # 失败时抛出 LocatorActionError
    """

    def __init__(self, page: Page):
        self._page = page

    def __getattr__(self, name: str) -> Any:
        # 拦截定位方法
        if name in _LOCATOR_METHODS:
            @functools.wraps(getattr(self._page, name))
            def create_healing_locator(*args, **kwargs):
                # 构建初始 SelectorExpr
                method_call = MethodCall(method=name, args=list(args), kwargs=kwargs)
                expr = SelectorExpr(calls=[method_call])
                return HealingLocator(
                    original_locator=None,
                    page=self._page,
                    selector_expr=expr,
                )
            return create_healing_locator

        # 其他属性和方法直接委托给原始 page
        return getattr(self._page, name)

    # ---- 显式代理常用 Page 属性和方法 ----

    @property
    def url(self) -> str:
        """当前页面 URL"""
        return self._page.url

    def goto(self, url: str, **kwargs) -> Any:
        """导航到指定 URL"""
        return self._page.goto(url, **kwargs)

    def wait_for_load_state(self, state: str = "load", **kwargs) -> None:
        """等待页面加载状态"""
        return self._page.wait_for_load_state(state, **kwargs)

    def screenshot(self, **kwargs) -> bytes:
        """截取页面截图"""
        return self._page.screenshot(**kwargs)

    def on(self, event: str, handler: Any) -> None:
        """注册页面事件处理器"""
        return self._page.on(event, handler)

    def frame_locator(self, selector: str) -> FrameLocator:
        """返回 Frame 定位器"""
        return self._page.frame_locator(selector)

    @property
    def context(self) -> Any:
        """返回浏览器上下文"""
        return self._page.context

    def close(self, **kwargs) -> None:
        """关闭页面"""
        return self._page.close(**kwargs)

    def wait_for_url(self, url: Optional[str] = None, **kwargs) -> None:
        """等待页面 URL 变化"""
        return self._page.wait_for_url(url, **kwargs)

    def reload(self, **kwargs) -> Any:
        """重新加载页面"""
        return self._page.reload(**kwargs)

    def evaluate(self, expression: str, arg: Any = None) -> Any:
        """在页面中执行 JavaScript"""
        return self._page.evaluate(expression, arg)

    def set_viewport_size(self, size: dict) -> None:
        """设置视口大小"""
        return self._page.set_viewport_size(size)

    def title(self) -> str:
        """返回页面标题"""
        return self._page.title()

    def wait_for_timeout(self, timeout: float) -> None:
        """等待指定毫秒数"""
        return self._page.wait_for_timeout(timeout)

    def expect(self) -> Any:
        """返回 PageAssertions 对象"""
        return self._page.expect()

    def bring_to_front(self) -> None:
        """将页面置于前台"""
        return self._page.bring_to_front()

    def go_back(self, **kwargs) -> Any:
        """返回上一页"""
        return self._page.go_back(**kwargs)

    def go_forward(self, **kwargs) -> Any:
        """前进到下一页"""
        return self._page.go_forward(**kwargs)

    @property
    def raw_page(self) -> Page:
        """获取被包装的原始 Page 对象（兼容已有代码）"""
        return self._page
