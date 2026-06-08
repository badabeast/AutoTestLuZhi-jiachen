#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
依赖图引擎

核心职责:
  1. 从模块定义构建依赖图（变量生产/消费关系）
  2. 拓扑排序计算前置执行链
  3. 变量映射表（哪个模块产出哪个变量，哪个模块消费哪个变量）

用法::

    graph = TestChainGraph()
    graph.add_module(module_def)
    chain = graph.get_execution_chain("confirm_demand")
    # → ["create_demand", "audit_demand", "confirm_demand"]
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Optional, Any

from .module_definition import ModuleDefinition


@dataclass
class DependencyEdge:
    """依赖边"""
    module: str           # 当前模块
    depends_on: str       # 依赖的模块
    variables: Dict[str, str] = field(default_factory=dict)  # {当前模块参数名: 源模块变量名}


class TestChainGraph:
    """模块依赖图引擎

    AI 自动推断模块间依赖 → 拓扑排序计算前置链 → 支持人工确认编辑
    """

    def __init__(self):
        self.modules: Dict[str, ModuleDefinition] = {}
        self.edges: Dict[str, Set[str]] = {}           # module → 依赖的模块集
        self.edge_details: Dict[str, List[DependencyEdge]] = {}  # 详细依赖信息
        self.variable_map: Dict[str, Dict] = {}        # var_name → {producer, field_path}

    def add_module(self, module: ModuleDefinition):
        """添加模块到依赖图

        同时注册该模块的产出变量，并推断与已有模块的依赖关系。
        """
        self.modules[module.id] = module

        # 注册产出变量
        for var in module.extract_variables:
            self.variable_map[var.name] = {
                "producer": module.id,
                "from_api": var.source,
                "from_field": var.field_path,
                "example_value": var.example_value,
            }

        # 推断依赖：如果该模块所需参数在已有模块的产出中
        for param in module.required_params:
            if param.name in self.variable_map:
                producer = self.variable_map[param.name]["producer"]
                self.edges.setdefault(module.id, set()).add(producer)

                # 记录详细依赖
                self.edge_details.setdefault(module.id, [])
                edge = DependencyEdge(
                    module=module.id,
                    depends_on=producer,
                    variables={param.name: param.name},
                )
                # 避免重复
                existing = self.edge_details[module.id]
                if not any(e.depends_on == producer for e in existing):
                    existing.append(edge)

    def add_dependency(self, module_name: str, depends_on: str,
                       var_mapping: Optional[Dict[str, str]] = None):
        """手动添加一条依赖关系"""
        self.edges.setdefault(module_name, set()).add(depends_on)
        edge = DependencyEdge(
            module=module_name,
            depends_on=depends_on,
            variables=var_mapping or {},
        )
        self.edge_details.setdefault(module_name, [])
        existing = self.edge_details[module_name]
        if not any(e.depends_on == depends_on for e in existing):
            existing.append(edge)

    def get_execution_chain(self, target_module: str) -> List[str]:
        """拓扑排序 → 返回从根到 target 的前置执行链

        Args:
            target_module: 目标模块名

        Returns:
            List[str]: 按执行顺序排列的模块列表（依赖在前）
        """
        chain = []
        visited = set()
        visiting = set()  # 检测循环依赖

        def _dfs(module_name: str):
            if module_name in visited:
                return
            if module_name in visiting:
                print(f"⚠️ 检测到循环依赖: {module_name}")
                return
            visiting.add(module_name)

            for dep in self.edges.get(module_name, set()):
                _dfs(dep)

            visiting.discard(module_name)
            visited.add(module_name)
            chain.append(module_name)

        _dfs(target_module)
        return chain

    def get_variable_sources(self, module_name: str) -> Dict[str, Dict]:
        """获取模块所需变量的来源信息

        Returns:
            Dict: {param_name: {"producer": "module_id", "var_name": "xxx"}}
        """
        sources = {}
        if module_name not in self.modules:
            return sources

        module = self.modules[module_name]
        for param in module.required_params:
            if param.name in self.variable_map:
                sources[param.name] = self.variable_map[param.name]

        return sources

    def save(self, path: str = "knowledge/dependency_graph.json"):
        """保存依赖图到 JSON"""
        data = {
            "modules": {k: v.to_dict() for k, v in self.modules.items()},
            "edges": {k: sorted(v) for k, v in self.edges.items()},
            "edge_details": {
                k: [{"module": e.module, "depends_on": e.depends_on,
                     "variables": e.variables} for e in edges]
                for k, edges in self.edge_details.items()
            },
            "variable_map": self.variable_map,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str = "knowledge/dependency_graph.json") -> "TestChainGraph":
        """从 JSON 加载依赖图"""
        graph = cls()
        if not Path(path).exists():
            return graph

        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        for mid, mdict in data.get("modules", {}).items():
            graph.modules[mid] = ModuleDefinition.from_dict(mdict)

        for mid, deps in data.get("edges", {}).items():
            graph.edges[mid] = set(deps)

        for mid, edge_list in data.get("edge_details", {}).items():
            graph.edge_details[mid] = [
                DependencyEdge(**e) for e in edge_list
            ]

        graph.variable_map = data.get("variable_map", {})
        return graph

    def visualize(self) -> str:
        """生成文本化的依赖图可视化"""
        lines = ["依赖图:"]
        if not self.edges:
            lines.append("  (空)")
            return "\n".join(lines)

        for module, deps in sorted(self.edges.items()):
            for dep in sorted(deps):
                details = self.edge_details.get(module, [])
                var_info = ""
                for d in details:
                    if d.depends_on == dep and d.variables:
                        var_info = f" [{', '.join(d.variables.keys())}]"
                lines.append(f"  {dep} → {module}{var_info}")

        return "\n".join(lines)
