#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能测试执行系统命令行入口，提供录制、编排、执行、自愈、报告等子命令。
运行 python cli.py -h 查看完整帮助。
"""

import argparse
import json
import sys
import os
from pathlib import Path

# 确保项目根目录在 import 路径中
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# 加载 .env（统一工具函数）
from config.env_loader import load_env
load_env()


def main():
    parser = argparse.ArgumentParser(
        description="智能测试执行系统 CLI（v5 Final）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # ── record ──
    record_parser = subparsers.add_parser("record", help="录制业务模块（两步录制法）")
    record_parser.add_argument("module_name", help="模块名称（如 create_demand）")
    record_parser.add_argument("--url", default="", help="目标 URL（默认从配置获取）")
    record_parser.add_argument("--project", default="web-demand", help="项目名称")
    record_parser.add_argument("--storage-state", default="login_state/storage_state.json",
                              help="登录态文件路径")
    record_parser.add_argument("--har-filter", default="",
                              help="HAR URL 过滤模式（默认全量捕获，由解析阶段过滤静态资源）")
    record_parser.add_argument("--headed-step2", action="store_true",
                              help="Step 2 回放使用有头模式")

    # ── replay ──
    replay_parser = subparsers.add_parser("replay", help="重放已有 raw_script 生成 HAR/Trace")
    replay_parser.add_argument("module_name", help="模块名称")
    replay_parser.add_argument("--storage-state", default="login_state/storage_state.json",
                               help="登录态文件路径")
    replay_parser.add_argument("--headed", action="store_true", help="有头模式")

    # ── run ──
    run_parser = subparsers.add_parser("run", help="编排+执行测试链")
    run_parser.add_argument("target_module", help="目标模块名（如 confirm_demand）")
    run_parser.add_argument("--headed", action="store_true", help="有头模式执行")
    run_parser.add_argument("--no-heal", action="store_true",
                            help="禁用自愈（调试用）")
    run_parser.add_argument("--var", action="append", default=[],
                            help="注入变量 key=value（可多次使用）")

    # ── compose（查看编排计划，不执行）──
    compose_parser = subparsers.add_parser("compose", help="查看编排计划（不执行）")
    compose_parser.add_argument("target_module", help="目标模块名")
    compose_parser.add_argument("--save", default="", help="保存执行计划到指定路径")

    # ── generate-script ──
    gen_parser = subparsers.add_parser("generate-script", help="生成增强脚本（healer 兼容）")
    gen_parser.add_argument("module_name", help="模块名称")
    gen_parser.add_argument("--extract-vars", nargs="*", default=[],
                            help="提取变量列表（name:from_api:from_field）")

    # ── heal ──
    heal_parser = subparsers.add_parser("heal", help="手动触发自愈")
    heal_parser.add_argument("module_name", help="模块名称")
    heal_parser.add_argument("--headed", action="store_true", help="有头模式")

    # ── repair（回退优先级策略层）──
    repair_parser = subparsers.add_parser("repair", help="回退优先级策略层 — 智能分析失败并选择修复策略")
    repair_parser.add_argument("--report", default="output/heal_report.json",
                               help="heal_report.json 路径（默认 output/heal_report.json）")
    repair_parser.add_argument("--dry-run", action="store_true",
                               help="仅分析决策，不执行修复")

    # ── report ──
    report_parser = subparsers.add_parser("report", help="查看断言报告")
    report_parser.add_argument("--module", default="", help="指定模块名筛选")

    # ── query-knowledge ──
    query_parser = subparsers.add_parser("query-knowledge", help="查询知识库")
    query_parser.add_argument("--module", default="", help="查询指定模块定义")
    query_parser.add_argument("--graph", action="store_true", help="查看依赖图")
    query_parser.add_argument("--frontend", action="store_true", help="查看前端知识文档")
    query_parser.add_argument("--api", default="", help="按 API 路径搜索前端知识")

    # ── list ──
    list_parser = subparsers.add_parser("list", help="列出已录制模块")

    args = parser.parse_args()

    # ── record ──
    if args.command == "record":
        from recorder.recording_wrapper import TwoStepRecorder

        url = args.url
        if not url:
            try:
                from config.accounts import AccountManager
                project_config = AccountManager.get_project_config(args.project)
                if project_config:
                    url = project_config.login_page_url or project_config.base_url
                    print(f"📌 使用配置文件中的URL ({args.project}): {url}")
                else:
                    print(f"⚠️ 未找到项目 {args.project} 的配置，请通过 --url 指定")
            except Exception as e:
                print(f"⚠️ 加载配置失败: {e}")

        if not url:
            print("❌ 无法获取录制URL，退出")
            sys.exit(1)

        wrapper = TwoStepRecorder(
            storage_state=args.storage_state,
            har_url_filter=args.har_filter,
        )
        result = wrapper.record(
            module_name=args.module_name,
            target_url=url,
            headless_step2=not args.headed_step2,
        )

        if result:
            print(f"\n📦 录制产物: output/modules/{args.module_name}/")
        else:
            print("❌ 录制失败")
            sys.exit(1)

    # ── replay ──
    elif args.command == "replay":
        module_dir = Path(f"output/modules/{args.module_name}")
        raw_script = module_dir / "raw_script.py"
        if not raw_script.exists():
            print(f"❌ 未找到 raw_script.py: {raw_script}")
            sys.exit(1)

        from recorder.recording_wrapper import TwoStepRecorder
        wrapper = TwoStepRecorder(storage_state=args.storage_state)
        result = wrapper.replay(
            module_name=args.module_name,
            headless=not args.headed,
        )
        if not result or not result.get("har_path"):
            sys.exit(1)

    # ── run ──
    elif args.command == "run":
        from orchestrator.orchestrator import TestChainOrchestrator

        # 解析 --var key=value
        variables = {}
        for v in args.var:
            if "=" in v:
                k, val = v.split("=", 1)
                variables[k.strip()] = val.strip()

        orch = TestChainOrchestrator()
        report = orch.run(
            target_module=args.target_module,
            headed=args.headed,
            variables=variables if variables else None,
            no_heal=args.no_heal,
        )

        if report.get("success"):
            print(f"\n✅ 测试链执行成功!")
        else:
            print(f"\n❌ 测试链执行失败!")
            failed = [r["module"] for r in report.get("results", []) if not r.get("success")]
            if failed:
                print(f"   失败模块: {', '.join(failed)}")
            sys.exit(1)

    # ── compose（查看编排计划，不执行）──
    elif args.command == "compose":
        from orchestrator.graph import TestChainGraph
        from orchestrator.composer import ExecutionPlanComposer
        from knowledge import load_module_definition, list_modules, load_dependency_graph
        from orchestrator.module_definition import ModuleDefinition

        graph = TestChainGraph()

        # 从 knowledge 加载模块到图
        for mod_name in list_modules():
            mod_data = load_module_definition(mod_name)
            if mod_data:
                graph.add_module(ModuleDefinition.from_dict(mod_data))

        # 加载手动依赖关系
        raw_graph = load_dependency_graph()
        for mod_name, deps_list in raw_graph.items():
            for dep in deps_list:
                dep_name = dep["depends_on"] if isinstance(dep, dict) else dep
                var_mapping = dep.get("var_mapping", {}) if isinstance(dep, dict) else {}
                graph.add_dependency(mod_name, dep_name, var_mapping)

        composer = ExecutionPlanComposer()
        plan = composer.compose(args.target_module, graph)
        composer.print_plan(plan)

        if args.save:
            plan_path = Path(args.save)
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(
                json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            print(f"  执行计划已保存: {plan_path}")

    # ── generate-script ──
    elif args.command == "generate-script":
        module_dir = Path(f"output/modules/{args.module_name}")
        raw_script = module_dir / "raw_script.py"
        if not raw_script.exists():
            print(f"❌ 未找到 raw_script.py: {module_dir}")
            sys.exit(1)

        from recorder.script_transformer import HealingScriptTransformer
        transformer = HealingScriptTransformer()

        # 解析 extract_vars
        extract_vars = []
        for v in args.extract_vars:
            parts = v.split(":", 2)
            var_def = {"name": parts[0]}
            if len(parts) > 1:
                var_def["from_api"] = parts[1]
            if len(parts) > 2:
                var_def["from_field"] = parts[2]
            extract_vars.append(var_def)

        enhanced_script = module_dir / "enhanced_script.py"
        transformer.transform(
            input_path=str(raw_script),
            output_path=str(enhanced_script),
            module_name=args.module_name,
            extract_vars=extract_vars,
        )
        print(f"✅ 增强脚本已生成: {enhanced_script}")

    # ── heal ──
    elif args.command == "heal":
        print(f"🩹 手动触发自愈: {args.module_name}")
        script_path = f"output/modules/{args.module_name}/enhanced_script.py"
        if not os.path.exists(script_path):
            script_path = f"output/modules/{args.module_name}/raw_script.py"

        if not os.path.exists(script_path):
            print(f"❌ 未找到脚本: {script_path}")
            sys.exit(1)

        cmd = [
            sys.executable, "-m", "pytest",
            script_path,
            "-x", "-v",
            "--ph-strategy=SMART",
            "--ph-auto-patch-source",
            "--ph-ai-patch-source",
        ]
        if args.headed:
            cmd.append("--headed")

        import subprocess
        subprocess.run(cmd)

    # ── repair（回退优先级策略层）──
    elif args.command == "repair":
        from orchestrator.strategy import FailureRepairOrchestrator, FailureEntry, StrategyDecisionEngine

        report_path = args.report
        if not os.path.exists(report_path):
            print(f"⚠️ 报告文件不存在: {report_path}")
            print(f"   请先运行测试生成失败报告，或指定 --report 路径")
            sys.exit(1)

        if args.dry_run:
            # 仅分析，不执行修复
            with open(report_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            failures = data.get("failures", [])
            if not failures:
                print("✅ 无失败记录")
                sys.exit(0)

            engine = StrategyDecisionEngine()
            entries = [FailureEntry.from_dict(f) for f in failures]
            pairs = engine.decide_batch(entries)

            print(f"\n{'='*60}")
            print(f"🧠 策略分析（Dry Run）— {len(entries)} 个失败")
            print(f"{'='*60}")

            for entry, decision in pairs:
                icon = {
                    "patch_script": "🔧", "replay_verify": "🔄",
                    "re_record": "🎬", "env_fix": "🌐", "skip": "⏭️",
                }.get(decision.strategy.value, "❓")
                print(f"\n  {icon} [{entry.test_name}]")
                print(f"     细分类: {entry.sub_category.value}")
                print(f"     策略: {decision.strategy.value} ({decision.priority.name})")
                print(f"     置信度: {decision.confidence:.0%}")
                print(f"     理由: {decision.reasoning}")
                if decision.fallback_chain:
                    print(f"     回退链: {' → '.join(s.value for s in decision.fallback_chain)}")

            print(f"\n{'='*60}")
            summary = engine.get_decision_summary()
            print(f"📊 汇总: {summary.get('by_strategy', {})}")
        else:
            # 完整执行
            orchestrator = FailureRepairOrchestrator(project_root)
            orchestrator.run(report_path)

    # ── report ──
    elif args.command == "report":
        report_candidates = []
        output_base = Path("output/modules")
        if output_base.exists():
            for module_dir in output_base.iterdir():
                if not module_dir.is_dir():
                    continue
                if args.module and module_dir.name != args.module:
                    continue
                for report_name in ["orchestration_report.json", "assertion_report.json"]:
                    report_path = module_dir / report_name
                    if report_path.exists():
                        report_candidates.append(report_path)

        if not report_candidates:
            print("📊 未找到任何报告。请先运行测试: python3 cli.py run <module>")
            sys.exit(1)

        for rp in sorted(report_candidates):
            print(f"\n{'='*50}")
            print(f"📊 报告: {rp}")
            print(f"{'='*50}")
            try:
                report_data = json.loads(rp.read_text(encoding='utf-8'))
                summary = report_data.get("summary", {})
                if "by_layer" in summary:
                    print(f"   总计: {summary.get('total', '?')}")
                    print(f"   通过: {summary.get('passed', 0)}")
                    print(f"   失败: {summary.get('failed', 0)}")
                    print(f"   跳过: {summary.get('skipped', 0)}")
                    for layer, counts in summary["by_layer"].items():
                        print(f"   {layer.upper()}: ✅{counts.get('passed', 0)} ❌{counts.get('failed', 0)} ⏭️{counts.get('skipped', 0)}")
                elif "results" in report_data:
                    chain = report_data.get("execution_chain", [])
                    print(f"   执行链: {' → '.join(chain)}")
                    for r in report_data.get("results", []):
                        status = "✅" if r.get("success") else "❌"
                        print(f"   {status} {r.get('module', '?')}")
            except Exception as e:
                print(f"   ⚠️ 读取失败: {e}")

    # ── query-knowledge ──
    elif args.command == "query-knowledge":
        from knowledge import load_module_definition, list_modules, load_dependency_graph

        if args.graph:
            # 查看依赖图
            graph = load_dependency_graph()
            if not graph:
                print("📊 依赖图为空（尚未录制模块或推断依赖）")
            else:
                print(f"📊 依赖图:")
                for mod, deps in graph.items():
                    for dep in deps:
                        dep_name = dep["depends_on"] if isinstance(dep, dict) else dep
                        var_map = dep.get("var_mapping", {}) if isinstance(dep, dict) else {}
                        var_str = f" [{', '.join(var_map.keys())}]" if var_map else ""
                        print(f"   {dep_name} → {mod}{var_str}")

        elif args.frontend:
            # 查看前端知识文档
            from knowledge.frontend_loader import FrontendKnowledgeBase
            loader = FrontendKnowledgeBase()
            docs = loader.list_docs()
            if not docs:
                print("📚 未找到前端知识文档")
            else:
                print(f"📚 前端知识文档 ({len(docs)} 份):")
                for doc in docs:
                    content = loader.load_doc(doc)
                    print(f"   - {doc} ({len(content)} 字符)")

        elif args.api:
            # 按 API 路径搜索前端知识
            from knowledge.frontend_loader import FrontendKnowledgeBase
            loader = FrontendKnowledgeBase()
            result = loader.load_for_api(args.api)
            if result:
                print(f"📚 API `{args.api}` 相关知识:")
                print(result[:2000])
            else:
                print(f"📚 未找到与 `{args.api}` 相关的前端知识")

        elif args.module:
            # 查看指定模块定义
            mod_def = load_module_definition(args.module)
            if not mod_def:
                print(f"❌ 未找到模块: {args.module}")
            else:
                print(f"📦 模块定义: {args.module}")
                print(json.dumps(mod_def, ensure_ascii=False, indent=2)[:3000])
        else:
            # 列出所有模块
            modules = list_modules()
            if not modules:
                print("📦 知识库为空（尚未录制任何模块）")
            else:
                print(f"📦 已录制模块 ({len(modules)} 个):")
                for mod_name in modules:
                    mod_def = load_module_definition(mod_name)
                    ops_count = len(mod_def.get("operations", [])) if mod_def else 0
                    api_count = len(mod_def.get("api_calls", [])) if mod_def else 0
                    print(f"   - {mod_name} ({ops_count} UI操作, {api_count} API)")

    # ── list ──
    elif args.command == "list":
        from knowledge import list_modules, load_module_definition

        modules = list_modules()
        if not modules:
            print("📦 尚未录制任何模块")
            print("   运行: python3 cli.py record <module_name> 开始录制")
        else:
            print(f"📦 已录制模块 ({len(modules)} 个):")
            for mod_name in modules:
                mod_def = load_module_definition(mod_name)
                ops_count = len(mod_def.get("operations", [])) if mod_def else 0
                api_count = len(mod_def.get("api_calls", [])) if mod_def else 0
                enhanced = "✅" if mod_def and mod_def.get("enhanced_script") else "⚠️"
                print(f"   {enhanced} {mod_name} ({ops_count} UI, {api_count} API)")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
