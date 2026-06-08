#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestChainOrchestrator — 测试链编排引擎

核心职责:
  1. 从依赖图构建前置链（拓扑排序）
  2. 按顺序执行模块
  3. 模块间变量传递（CrossModuleVariableBridge）
  4. 汇总三层断言结果

内部调用子模块:
  - graph.TestChainGraph: 依赖图构建与拓扑排序
  - composer.ExecutionPlanComposer: 执行计划编排
  - variable_resolver.CrossModuleVariableBridge: 跨模块变量传递
  - smart_inference.CrossModuleInferencer: 智能依赖推断

用法::

    orch = TestChainOrchestrator()
    report = orch.run("confirm_demand")
    # 自动构建链: create_demand → audit_demand → confirm_demand
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

from knowledge import (
    load_module_definition,
    load_dependency_graph,
    list_modules,
    save_module_definition,
)
from .graph import TestChainGraph
from .composer import ExecutionPlanComposer
from .variable_resolver import CrossModuleVariableBridge
from .smart_inference import CrossModuleInferencer


class TestChainOrchestrator:
    """测试链编排引擎"""

    def __init__(
        self,
        output_base: str = "output/modules",
        knowledge_dir: str = "knowledge/modules",
    ):
        self.output_base = Path(output_base)
        self.knowledge_dir = Path(knowledge_dir)
        self.graph = TestChainGraph()
        self.composer = ExecutionPlanComposer()
        self.resolver = CrossModuleVariableBridge()
        self.inferencer = CrossModuleInferencer()
