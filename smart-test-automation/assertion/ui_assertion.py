#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI 层断言 — Playwright 页面元素断言

支持: 元素可见性、文本内容、URL、数量、属性值、可用性
"""

from typing import Dict, Any, Optional
from .assertion_rule import AssertionResult, AssertionStatus


def assert_ui(assertion: Dict[str, Any], context: Dict[str, Any]) -> AssertionResult:
    """执行 UI 层断言

    Args:
        assertion: 断言规则（layer, type, description, selector, text, expected 等）
        context: 执行上下文（必须包含 "page"）

    Returns:
        AssertionResult
    """
    page = context.get("page")
    desc = assertion.get("description", "")
    atype = assertion.get("type", "visible")

    if not page:
        return AssertionResult(
            layer="ui", description=desc,
            status=AssertionStatus.SKIPPED,
            error_message="page 对象不可用",
        )

    try:
        if atype == "visible":
            return _assert_visible(page, assertion, desc)
        elif atype == "text":
            return _assert_text(page, assertion, desc)
        elif atype == "url":
            return _assert_url(page, assertion, desc)
        elif atype == "count":
            return _assert_count(page, assertion, desc)
        elif atype == "enabled":
            return _assert_enabled(page, assertion, desc)
        else:
            return AssertionResult(
                layer="ui", description=desc,
                status=AssertionStatus.ERROR,
                error_message=f"不支持的 UI 断言类型: {atype}",
            )
    except Exception as e:
        return AssertionResult(
            layer="ui", description=desc,
            status=AssertionStatus.ERROR,
            error_message=str(e),
        )


def _assert_visible(page, assertion: dict, desc: str) -> AssertionResult:
    """元素可见性断言"""
    selector = assertion.get("selector", "")
    expected_text = assertion.get("text", "")

    if expected_text:
        locator = page.get_by_text(expected_text)
    elif selector:
        locator = page.locator(selector)
    else:
        return AssertionResult(
            layer="ui", description=desc,
            status=AssertionStatus.ERROR,
            error_message="缺少 selector 或 text 参数",
        )

    visible = locator.is_visible()
    return AssertionResult(
        layer="ui", description=desc,
        status=AssertionStatus.PASSED if visible else AssertionStatus.FAILED,
        expected="元素可见",
        actual=f"元素{'可见' if visible else '不可见'}",
    )


def _assert_text(page, assertion: dict, desc: str) -> AssertionResult:
    """文本内容断言"""
    selector = assertion.get("selector", "")
    expected = assertion.get("expected", "")

    locator = page.locator(selector)
    actual = locator.text_content() or ""
    match = expected in actual
    return AssertionResult(
        layer="ui", description=desc,
        status=AssertionStatus.PASSED if match else AssertionStatus.FAILED,
        expected=expected,
        actual=actual[:200],
    )


def _assert_url(page, assertion: dict, desc: str) -> AssertionResult:
    """URL 包含断言"""
    expected = assertion.get("expected", "")
    actual = page.url
    match = expected in actual
    return AssertionResult(
        layer="ui", description=desc,
        status=AssertionStatus.PASSED if match else AssertionStatus.FAILED,
        expected=expected,
        actual=actual,
    )


def _assert_count(page, assertion: dict, desc: str) -> AssertionResult:
    """元素数量断言"""
    selector = assertion.get("selector", "")
    expected_count = assertion.get("expected", 0)
    actual_count = page.locator(selector).count()
    match = actual_count == expected_count
    return AssertionResult(
        layer="ui", description=desc,
        status=AssertionStatus.PASSED if match else AssertionStatus.FAILED,
        expected=str(expected_count),
        actual=str(actual_count),
    )


def _assert_enabled(page, assertion: dict, desc: str) -> AssertionResult:
    """元素可用性断言"""
    selector = assertion.get("selector", "")
    locator = page.locator(selector)
    enabled = locator.is_enabled()
    return AssertionResult(
        layer="ui", description=desc,
        status=AssertionStatus.PASSED if enabled else AssertionStatus.FAILED,
        expected="元素可用",
        actual=f"元素{'可用' if enabled else '不可用'}",
    )
