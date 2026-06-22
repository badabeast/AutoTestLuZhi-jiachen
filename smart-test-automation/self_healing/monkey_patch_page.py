"""MonkeyPatchPage 包装 Playwright Page，让原生API调用自动捕获为 LocatorActionError。
拦截定位方法返回 HealingLocator，终端操作失败时包装异常。"""
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
    """自愈感知 Locator，维护链式选择器字符串，终端操作失败时抛 LocatorActionError"""

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
        return self._selector_str

    @property
    def selector_expr(self) -> SelectorExpr:
        return self._selector_expr

    # ---- 链式方法（返回新的 HealingLocator）----

    def nth(self, index: int) -> "HealingLocator":
        new_calls = list(self._selector_expr.calls) + [MethodCall(method="nth", args=[index])]
        return HealingLocator(
            original_locator=None,
            page=self._page,
            selector_expr=SelectorExpr(calls=new_calls),
        )

    @property
    def first(self) -> "HealingLocator":
        new_calls = list(self._selector_expr.calls) + [MethodCall(method="first")]
        return HealingLocator(
            original_locator=None,
            page=self._page,
            selector_expr=SelectorExpr(calls=new_calls),
        )

    @property
    def last(self) -> "HealingLocator":
        new_calls = list(self._selector_expr.calls) + [MethodCall(method="last")]
        return HealingLocator(
            original_locator=None,
            page=self._page,
            selector_expr=SelectorExpr(calls=new_calls),
        )

    def filter(self, *, has_text: str = None, has: Any = None) -> "HealingLocator":
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
        new_calls = list(self._selector_expr.calls) + [MethodCall(method="and_", args=[str(locator)])]
        return HealingLocator(
            original_locator=None,
            page=self._page,
            selector_expr=SelectorExpr(calls=new_calls),
        )

    def or_(self, locator: Any) -> "HealingLocator":
        new_calls = list(self._selector_expr.calls) + [MethodCall(method="or_", args=[str(locator)])]
        return HealingLocator(
            original_locator=None,
            page=self._page,
            selector_expr=SelectorExpr(calls=new_calls),
        )

    # ---- 真实定位器解析 ----

    def _resolve_real_locator(self) -> Locator:
        """将 selector_expr 解析回真实的 Playwright Locator"""
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
                    # 保留 strict violation 原始错误文本
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
        locator = self._resolve_real_locator()
        return locator.count()

    def is_visible(self) -> bool:
        locator = self._resolve_real_locator()
        return locator.is_visible()

    def is_enabled(self) -> bool:
        locator = self._resolve_real_locator()
        return locator.is_enabled()

    def is_disabled(self) -> bool:
        locator = self._resolve_real_locator()
        return locator.is_disabled()

    def is_checked(self) -> bool:
        locator = self._resolve_real_locator()
        return locator.is_checked()

    def is_hidden(self) -> bool:
        locator = self._resolve_real_locator()
        return locator.is_hidden()

    def inner_text(self) -> str:
        locator = self._resolve_real_locator()
        return locator.inner_text()

    def inner_html(self) -> str:
        locator = self._resolve_real_locator()
        return locator.inner_html()

    def input_value(self) -> str:
        locator = self._resolve_real_locator()
        return locator.input_value()

    def text_content(self) -> str:
        locator = self._resolve_real_locator()
        return locator.text_content()

    def get_attribute(self, name: str) -> Optional[str]:
        locator = self._resolve_real_locator()
        return locator.get_attribute(name)

    def scroll_into_view_if_needed(self) -> None:
        locator = self._resolve_real_locator()
        return locator.scroll_into_view_if_needed()

    def wait_for(self, state: str = "visible", **kwargs) -> None:
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
            # 保留 strict violation 原始错误文本
            error_message = str(e)
            if "strict mode violation" in error_message.lower():
                error.strict_violation_message = error_message
            raise error from e

    def highlight(self) -> None:
        locator = self._resolve_real_locator()
        return locator.highlight()

    def screenshot(self, **kwargs) -> bytes:
        locator = self._resolve_real_locator()
        return locator.screenshot(**kwargs)

    def bounding_box(self) -> Optional[dict]:
        locator = self._resolve_real_locator()
        return locator.bounding_box()


class MonkeyPatchPage:
    """包装 Playwright Page，拦截定位方法返回 HealingLocator"""

    def __init__(self, page: Page):
        self._page = page

    def __getattr__(self, name: str) -> Any:
        if name in _LOCATOR_METHODS:
            @functools.wraps(getattr(self._page, name))
            def create_healing_locator(*args, **kwargs):
                method_call = MethodCall(method=name, args=list(args), kwargs=kwargs)
                expr = SelectorExpr(calls=[method_call])
                return HealingLocator(
                    original_locator=None,
                    page=self._page,
                    selector_expr=expr,
                )
            return create_healing_locator

        return getattr(self._page, name)

    # ---- 显式代理常用 Page 属性和方法 ----

    @property
    def url(self) -> str:
        return self._page.url

    def goto(self, url: str, **kwargs) -> Any:
        return self._page.goto(url, **kwargs)

    def wait_for_load_state(self, state: str = "load", **kwargs) -> None:
        return self._page.wait_for_load_state(state, **kwargs)

    def screenshot(self, **kwargs) -> bytes:
        return self._page.screenshot(**kwargs)

    def on(self, event: str, handler: Any) -> None:
        return self._page.on(event, handler)

    def frame_locator(self, selector: str) -> FrameLocator:
        return self._page.frame_locator(selector)

    @property
    def context(self) -> Any:
        return self._page.context

    def close(self, **kwargs) -> None:
        return self._page.close(**kwargs)

    def wait_for_url(self, url: Optional[str] = None, **kwargs) -> None:
        return self._page.wait_for_url(url, **kwargs)

    def reload(self, **kwargs) -> Any:
        return self._page.reload(**kwargs)

    def evaluate(self, expression: str, arg: Any = None) -> Any:
        return self._page.evaluate(expression, arg)

    def set_viewport_size(self, size: dict) -> None:
        return self._page.set_viewport_size(size)

    def title(self) -> str:
        return self._page.title()

    def wait_for_timeout(self, timeout: float) -> None:
        return self._page.wait_for_timeout(timeout)

    def expect(self) -> Any:
        return self._page.expect()

    def bring_to_front(self) -> None:
        return self._page.bring_to_front()

    def go_back(self, **kwargs) -> Any:
        return self._page.go_back(**kwargs)

    def go_forward(self, **kwargs) -> Any:
        return self._page.go_forward(**kwargs)

    @property
    def raw_page(self) -> Page:
        # 取原始 Page
        return self._page
