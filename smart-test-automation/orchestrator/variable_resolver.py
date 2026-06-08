#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
变量传递解析器

管理模块间的变量传递：
  1. 从模块执行结果中提取变量值
  2. 将变量注入到后续模块的执行上下文中
  3. 支持变量模板替换（{{var_name}}）

变量传递链路:
  Module A 执行 → 提取 demand_id=XQ-001
  → 写入 context_vars["demand_id"] = "XQ-001"
  → Module B 执行时注入 TEST_CONTEXT_VARS 环境变量
  → Module B 脚本中通过 os.environ["TEST_CONTEXT_VARS"] 读取
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Any


class CrossModuleVariableBridge:
    """变量传递解析器"""

    def __init__(self):
        self.context_vars: Dict[str, Any] = {}

    def inject_external(self, variables: Dict[str, Any]):
        """注入外部变量"""
        self.context_vars.update(variables)

    def extract_from_module_result(
        self,
        module_name: str,
        output_dir: str = "output/modules",
    ) -> Dict[str, Any]:
        """从模块执行结果中提取变量

        读取 output/modules/<module_name>/extracted_vars.json

        Args:
            module_name: 模块名称
            output_dir: 输出目录

        Returns:
            Dict: 提取的变量
        """
        vars_path = Path(output_dir) / module_name / "extracted_vars.json"
        if not vars_path.exists():
            return {}

        try:
            data = json.loads(vars_path.read_text(encoding='utf-8'))
            self.context_vars.update(data)
            return data
        except Exception as e:
            print(f"⚠️ 读取变量文件失败: {vars_path} → {e}")
            return {}

    def resolve_template(self, template: str) -> str:
        """替换 {{var_name}} 模板

        Args:
            template: 含模板的字符串

        Returns:
            str: 替换后的字符串
        """
        def _replace(match):
            var_name = match.group(1)
            value = self.context_vars.get(var_name)
            if value is not None:
                return str(value)
            return match.group(0)  # 未找到变量，保留原模板
        return re.sub(r"\{\{(\w+)\}\}", _replace, template)

    def resolve_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """递归替换字典中所有字符串值的模板"""
        resolved = {}
        for key, value in data.items():
            if isinstance(value, str):
                resolved[key] = self.resolve_template(value)
            elif isinstance(value, dict):
                resolved[key] = self.resolve_dict(value)
            elif isinstance(value, list):
                resolved[key] = [
                    self.resolve_template(item) if isinstance(item, str) else item
                    for item in value
                ]
            else:
                resolved[key] = value
        return resolved

    def to_env_json(self) -> str:
        """导出为 JSON 字符串，用于注入到 TEST_CONTEXT_VARS 环境变量"""
        return json.dumps(self.context_vars, ensure_ascii=False)

    def inject_to_env(self):
        """将当前上下文变量注入到环境变量"""
        if self.context_vars:
            os.environ["TEST_CONTEXT_VARS"] = self.to_env_json()

    @classmethod
    def from_env(cls) -> "VariableResolver":
        """从环境变量恢复上下文"""
        resolver = cls()
        env_vars = os.environ.get("TEST_CONTEXT_VARS", "")
        if env_vars:
            try:
                resolver.context_vars = json.loads(env_vars)
            except json.JSONDecodeError:
                pass
        return resolver

    def save(self, path: str):
        """保存变量上下文到文件"""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps(self.context_vars, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

    def summary(self) -> str:
        """变量摘要"""
        if not self.context_vars:
            return "  (无变量)"
        lines = []
        for k, v in self.context_vars.items():
            v_str = str(v)[:50]
            lines.append(f"  {k} = {v_str}")
        return "\n".join(lines)
