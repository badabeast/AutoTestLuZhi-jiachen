#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
断言规则数据模型

定义三层断言的规则结构和通用类型。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List


class AssertionLayer(str, Enum):
    """断言层"""
    UI = "ui"
    API = "api"
    DB = "db"


class AssertionStatus(str, Enum):
    """断言状态"""
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class UIAssertionType(str, Enum):
    """UI 断言类型"""
    VISIBLE = "visible"       # 元素可见性
    TEXT = "text"             # 文本内容包含
    URL = "url"               # URL 包含
    COUNT = "count"           # 元素数量
    ATTRIBUTE = "attribute"   # 元素属性值
    ENABLED = "enabled"       # 元素可用


class APIAssertionType(str, Enum):
    """API 断言类型"""
    STATUS = "status"         # HTTP 状态码
    CODE = "code"             # 业务 code
    FIELD = "field"           # 响应字段值
    HEADER = "header"         # 响应头


class DBAssertionType(str, Enum):
    """DB 断言类型"""
    EXISTS = "exists"         # 记录存在
    FIELD = "field"           # 字段值匹配
    COUNT = "count"           # 记录数量


@dataclass
class AssertionResult:
    """单条断言结果"""
    layer: str                          # ui / api / db
    description: str                    # 断言描述
    status: str                         # passed / failed / skipped / error
    expected: str = ""                  # 期望值描述
    actual: str = ""                    # 实际值描述
    error_message: str = ""             # 错误信息
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AssertionRule:
    """断言规则

    通用断言规则定义，适用于所有三层。
    """
    layer: str                          # ui / api / db
    type: str                           # 断言类型（各层有不同取值）
    description: str = ""               # 断言描述

    # UI 断言参数
    selector: str = ""                  # CSS 选择器
    text: str = ""                      # 文本内容
    expected: Any = None                # 期望值

    # API 断言参数
    url_pattern: str = ""               # URL 匹配模式
    method: str = ""                    # HTTP 方法
    field: str = ""                     # JSON 字段路径

    # DB 断言参数
    sql: str = ""                       # SQL 查询

    # 通用
    timeout: int = 10000                # 超时时间（毫秒）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer": self.layer, "type": self.type,
            "description": self.description,
            "selector": self.selector, "text": self.text,
            "expected": self.expected, "url_pattern": self.url_pattern,
            "method": self.method, "field": self.field, "sql": self.sql,
        }
