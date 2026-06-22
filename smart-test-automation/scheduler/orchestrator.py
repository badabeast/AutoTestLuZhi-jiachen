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
        no_heal: bool = False,
    ) -> Dict[str, Any]:
        """编排并执行测试链

        Args:
            target_module: 目标模块名
            headed: 是否有头模式
            variables: 外部注入变量
            no_heal: 是否禁用自愈

        Returns:
            dict: 执行报告
        """
        self._load_graph()

        plan = self.composer.compose(target_module, self.graph)

        if not plan.chain:
            return {"success": False, "error": f"未找到模块: {target_module}", "results": []}

        print(f"\n🔗 执行链: {' → '.join(plan.chain)}")

        if variables:
            self.resolver.inject_external(variables)

        results = []
        for step in plan.steps:
            print(f"\n{'='*40}")
            print(f"▶ 执行模块: {step.module_id} (Step {step.order})")
            print(f"{'='*40}")

            self.resolver.inject_to_env()

            script_path = self._resolve_script_path(step.module_id)
            if not script_path:
                results.append({
                    "module": step.module_id,
                    "success": False,
                    "error": "未找到可执行脚本",
                })
                break

            module_result = self._execute_module(script_path, headed, no_heal=no_heal)
            results.append(module_result)

            if not module_result["success"]:
                # P0 #1: 检查自动修复是否成功
                healed = self._check_heal_result(step.module_id)
                if healed:
                    module_result["success"] = True
                    module_result["healed"] = True
                    module_result["healed_selectors"] = healed
                    print(f"🩹 模块 {step.module_id} 自愈修复成功，继续执行后续模块")
                else:
                    print(f"❌ 模块 {step.module_id} 执行失败")
                    break

            self.resolver.extract_from_module_result(
                step.module_id, str(self.output_base)
            )

            try:
                from assertion.engine import ThreeLayerAssertionEngine
                from assertion.assertion_rule import AssertionResult, AssertionStatus
                from recorder.har_parser import HARParser

                module_dir = self.output_base / step.module_id
                har_path = module_dir / "api.har"

                if har_path.exists():
                    har_parser = HARParser()
                    api_calls = har_parser.parse_api_sequence(str(har_path))

                    if api_calls:
                        engine = ThreeLayerAssertionEngine()
                        api_assertions = []
                        for call in api_calls:
                            # 使用录制时的实际状态码作为期望值，而非硬编码 200
                            expected_status = call.status if call.status else 200
                            api_assertions.append({
                                "layer": "api",
                                "type": "status",
                                "description": f"{call.method} {call.path} 返回 {expected_status}",
                                "url_pattern": call.path,
                                "method": call.method,
                                "expected": expected_status,
                            })

                        assertion_results = engine.run_assertions(
                            api_assertions,
                            {"api_calls": api_calls}
                        )

                        # 读取 UI 断言结果并合并
                        ui_results_path = module_dir / "ui_assertion_results.json"
                        if ui_results_path.exists():
                            try:
                                ui_data = json.loads(ui_results_path.read_text(encoding='utf-8'))
                                for ui_item in ui_data:
                                    ui_result = AssertionResult(
                                        layer=ui_item.get("layer", "ui"),
                                        description=ui_item.get("description", ""),
                                        status=ui_item.get("status", "unknown"),
                                        expected=ui_item.get("expected", ""),
                                        actual=ui_item.get("actual", ""),
                                        error_message=ui_item.get("error_message", ""),
                                    )
                                    assertion_results.append(ui_result)
                            except Exception as e:
                                logger.warning(f"读取 UI 断言结果失败: {e}")

                        assertion_report = engine.generate_report(assertion_results)
                        report_path = module_dir / "assertion_report.json"
                        report_path.write_text(
                            json.dumps(assertion_report, ensure_ascii=False, indent=2, default=str),
                            encoding='utf-8',
                        )

                        # 分别统计 UI 和 API 断言
                        ui_results = [r for r in assertion_results if r.layer == "ui"]
                        api_results = [r for r in assertion_results if r.layer == "api"]
                        
                        ui_passed = sum(1 for r in ui_results if r.status == AssertionStatus.PASSED)
                        ui_failed = sum(1 for r in ui_results if r.status == AssertionStatus.FAILED)
                        api_passed = sum(1 for r in api_results if r.status == AssertionStatus.PASSED)
                        api_failed = sum(1 for r in api_results if r.status == AssertionStatus.FAILED)
                        
                        passed = ui_passed + api_passed
                        failed = ui_failed + api_failed
                        
                        print(f"   📊 断言统计:")
                        if ui_results:
                            print(f"      UI 断言: {ui_passed}/{len(ui_results)} 通过, {ui_failed} 失败")
                        if api_results:
                            print(f"      API 断言: {api_passed}/{len(api_results)} 通过, {api_failed} 失败")
                        print(f"      总计: {passed}/{len(assertion_results)} 通过, {failed} 失败")

                        if failed > 0:
                            for r in assertion_results:
                                if r.status == AssertionStatus.FAILED:
                                    print(f"      ❌ [{r.layer.upper()}] {r.description}: 期望 {r.expected}, 实际 {r.actual}")

                        module_result["assertion_summary"] = {
                            "total": len(assertion_results),
                            "passed": passed,
                            "failed": failed,
                            "ui_passed": ui_passed,
                            "ui_failed": ui_failed,
                            "api_passed": api_passed,
                            "api_failed": api_failed,
                        }
            except Exception as e:
                print(f"   ⚠️ 断言执行异常: {e}")
                logger.warning("断言执行异常: %s", e)

            print(f"✅ 模块 {step.module_id} 执行成功")

        chain_success = all(r.get("success") for r in results)
        healed_count = sum(1 for r in results if r.get("healed"))
        report = {
            "success": chain_success,
            "target_module": target_module,
            "execution_chain": plan.chain,
            "results": results,
            "variables": self.resolver.context_vars,
            "assertion_summary": self._aggregate_assertions(results),
            "healed_count": healed_count,
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

    def _aggregate_assertions(self, results: list) -> dict:
        """汇总所有模块的断言结果"""
        total = 0
        passed = 0
        failed = 0
        for r in results:
            summary = r.get("assertion_summary", {})
            total += summary.get("total", 0)
            passed += summary.get("passed", 0)
            failed += summary.get("failed", 0)
        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "success": failed == 0,
        }

    def _check_heal_result(self, module_id: str) -> Optional[List[Dict[str, str]]]:
        """检查 heal_report.json 判断自动修复是否成功

        # 查 heal_log.json 看有没有修复成功的记录

        Args:
            module_id: 模块标识

        Returns:
            成功修复的选择器列表 [{old, new}]，或 None
        """
        # 1. 检查 heal_log.json（strategy repair 在 sessionfinish 中写入）
        heal_log_path = Path("output") / "heal_log.json"
        if heal_log_path.exists():
            try:
                with open(heal_log_path, "r", encoding="utf-8") as f:
                    logs = json.load(f)
                if isinstance(logs, list):
                    healed = [
                        {"old": entry.get("old_selector", ""),
                         "new": entry.get("new_selector", "")}
                        for entry in logs
                        if entry.get("success") and entry.get("new_selector")
                    ]
                    if healed:
                        logger.info("检测到 %d 条成功修复记录", len(healed))
                        return healed
            except Exception as e:
                logger.warning("读取 heal_log.json 失败: %s", e)

        # 2. 回退检查 heal_report.json 的 archive 目录
        archive_dir = Path("output") / "archive"
        if archive_dir.exists():
            try:
                archive_files = sorted(archive_dir.glob("heal_report_*.json"), reverse=True)
                if archive_files:
                    with open(archive_files[0], "r", encoding="utf-8") as f:
                        report = json.load(f)
                    """heal_report 本身记录的是失败现场，无法直接判断修复是否成功
                    但如果 strategy repair 流程正常走完，heal_log.json 应该存在
                    此处仅作兜底日志"""
                    failures = report.get("failures", [])
                    logger.info("归档报告包含 %d 条失败记录（仅供参考）", len(failures))
            except Exception:
                pass

        return None

    def _resolve_script_path(self, module_id: str) -> Optional[str]:
        """查找模块的可执行脚本"""
        module_dir = self.output_base / module_id

        enhanced = module_dir / "enhanced_script.py"
        if enhanced.exists():
            return str(enhanced)

        raw = module_dir / "raw_script.py"
        if raw.exists():
            return str(raw)

        return None

    def _execute_module(
        self, script_path: str, headed: bool = False, no_heal: bool = False
    ) -> Dict[str, Any]:
        """执行单个模块的测试脚本

        Args:
            script_path: 脚本路径
            headed: 是否有头模式
            no_heal: 是否禁用自愈

        Returns:
            dict: 执行结果
        """
        cmd = [
            sys.executable, "-m", "pytest",
            script_path,
            "-x", "-v",
        ]
        if headed:
            cmd.append("--headed")

        # 默认开启自愈
        if not no_heal:
            cmd.extend([
                "--ph-strategy=SMART",
                "--ph-auto-patch-source",
                "--ph-ai-patch-source",
            ])

        try:
            # P0 #2: 传入向后兼容的 healer 环境变量
            env = os.environ.copy()
            try:
                from self_healing.healer_config import get_healer_env_vars
                env.update(get_healer_env_vars())
            except Exception:
                logger.warning("healer_config.get_healer_env_vars() 导入失败，子进程可能缺少 AI 配置")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                env=env,
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
