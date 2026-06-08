#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DB 层断言 — MySQL 数据库断言

支持: 记录存在、字段值匹配（含变量模板）
特性: DB 不可达时自动跳过，不影响 UI/API 断言
"""

import os
import re
from typing import Dict, Any, Optional
from .assertion_rule import AssertionResult, AssertionStatus


def assert_db(assertion: Dict[str, Any], context: Dict[str, Any]) -> AssertionResult:
    """执行 DB 层断言（MySQL 不可达则自动跳过）

    Args:
        assertion: 断言规则（layer, type, description, sql, field, expected）
        context: 执行上下文（包含 variables）

    Returns:
        AssertionResult
    """
    desc = assertion.get("description", "")
    variables = context.get("variables", {})

    # 检查 DB 配置
    db_config = {
        "host": os.environ.get("MYSQL_HOST", ""),
        "port": int(os.environ.get("MYSQL_PORT", "3306")),
        "user": os.environ.get("MYSQL_USER", ""),
        "password": os.environ.get("MYSQL_PASS", ""),
        "database": os.environ.get("MYSQL_DB", ""),
    }

    if not db_config["host"] or not db_config["user"]:
        return AssertionResult(
            layer="db", description=desc,
            status=AssertionStatus.SKIPPED,
            error_message="DB 配置缺失（MYSQL_HOST/MYSQL_USER），跳过 DB 断言",
        )

    try:
        import pymysql
    except ImportError:
        return AssertionResult(
            layer="db", description=desc,
            status=AssertionStatus.SKIPPED,
            error_message="pymysql 未安装，跳过 DB 断言",
        )

    try:
        atype = assertion.get("type", "exists")

        # 变量模板替换 SQL
        sql = assertion.get("sql", "")
        if "{{" in sql:
            sql = _resolve_template(sql, variables)

        conn = pymysql.connect(**db_config, cursorclass=pymysql.cursors.DictCursor)
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                rows = cursor.fetchall()
        finally:
            conn.close()

        if atype == "exists":
            return _assert_exists(rows, desc)
        elif atype == "field":
            return _assert_field(rows, assertion, desc, variables)
        elif atype == "count":
            return _assert_count(rows, assertion, desc)
        else:
            return AssertionResult(
                layer="db", description=desc,
                status=AssertionStatus.ERROR,
                error_message=f"不支持的 DB 断言类型: {atype}",
            )

    except Exception as e:
        error_msg = str(e)
        if "Can't connect" in error_msg or "Connection refused" in error_msg:
            return AssertionResult(
                layer="db", description=desc,
                status=AssertionStatus.SKIPPED,
                error_message=f"DB 不可达，跳过: {error_msg}",
            )
        return AssertionResult(
            layer="db", description=desc,
            status=AssertionStatus.ERROR,
            error_message=error_msg,
        )


def _assert_exists(rows: list, desc: str) -> AssertionResult:
    """记录存在性断言"""
    exists = len(rows) > 0
    return AssertionResult(
        layer="db", description=desc,
        status=AssertionStatus.PASSED if exists else AssertionStatus.FAILED,
        expected="记录存在",
        actual=f"找到 {len(rows)} 条记录",
    )


def _assert_field(rows: list, assertion: dict, desc: str, variables: dict) -> AssertionResult:
    """字段值断言"""
    field_name = assertion.get("field", "")
    expected = assertion.get("expected", "")
    if "{{" in str(expected):
        expected = _resolve_template(str(expected), variables)

    if not rows:
        return AssertionResult(
            layer="db", description=desc,
            status=AssertionStatus.FAILED,
            error_message="查询无结果",
        )

    actual = rows[0].get(field_name, "")
    match = str(actual) == str(expected)
    return AssertionResult(
        layer="db", description=desc,
        status=AssertionStatus.PASSED if match else AssertionStatus.FAILED,
        expected=str(expected),
        actual=str(actual),
    )


def _assert_count(rows: list, assertion: dict, desc: str) -> AssertionResult:
    """记录数量断言"""
    expected = assertion.get("expected", 0)
    actual = len(rows)
    match = actual == expected
    return AssertionResult(
        layer="db", description=desc,
        status=AssertionStatus.PASSED if match else AssertionStatus.FAILED,
        expected=str(expected),
        actual=str(actual),
    )


def _resolve_template(template: str, variables: dict) -> str:
    """替换 {{var_name}} 模板"""
    def _replace(match):
        var_name = match.group(1)
        return str(variables.get(var_name, match.group(0)))
    return re.sub(r"\{\{(\w+)\}\}", _replace, template)
