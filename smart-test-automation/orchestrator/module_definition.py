#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模块定义数据模型

描述一个已录制业务模块的完整信息：
  - 脚本路径（raw/enhanced）
  - API 产物路径（HAR/Trace）
  - 提取变量（该模块产出哪些变量）
  - 所需参数（该模块需要哪些外部输入）
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


@dataclass
class VariableDef:
    """变量定义"""
    name: str                         # 变量名（如 demand_id）
    source: str = ""                  # 来源描述（如 "POST /demand/create → data.id"）
    field_path: str = ""              # JSON 路径（如 "data.id"）
    example_value: str = ""           # 示例值
    description: str = ""             # 变量说明


@dataclass
class ModuleDefinition:
    """模块定义

    对应 knowledge/modules/<module_name>.json 的数据模型。
    由 TwoStepRecorder 在录制完成后自动生成。
    """
    id: str                                    # 模块ID（如 create_demand）
    name: str = ""                             # 显示名称（如 "创建采购需求"）
    description: str = ""                      # 模块说明
    target_url: str = ""                       # 目标页面 URL

    # 脚本路径
    raw_script_path: str = ""                  # codegen 原始脚本
    enhanced_script_path: str = ""             # healer 兼容增强脚本

    # 产物路径
    har_path: str = ""                         # HAR 文件路径
    trace_path: str = ""                       # Trace 文件路径

    # 选择器信息（codegen 解析出的 UI 操作列表）
    selectors: List[Dict[str, Any]] = field(default_factory=list)

    # API 端点（HAR 解析出的 API 调用列表）
    api_endpoints: List[Dict[str, Any]] = field(default_factory=list)

    # 提取变量（该模块产出的变量，供下游模块使用）
    extract_variables: List[VariableDef] = field(default_factory=list)

    # 所需参数（该模块需要的外部输入参数）
    required_params: List[VariableDef] = field(default_factory=list)

    # AI 分析结果
    ai_analysis: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "target_url": self.target_url,
            "raw_script_path": self.raw_script_path,
            "enhanced_script_path": self.enhanced_script_path,
            "har_path": self.har_path,
            "trace_path": self.trace_path,
            "selectors": self.selectors,
            "api_endpoints": self.api_endpoints,
            "extract_variables": [
                {"name": v.name, "source": v.source, "field_path": v.field_path,
                 "example_value": v.example_value, "description": v.description}
                for v in self.extract_variables
            ],
            "required_params": [
                {"name": v.name, "source": v.source, "field_path": v.field_path,
                 "description": v.description}
                for v in self.required_params
            ],
            "ai_analysis": self.ai_analysis,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModuleDefinition":
        """从字典反序列化"""
        extract_vars = [
            VariableDef(**v) for v in data.get("extract_variables", [])
        ]
        required_params = [
            VariableDef(**v) for v in data.get("required_params", [])
        ]
        return cls(
            id=data.get("id", data.get("module_name", "")),
            name=data.get("name", ""),
            description=data.get("description", ""),
            target_url=data.get("target_url", ""),
            raw_script_path=data.get("raw_script_path", ""),
            enhanced_script_path=data.get("enhanced_script_path", ""),
            har_path=data.get("har_path", ""),
            trace_path=data.get("trace_path", ""),
            selectors=data.get("selectors", []),
            api_endpoints=data.get("api_endpoints", []),
            extract_variables=extract_vars,
            required_params=required_params,
            ai_analysis=data.get("ai_analysis", {}),
        )
