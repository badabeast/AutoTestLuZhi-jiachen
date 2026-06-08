#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestOrchestrator — 测试编排引擎

核心职责:
  1. 从依赖图构建前置链（拓扑排序）
  2. 按顺序执行模块
  3. 模块间变量传递（VariableResolver）
  4. 汇总三层断言结果

内部调用子模块:
  - graph.DependencyGraph: 依赖图构建与拓扑排序
  - composer.Composer: 执行计划编排
  - variable_resolver.VariableResolver: 跨模块变量传递
  - ai_inference.AIDependencyInference: AI 依赖推断

用法::

    orch = TestOrchestrator()
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
from .graph import DependencyGraph
from .composer import Composer
from .variable_resolver import VariableResolver
from .ai_inference import AIDependencyInference


class TestOrchestrator:
    """测试编排引擎"""

    def __init__(
        self,
        output_base: str = "output/modules",
        knowledge_dir: str = "knowledge/modules",
    ):
        self.output_base = Path(output_base)
        self.knowledge_dir = Path(knowledge_dir)
        self.graph = DependencyGraph()
        self.composer = Composer()
        self.resolver = VariableResolver()
        self.inferencer = AIDependencyInference()

    def build_pre_chain(self, target_module: str) -> List[str]:
        """构建前置执行链（拓扑排序）

        优先使用 DependencyGraph 子模块计算，回退到 knowledge 的原始依赖图。

        Args:
            target_module: 目标模块名

        Returns:
            List[str]: 执行顺序的模块列表（依赖在前）
        """
        # 尝试从子模块依赖图获取
        if self.graph.modules:
            chain = self.graph.get_execution_chain(target_module)
            if chain:
                return chain

        # 回退：从 knowledge 原始 JSON 加载
        raw_graph = load_dependency_graph()
        visited = set()
        chain = []

        def _visit(module_name: str):
            if module_name in visited:
                return
            visited.add(module_name)
            deps = raw_graph.get(module_name, [])
            for dep in deps:
                dep_name = dep["depends_on"] if isinstance(dep, dict) else dep
                _visit(dep_name)
            chain.append(module_name)

        _visit(target_module)
        return chain

    def run(
        self,
        target_module: str,
        headed: bool = False,
        variables: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """编排执行测试链

        Args:
            target_module: 目标模块名
            headed: 是否有头模式
            variables: 外部注入的变量

        Returns:
            Dict: 编排执行报告
        """
        # Step 1: 构建前置链
        chain = self.build_pre_chain(target_module)
        print(f"\n🔗 执行链: {' → '.join(chain)}")

        # Step 2: 初始化变量解析器
        self.resolver = VariableResolver()
        if variables:
            self.resolver.inject_external(variables)

        # Step 3: 逐模块执行
        results = []

        for module_name in chain:
            print(f"\n{'='*50}")
            print(f"📦 执行模块: {module_name}")
            print(f"{'='*50}")

            result = self._execute_module(
                module_name, self.resolver.context_vars, headed=headed
            )
            results.append(result)

            # 提取变量供后续模块使用
            extracted = self.resolver.extract_from_module_result(module_name)
            if extracted:
                print(f"   提取变量: {list(extracted.keys())}")

            # 如果模块执行失败且非最后一个，终止链
            if not result.get("success", True) and module_name != chain[-1]:
                print(f"   ⚠️ 模块 {module_name} 执行失败，终止链")
                break

        # Step 4: 汇总报告
        report = self._generate_report(target_module, chain, results, self.resolver.context_vars)

        # 保存报告
        report_dir = self.output_base / target_module
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "orchestration_report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8'
        )
        print(f"\n📊 编排报告: {report_path}")

        return report

    def _execute_module(
        self,
        module_name: str,
        variables: Dict[str, Any],
        headed: bool = False,
    ) -> Dict[str, Any]:
        """执行单个模块

        Args:
            module_name: 模块名称
            variables: 当前上下文变量
            headed: 是否有头模式

        Returns:
            Dict: 模块执行结果
        """
        module_def = load_module_definition(module_name)

        # 查找可执行脚本
        script_path = self._find_script(module_name)
        if not script_path:
            return {
                "module": module_name,
                "success": False,
                "error": f"未找到模块脚本: {module_name}",
            }

        # 注入变量到环境
        env = os.environ.copy()
        if variables:
            env["TEST_CONTEXT_VARS"] = json.dumps(variables, ensure_ascii=False)

        # 执行 pytest + healer
        cmd = [
            sys.executable, "-m", "pytest",
            str(script_path),
            "-x", "-v",
            "--ph-strategy=SMART",
            "--ph-auto-patch-source",
            "--ph-ai-patch-source",
        ]
        if headed:
            cmd.append("--headed")
        # pytest-playwright 默认 headless，不需要额外参数

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )

        # 解析结果
        success = result.returncode == 0

        # 尝试加载模块产生的变量提取结果
        extracted_vars = {}
        vars_path = self.output_base / module_name / "extracted_vars.json"
        if vars_path.exists():
            try:
                extracted_vars = json.loads(vars_path.read_text(encoding='utf-8'))
            except Exception:
                pass

        return {
            "module": module_name,
            "success": success,
            "script": str(script_path),
            "returncode": result.returncode,
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
            "extracted_vars": extracted_vars,
        }

    def _find_script(self, module_name: str) -> Optional[Path]:
        """查找模块的可执行脚本（优先 enhanced_script）"""
        module_dir = self.output_base / module_name

        for name in ["enhanced_script.py", "raw_script.py"]:
            path = module_dir / name
            if path.exists():
                return path
        return None

    def _generate_report(
        self,
        target_module: str,
        chain: List[str],
        results: List[Dict],
        context_vars: Dict[str, Any],
    ) -> Dict[str, Any]:
        """生成编排执行报告"""
        all_success = all(r.get("success", False) for r in results)

        return {
            "target_module": target_module,
            "execution_chain": chain,
            "total_modules": len(chain),
            "success": all_success,
            "results": results,
            "context_variables": context_vars,
            "summary": {
                "passed": sum(1 for r in results if r.get("success")),
                "failed": sum(1 for r in results if not r.get("success")),
                "total": len(results),
            },
        }
