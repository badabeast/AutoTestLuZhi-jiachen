#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试链编排引擎。

负责调度测试模块的执行顺序：从知识库加载模块定义和依赖关系，
经拓扑排序确定执行链路，逐模块执行并传递跨模块变量，
最后汇总 UI/API/DB 三层断言的验证结果。

内部调用 graph / composer / variable_resolver / smart_inference 子模块。
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

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

    def _load_graph(self):
        """从知识库加载模块和依赖关系到图中"""
        self.graph = TestChainGraph()

        for mod_name in list_modules():
            mod_data = load_module_definition(mod_name)
            if mod_data:
                from .module_definition import ModuleDefinition
                self.graph.add_module(ModuleDefinition.from_dict(mod_data))

        raw_graph = load_dependency_graph()
        for mod_name, deps_list in raw_graph.items():
            for dep in deps_list:
                dep_name = dep["depends_on"] if isinstance(dep, dict) else dep
                var_mapping = dep.get("var_mapping", {}) if isinstance(dep, dict) else {}
                self.graph.add_dependency(mod_name, dep_name, var_mapping)

        logger.info("知识库加载完成: %d 个模块, %d 条依赖",
                     len(self.graph.modules), sum(len(v) for v in self.graph.edges.values()))

    def run(
        self,
        target_module: str,
        headed: bool = False,
        variables: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """编排并执行测试链

        Args:
            target_module: 目标模块名
            headed: 是否有头模式
            variables: 外部注入变量

        Returns:
            dict: 执行报告
        """
        # 1. 加载依赖图
        self._load_graph()

        # 2. 编排执行计划
        plan = self.composer.compose(target_module, self.graph)

        if not plan.chain:
            return {"success": False, "error": f"未找到模块: {target_module}", "results": []}

        print(f"\n🔗 执行链: {' → '.join(plan.chain)}")

        # 3. 注入外部变量
        if variables:
            self.resolver.inject_external(variables)

        # 4. 逐模块执行
        results = []
        for step in plan.steps:
            print(f"\n{'='*40}")
            print(f"▶ 执行模块: {step.module_id} (Step {step.order})")
            print(f"{'='*40}")

            # 注入上下文变量到环境
            self.resolver.inject_to_env()

            # 确定脚本路径
            script_path = self._resolve_script_path(step.module_id)
            if not script_path:
                results.append({
                    "module": step.module_id,
                    "success": False,
                    "error": "未找到可执行脚本",
                })
                break

            # 执行脚本
            module_result = self._execute_module(script_path, headed)
            results.append(module_result)

            if not module_result["success"]:
                print(f"❌ 模块 {step.module_id} 执行失败")
                break

            # 保存提取的变量
            self.resolver.extract_from_module_result(
                step.module_id, str(self.output_base)
            )

            print(f"✅ 模块 {step.module_id} 执行成功")

        # 5. 生成编排报告
        chain_success = all(r.get("success") for r in results)
        report = {
            "success": chain_success,
            "target_module": target_module,
            "execution_chain": plan.chain,
            "results": results,
            "variables": self.resolver.context_vars,
        }

        # 保存报告
        report_dir = self.output_base / target_module
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "orchestration_report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding='utf-8',
        )
        print(f"\n📊 编排报告: {report_path}")

        return report

    def _resolve_script_path(self, module_id: str) -> Optional[str]:
        """查找模块的可执行脚本"""
        module_dir = self.output_base / module_id

        # 优先使用增强脚本
        enhanced = module_dir / "enhanced_script.py"
        if enhanced.exists():
            return str(enhanced)

        # 回退到原始脚本
        raw = module_dir / "raw_script.py"
        if raw.exists():
            return str(raw)

        return None

    def _execute_module(self, script_path: str, headed: bool = False) -> Dict[str, Any]:
        """执行单个模块的测试脚本

        Args:
            script_path: 脚本路径
            headed: 是否有头模式

        Returns:
            dict: 执行结果
        """
        cmd = [
            sys.executable, "-m", "pytest",
            script_path,
            "-x", "-v",
        ]
        if not headed:
            cmd.append("--headless")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
            success = result.returncode == 0
            logger.info("模块执行 %s: returncode=%d", script_path, result.returncode)

            if not success and result.stderr:
                for line in result.stderr.split('\n')[-10:]:
                    if line.strip():
                        print(f"   {line.strip()}")

            return {
                "module": Path(script_path).parent.name,
                "success": success,
                "script": script_path,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "module": Path(script_path).parent.name,
                "success": False,
                "error": "执行超时（300s）",
                "script": script_path,
            }
        except Exception as e:
            return {
                "module": Path(script_path).parent.name,
                "success": False,
                "error": str(e),
                "script": script_path,
            }
