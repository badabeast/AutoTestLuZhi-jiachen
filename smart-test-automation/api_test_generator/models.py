# -*- coding: utf-8 -*-
"""
数据模型定义
用于接口自动化用例生成器的数据结构
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from recorder.har_parser import APICall


@dataclass
class UIOperation:
    """UI 操作记录"""
    step_index: int
    action: str
    selector_type: str
    selector_value: str
    selector_name: Optional[str]
    value: Optional[str]
    raw_line: str
    timestamp: Optional[str] = None  # 从 codegen 录制中解析


@dataclass
class TimelineMapping:
    """UI 操作与 API 调用的时间线映射"""
    ui_operation: UIOperation
    api_calls: List[APICall] = field(default_factory=list)
    time_range: Tuple[str, str] = ("", "")  # (start, end) ISO timestamps
    confidence: float = 0.0


@dataclass
class ParamChain:
    """参数传递链"""
    source_api: str      # 如 "GET /api/workbench/my/themes"
    source_field: str    # 如 "result.id"
    source_example: Any  # 示例值
    target_api: str      # 如 "POST /api/demand/save"
    target_field: str    # 如 "templateId"
    chain_type: str      # "value_match" 或 "field_path_match"
    confidence: float = 0.0


@dataclass
class APIStep:
    """API 测试步骤"""
    step_index: int
    method: str
    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[Any] = None
    expected_status: int = 200
    extract_vars: Dict[str, str] = field(default_factory=dict)  # var_name -> jsonpath
    depends_on: List[str] = field(default_factory=list)  # 依赖的变量名


@dataclass
class TestCase:
    """测试用例"""
    module_name: str
    test_name: str
    steps: List[APIStep] = field(default_factory=list)
    setup: Optional[str] = None
    teardown: Optional[str] = None


@dataclass
class IncrementalDiff:
    """增量差异"""
    added_apis: List[APICall] = field(default_factory=list)
    removed_apis: List[APICall] = field(default_factory=list)
    modified_apis: List[Tuple[APICall, APICall]] = field(default_factory=list)
    updated_chains: List[ParamChain] = field(default_factory=list)
