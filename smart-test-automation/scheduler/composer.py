#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
执行计划编排器

根据依赖图的前置链，生成执行计划并管理变量传递。

用法::

    graph = TestChainGraph()
    composer = ExecutionPlanComposer()
    plan = composer.compose("confirm_demand", graph)
    # plan.chain = ["create_demand", "audit_demand", "confirm_demand"]
    # plan.steps[0].needs = {}
    # plan.steps[1].needs = {"demand_id": "from_module:create_demand"}
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

from .graph import TestChainGraph
from .module_definition import ModuleDefinition


@dataclass
class ExecutionStep:
    """单个模块的执行步骤"""
    module_id: str                           # 模块 ID
    script_path: str = ""                    # 脚本路径
    needs: Dict[str, str] = field(default_factory=dict)     # 需要的变量 {param: source}
    produces: Dict[str, str] = field(default_factory=dict)  # 产出的变量 {var: field_path}
    order: int = 0                           # 执行顺序


@dataclass
class ExecutionPlan:
    """完整执行计划"""
    target: str                                  # 目标模块
    chain: List[str] = field(default_factory=list)  # 执行链
    steps: List[ExecutionStep] = field(default_factory=list)
    variables: Dict[str, Any] = field(default_factory=dict)  # 上下文变量
    external_params: Dict[str, Any] = field(default_factory=dict)  # 外部注入参数

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "chain": self.chain,
            "steps": [
                {"module_id": s.module_id, "script_path": s.script_path,
                 "needs": s.needs, "produces": s.produces, "order": s.order}
                for s in self.steps
            ],
            "variables": self.variables,
            "external_params": self.external_params,
        }


class ExecutionPlanComposer:
    """执行计划编排器"""

    def compose(
        self,
        target_module: str,
        graph: TestChainGraph,
        external_params: Optional[Dict[str, Any]] = None,
    ) -> ExecutionPlan:
        """根据依赖图编排执行计划

        Args:
            target_module: 目标模块名
            graph: 依赖图实例
            external_params: 外部注入的变量

        Returns:
            ExecutionPlan: 执行计划
        """
        # 获取执行链
        chain = graph.get_execution_chain(target_module)

        plan = ExecutionPlan(
            target=target_module,
            chain=chain,
            variables=dict(external_params or {}),
            external_params=dict(external_params or {}),
        )

        for i, module_id in enumerate(chain):
            module_def = graph.modules.get(module_id)
            step = ExecutionStep(
                module_id=module_id,
                order=i,
            )

            if module_def:
                # 脚本路径
                step.script_path = (
                    module_def.enhanced_script_path
                    or module_def.raw_script_path
                )

                # 产出变量
                for var in module_def.extract_variables:
                    step.produces[var.name] = var.field_path

            # 所需变量来源
            var_sources = graph.get_variable_sources(module_id)
            for param_name, source_info in var_sources.items():
                producer = source_info.get("producer", "")
                step.needs[param_name] = f"from_module:{producer}"

            plan.steps.append(step)

        return plan

    def print_plan(self, plan: ExecutionPlan):
        """打印执行计划"""
        print(f"\n{'='*50}")
        print(f"📋 执行计划: {plan.target}")
        print(f"{'='*50}")
        print(f"🔗 执行链: {' → '.join(plan.chain)}")
        print()

        for step in plan.steps:
            print(f"  Step {step.order}: {step.module_id}")
            if step.script_path:
                print(f"    脚本: {step.script_path}")
            if step.needs:
                print(f"    需要: {step.needs}")
            if step.produces:
                print(f"    产出: {list(step.produces.keys())}")
            print()
