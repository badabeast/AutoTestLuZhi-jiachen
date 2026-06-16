#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API 层断言 — HTTP 响应断言

支持: 状态码、业务 code、响应字段值（含变量模板）、响应头
"""

import json
import re
from typing import Dict, Any, Optional
from .assertion_rule import AssertionResult, AssertionStatus


def assert_api(assertion: Dict[str, Any], context: Dict[str, Any]) -> AssertionResult:
    """执行 API 层断言

    Args:
        assertion: 断言规则
        context: 执行上下文（必须包含 "api_calls" 列表）

    Returns:
        AssertionResult
    """
    api_calls = context.get("api_calls", [])
    variables = context.get("variables", {})
    desc = assertion.get("description", "")
    atype = assertion.get("type", "status")

    if not api_calls:
        return AssertionResult(
            layer="api", description=desc,
            status=AssertionStatus.SKIPPED,
            error_message="无 API 调用数据",
        )

    try:
        # 匹配目标 API 调用
        target_call = _find_api_call(api_calls, assertion)
        if not target_call:
            return AssertionResult(
                layer="api", description=desc,
                status=AssertionStatus.FAILED,
                error_message=f"未找到匹配的 API 调用: {assertion.get('url_pattern', assertion.get('url', ''))}",
            )

        if atype == "status":
            return _assert_status(target_call, assertion, desc)
        elif atype == "code":
            return _assert_code(target_call, assertion, desc)
        elif atype == "field":
            return _assert_field(target_call, assertion, desc, variables)
        elif atype == "header":
            return _assert_header(target_call, assertion, desc)
        else:
            return AssertionResult(
                layer="api", description=desc,
                status=AssertionStatus.ERROR,
                error_message=f"不支持的 API 断言类型: {atype}",
            )
    except Exception as e:
        return AssertionResult(
            layer="api", description=desc,
            status=AssertionStatus.ERROR,
            error_message=str(e),
        )


def _find_api_call(api_calls: list, assertion: dict) -> Optional[Any]:
    """在 API 调用列表中查找匹配的调用"""
    url_pattern = assertion.get("url_pattern", assertion.get("url", ""))
    method = assertion.get("method", "")

    for call in api_calls:
        call_url = _get_attr(call, "url", "")
        call_path = _get_attr(call, "path", "")
        call_method = _get_attr(call, "method", "")

        if url_pattern and url_pattern in (call_url or call_path):
            if not method or call_method.upper() == method.upper():
                return call
    return None


def _assert_status(target_call, assertion: dict, desc: str) -> AssertionResult:
    """HTTP 状态码断言"""
    expected = assertion.get("expected", 200)
    actual = _get_attr(target_call, "status", 0)
    return AssertionResult(
        layer="api", description=desc,
        status=AssertionStatus.PASSED if actual == expected else AssertionStatus.FAILED,
        expected=str(expected),
        actual=str(actual),
    )


def _assert_code(target_call, assertion: dict, desc: str) -> AssertionResult:
    """业务 code 断言"""
    resp = _get_response_body(target_call)
    expected = assertion.get("expected", 0)
    actual = resp.get("code", resp.get("status", None))
    return AssertionResult(
        layer="api", description=desc,
        status=AssertionStatus.PASSED if actual == expected else AssertionStatus.FAILED,
        expected=str(expected),
        actual=str(actual),
    )


def _assert_field(target_call, assertion: dict, desc: str, variables: dict) -> AssertionResult:
    """响应字段值断言（支持 {{var}} 变量模板）"""
    resp = _get_response_body(target_call)
    field_path = assertion.get("field", "")
    expected = assertion.get("expected", "")

    # 变量模板替换
    if isinstance(expected, str) and "{{" in expected:
        expected = _resolve_template(expected, variables)

    actual = _get_nested(resp, field_path)
    match = str(actual) == str(expected)
    return AssertionResult(
        layer="api", description=desc,
        status=AssertionStatus.PASSED if match else AssertionStatus.FAILED,
        expected=str(expected),
        actual=str(actual),
    )


def _assert_header(target_call, assertion: dict, desc: str) -> AssertionResult:
    """响应头断言"""
    headers = _get_attr(target_call, "response_headers", {})
    header_name = assertion.get("field", "")
    expected = assertion.get("expected", "")
    actual = headers.get(header_name, "")
    match = str(expected) in str(actual)
    return AssertionResult(
        layer="api", description=desc,
        status=AssertionStatus.PASSED if match else AssertionStatus.FAILED,
        expected=str(expected),
        actual=str(actual),
    )


# 工具方法

def _get_attr(call, key, default=None):
    """兼容 dict 和 dataclass 两种访问方式"""
    if isinstance(call, dict):
        return call.get(key, default)
    return getattr(call, key, default)


def _get_response_body(call) -> dict:
    """获取响应体（确保返回 dict）"""
    resp = _get_attr(call, "response_body") or {}
    if isinstance(resp, str):
        try:
            resp = json.loads(resp)
        except Exception:
            resp = {}
    return resp if isinstance(resp, dict) else {}


def _resolve_template(template: str, variables: dict) -> str:
    """替换 {{var_name}} 模板"""
    def _replace(match):
        var_name = match.group(1)
        return str(variables.get(var_name, match.group(0)))
    return re.sub(r"\{\{(\w+)\}\}", _replace, template)


def _get_nested(data: dict, path: str, default=None):
    """获取嵌套字典值（data.items.0.name）"""
    keys = path.split(".")
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list):
            try:
                current = current[int(key)]
            except (ValueError, IndexError):
                return default
        else:
            return default
        if current is None:
            return default
    return current
