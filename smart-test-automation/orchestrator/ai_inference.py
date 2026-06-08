#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 依赖推断器

使用 AI 分析模块间的依赖关系：
  1. 分析 API 请求序列中的数据流（前一个接口返回的 ID 被后一个接口使用）
  2. 跨模块依赖推断（模块 B 的请求参数引用了模块 A 的响应字段）
  3. 生成依赖关系建议（供人工确认）

用法::

    inferencer = AIDependencyInference()
    deps = inferencer.infer_cross_module("create_demand", "audit_demand")
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any

from knowledge import load_module_definition, list_modules


class AIDependencyInference:
    """AI 依赖推断器"""

    def __init__(self):
        self.knowledge_dir = Path("knowledge/modules")

    def infer_cross_module(
        self,
        module_a: str,
        module_b: str,
    ) -> Optional[Dict[str, Any]]:
        """推断两个模块之间的依赖关系

        分析模块 A 的产出变量是否被模块 B 的请求参数引用。

        Args:
            module_a: 上游模块名
            module_b: 下游模块名

        Returns:
            Dict: 依赖关系信息，无依赖返回 None
        """
        def_a = load_module_definition(module_a)
        def_b = load_module_definition(module_b)

        if not def_a or not def_b:
            return None

        # 提取模块 A 的产出变量
        a_outputs = set()
        for var in def_a.get("ai_analysis", {}).get("extract_vars", []):
            a_outputs.add(var.get("name", ""))

        # 提取模块 B 的输入参数
        b_inputs = set()
        for var in def_b.get("ai_analysis", {}).get("input_params", []):
            b_inputs.add(var.get("name", ""))

        # 匹配：如果 B 的输入参数名包含 A 的产出变量名
        # 或 A 产出的字段路径在 B 的请求中出现
        var_mapping = {}
        for a_var_name in a_outputs:
            for b_param_name in b_inputs:
                # 简单匹配：参数名中包含产出变量名
                # 如 create_demand_demand_id 被 confirm_demand_demand_id 匹配
                a_short = a_var_name.split("_", 1)[-1] if "_" in a_var_name else a_var_name
                b_short = b_param_name.split("_", 1)[-1] if "_" in b_param_name else b_param_name
                if a_short and b_short and (a_short in b_short or b_short in a_short):
                    var_mapping[b_param_name] = a_var_name

        if var_mapping:
            return {
                "from": module_a,
                "to": module_b,
                "var_mapping": var_mapping,
                "confidence": 0.8,
            }

        return None

    def infer_all(self) -> List[Dict[str, Any]]:
        """推断所有已录制模块之间的依赖关系

        Returns:
            List[Dict]: 依赖关系列表
        """
        modules = list_modules()
        dependencies = []

        for i, module_a in enumerate(modules):
            for module_b in modules:
                if module_a == module_b:
                    continue
                dep = self.infer_cross_module(module_a, module_b)
                if dep:
                    dependencies.append(dep)

        return dependencies

    def auto_update_graph(self):
        """自动推断所有依赖并更新依赖图

        Returns:
            int: 更新的依赖关系数量
        """
        from knowledge import add_dependency

        deps = self.infer_all()
        count = 0
        for dep in deps:
            var_mapping = dep.get("var_mapping", {})
            add_dependency(
                module_name=dep["to"],
                depends_on=dep["from"],
                var_mapping=var_mapping,
            )
            count += 1
            print(f"   📎 {dep['from']} → {dep['to']} ({list(var_mapping.keys())})")

        return count
