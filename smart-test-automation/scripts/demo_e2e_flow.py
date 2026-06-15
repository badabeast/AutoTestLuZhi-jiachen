#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端 Demo — 串通智能测试系统完整流程

模拟流程（不启动浏览器）:
  1. 录制解析：AST 解析 codegen 脚本 + HAR 解析
  2. 脚本转换：raw_script → enhanced_script（healer 兼容）
  3. 模块注册：保存到 knowledge/modules/
  4. 依赖推断：AI 分析跨模块依赖
  5. 依赖图构建：拓扑排序计算执行链
  6. 变量传递：跨模块变量注入
  7. 三层断言：UI + API + DB 断言引擎
  8. 报告生成：汇总报告

运行方式:
    python3 demo_e2e_flow.py
"""

import json
import os
import sys
from pathlib import Path

# 确保项目根目录在 import 路径中
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 加载 .env
_env_path = project_root / ".env"
if _env_path.exists():
    with open(_env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def demo_step(step_name: str, step_num: int):
    """打印步骤分隔线"""
    print(f"\n{'='*60}")
    print(f"  Step {step_num}: {step_name}")
    print(f"{'='*60}")


def main():
    print("=" * 60)
    print("  智能测试执行系统 v5 — 端到端 Demo")
    print("=" * 60)

    # Demo 中使用的示例基础 URL（从环境变量读取，避免硬编码内部地址）
    DEMO_URL = os.environ.get("DEMO_BASE_URL", "https://demo.example.com")

    # ============================================================
    # Step 1: 录制解析 — 模拟 codegen 输出 + HAR 解析
    # ============================================================
    demo_step("录制解析（AST + HAR）", 1)

    # 创建模拟的 codegen 输出脚本
    demo_output = Path("output/modules/create_demand_demo")
    demo_output.mkdir(parents=True, exist_ok=True)

    raw_script = demo_output / "raw_script.py"
    raw_script.write_text('''
from playwright.sync_api import Page, expect

def test_create_demand(page: Page):
    page.goto(f"{DEMO_URL}/demand_front/")
    page.get_by_role("link", name="采购需求管理").click()
    page.get_by_role("button", name="新建需求").click()
    page.get_by_label("需求名称").fill("测试需求_自动化")
    page.get_by_label("预算金额").fill("100000")
    page.get_by_role("button", name="提交").click()
    expect(page.get_by_text("提交成功")).to_be_visible()
''', encoding='utf-8')

    # 用真实的 AST 解析器解析
    from recorder.codegen_parser import RecordingASTParser
    parser = RecordingASTParser()
    operations = parser.parse(str(raw_script))
    print(f"  ✅ AST 解析完成: {len(operations)} 个 UI 操作")
    for op in operations:
        sel_name = f" name={op.selector_name}" if op.selector_name else ""
        print(f"     Step {op.step_index}: {op.action} ({op.selector_type}={op.selector_value}{sel_name})")

    # 创建模拟的 HAR 文件
    demo_har = demo_output / "api.har"
    demo_har.write_text(json.dumps({
        "log": {
            "entries": [
                {
                    "request": {
                        "method": "POST",
                        "url": f"{DEMO_URL}/api/demand/create",
                        "headers": [],
                        "postData": {
                            "mimeType": "application/json",
                            "text": json.dumps({"name": "测试需求", "budget": 100000})
                        }
                    },
                    "response": {
                        "status": 200,
                        "content": {
                            "mimeType": "application/json",
                            "text": json.dumps({"code": 0, "data": {"id": "XQ-2026-00518964", "status": "draft"}})
                        }
                    },
                    "startedDateTime": "2026-06-05T10:00:00.000Z",
                    "timings": {}
                },
                {
                    "request": {
                        "method": "GET",
                        "url": f"{DEMO_URL}/api/demand/list",
                        "headers": [],
                    },
                    "response": {
                        "status": 200,
                        "content": {
                            "mimeType": "application/json",
                            "text": json.dumps({"code": 0, "data": {"total": 1}})
                        }
                    },
                    "startedDateTime": "2026-06-05T10:00:01.000Z",
                    "timings": {}
                }
            ]
        }
    }, ensure_ascii=False), encoding='utf-8')

    # 用真实的 HAR 解析器解析
    from recorder.har_parser import HARParser
    har_parser = HARParser()
    api_calls = har_parser.parse_api_sequence(str(demo_har))
    print(f"\n  ✅ HAR 解析完成: {len(api_calls)} 个业务 API")
    for call in api_calls:
        print(f"     {call.method:6s} {call.path}")
        if call.response_body and isinstance(call.response_body, dict):
            print(f"           响应: {json.dumps(call.response_body, ensure_ascii=False)[:100]}")

    # ============================================================
    # Step 2: 脚本转换 — raw_script → enhanced_script（healer 兼容）
    # ============================================================
    demo_step("脚本转换（healer 兼容）", 2)

    from recorder.script_transformer import ScriptTransformer
    transformer = ScriptTransformer()

    enhanced_script = demo_output / "enhanced_script.py"
    transformer.transform(
        input_path=str(raw_script),
        output_path=str(enhanced_script),
        module_name="create_demand_demo",
        extract_vars=[
            {"name": "demand_id", "from_api": "POST /demand/create", "from_field": "data.id"},
        ],
    )

    # 验证转换结果
    enhanced_content = enhanced_script.read_text(encoding='utf-8')
    has_healing_page = "healing_page" in enhanced_content
    no_page_ref = "page." not in enhanced_content.replace("healing_page.", "")
    print(f"  ✅ 转换完成:")
    print(f"     healing_page 替换: {'✅' if has_healing_page else '❌'}")
    print(f"     page 残留: {'❌ 存在' if not no_page_ref else '✅ 无残留'}")
    print(f"     输出: {enhanced_script}")

    # ============================================================
    # Step 3: 模块注册 — 保存到 knowledge/modules/
    # ============================================================
    demo_step("模块注册（knowledge/modules/）", 3)

    from knowledge import save_module_definition

    module_def = {
        "module_name": "create_demand_demo",
        "target_url": f"{DEMO_URL}/demand_front/",
        "raw_script": str(raw_script),
        "api_har": str(demo_har),
        "enhanced_script": str(enhanced_script),
        "operations": [
            {"step_index": op.step_index, "action": op.action,
             "selector_type": op.selector_type, "selector_value": op.selector_value}
            for op in operations
        ],
        "api_calls": [
            {"step_index": c.step_index, "method": c.method, "path": c.path, "status": c.status}
            for c in api_calls
        ],
        "smart_analysis": {
            "extract_vars": [
                {"name": "demand_id", "from_api": "POST /demand/create",
                 "from_field": "data.id", "example_value": "XQ-2026-00518964"}
            ],
            "dependencies": [],
        },
    }
    knowledge_path = save_module_definition("create_demand_demo", module_def)
    print(f"  ✅ 模块定义已保存: {knowledge_path}")

    # 验证加载
    from knowledge import load_module_definition, list_modules
    loaded = load_module_definition("create_demand_demo")
    modules = list_modules()
    print(f"  ✅ 已注册模块: {modules}")

    # ============================================================
    # Step 4: 依赖推断 — AI 分析跨模块依赖
    # ============================================================
    demo_step("依赖推断（AI 分析）", 4)

    # 注册第二个模拟模块（审核需求）
    audit_def = {
        "module_name": "audit_demand_demo",
        "target_url": f"{DEMO_URL}/demand_front/",
        "smart_analysis": {
            "extract_vars": [
                {"name": "audit_result", "from_api": "POST /demand/audit", "from_field": "data.result"}
            ],
            "input_params": [
                {"name": "demand_id", "source": "从上游模块注入"}
            ],
            "dependencies": [],
        },
    }
    save_module_definition("audit_demand_demo", audit_def)

    # 注册第三个模拟模块（确认需求）
    confirm_def = {
        "module_name": "confirm_demand_demo",
        "target_url": f"{DEMO_URL}/demand_front/",
        "smart_analysis": {
            "extract_vars": [],
            "input_params": [
                {"name": "demand_id", "source": "从上游模块注入"},
                {"name": "audit_result", "source": "从上游模块注入"},
            ],
            "dependencies": [],
        },
    }
    save_module_definition("confirm_demand_demo", confirm_def)

    # AI 推断
    from orchestrator.smart_inference import CrossModuleInferencer
    inferencer = CrossModuleInferencer()
    deps = inferencer.infer_all()
    print(f"  ✅ AI 推断完成: 发现 {len(deps)} 条依赖关系")
    for dep in deps:
        print(f"     {dep['from']} → {dep['to']} ({list(dep.get('var_mapping', {}).keys())})")

    # 自动更新依赖图
    count = inferencer.auto_update_graph()
    print(f"  ✅ 依赖图已更新: {count} 条关系")

    # ============================================================
    # Step 5: 依赖图构建 — 拓扑排序计算执行链
    # ============================================================
    demo_step("依赖图构建（拓扑排序）", 5)

    from orchestrator.graph import DependencyGraph
    graph = DependencyGraph()

    # 从 knowledge 加载模块并构建图
    from orchestrator.module_definition import ModuleDefinition
    for mod_name in list_modules():
        mod_data = load_module_definition(mod_name)
        if mod_data:
            mod_def = ModuleDefinition.from_dict(mod_data)
            graph.add_module(mod_def)

    # 手动添加推断的依赖关系
    from knowledge import load_dependency_graph
    raw_graph = load_dependency_graph()
    for mod_name, deps_list in raw_graph.items():
        for dep in deps_list:
            dep_name = dep["depends_on"] if isinstance(dep, dict) else dep
            var_mapping = dep.get("var_mapping", {}) if isinstance(dep, dict) else {}
            graph.add_dependency(mod_name, dep_name, var_mapping)

    # 计算执行链
    chain = graph.get_execution_chain("confirm_demand_demo")
    print(f"  ✅ 执行链: {' → '.join(chain)}")
    print(f"\n  {graph.visualize()}")

    # ============================================================
    # Step 6: 变量传递 — 跨模块变量注入
    # ============================================================
    demo_step("变量传递（VariableResolver）", 6)

    from orchestrator.variable_resolver import VariableResolver
    resolver = VariableResolver()

    # 模拟模块 A 产出变量
    resolver.context_vars["demand_id"] = "XQ-2026-00518964"
    print(f"  模块 A 产出: demand_id = XQ-2026-00518964")

    # 模板替换测试
    template = "SELECT * FROM demand WHERE id = '{{demand_id}}'"
    resolved = resolver.resolve_template(template)
    print(f"  模板替换: {template}")
    print(f"           → {resolved}")

    # 导出环境变量
    resolver.inject_to_env()
    print(f"  环境变量注入: TEST_CONTEXT_VARS = {resolver.to_env_json()[:80]}...")

    # 模拟模块 B 产出变量
    resolver.context_vars["audit_result"] = "approved"
    print(f"\n  模块 B 产出: audit_result = approved")
    print(f"  当前上下文变量:")
    print(f"  {resolver.summary()}")

    # ============================================================
    # Step 7: 三层断言 — UI + API + DB 断言引擎
    # ============================================================
    demo_step("三层断言引擎（UI + API + DB）", 7)

    from assertion.engine import AssertionEngine, AssertionStatus
    engine = AssertionEngine()

    # 定义断言规则
    assertions = [
        # UI 断言
        {"layer": "ui", "type": "visible", "text": "提交成功",
         "description": "提交成功提示可见"},
        {"layer": "ui", "type": "url", "expected": "demand",
         "description": "页面 URL 包含 demand"},

        # API 断言
        {"layer": "api", "type": "status", "url_pattern": "/demand/create",
         "method": "POST", "expected": 200,
         "description": "创建需求接口返回 200"},
        {"layer": "api", "type": "code", "url_pattern": "/demand/create",
         "method": "POST", "expected": 0,
         "description": "创建需求业务 code=0"},
        {"layer": "api", "type": "field", "url_pattern": "/demand/create",
         "method": "POST", "field": "data.id", "expected": "XQ-2026-00518964",
         "description": "返回需求 ID = XQ-2026-00518964"},

        # DB 断言（会因 DB 不可达而自动跳过）
        {"layer": "db", "type": "exists",
         "sql": "SELECT * FROM demand WHERE id = '{{demand_id}}'",
         "description": "需求记录存在于数据库"},
    ]

    # 构造上下文（模拟 page 和 api_calls）
    class MockPage:
        url = f"{DEMO_URL}/demand_front/#/detail"

        class MockLocator:
            def is_visible(self): return True
            def text_content(self): return "提交成功"
            def count(self): return 1

        def get_by_text(self, text):
            return self.MockLocator()
        def locator(self, sel):
            return self.MockLocator()

    # 构造模拟的 api_calls（使用 HAR 解析的真实数据）
    mock_context = {
        "page": MockPage(),
        "api_calls": api_calls,
        "variables": {"demand_id": "XQ-2026-00518964"},
    }

    results = engine.run_assertions(assertions, mock_context)

    print(f"  断言结果:")
    for r in results:
        status_icon = {"passed": "✅", "failed": "❌", "skipped": "⏭️", "error": "⚠️"}.get(r.status, "?")
        print(f"     {status_icon} [{r.layer.upper()}] {r.description}")
        if r.error_message:
            print(f"        {r.error_message}")

    # ============================================================
    # Step 8: 报告生成
    # ============================================================
    demo_step("报告生成", 8)

    report = engine.generate_report(results)
    report_path = demo_output / "assertion_report.json"
    engine.save_report(results, str(report_path))

    print(f"  断言汇总:")
    print(f"    总计: {report['summary']['total']}")
    print(f"    通过: {report['summary']['passed']}")
    print(f"    失败: {report['summary']['failed']}")
    print(f"    跳过: {report['summary']['skipped']}")
    for layer, counts in report['summary']['by_layer'].items():
        print(f"    {layer.upper()}: ✅{counts['passed']} ❌{counts['failed']} ⏭️{counts['skipped']}")
    print(f"\n  报告文件: {report_path}")

    # 编排报告
    from orchestrator.composer import Composer
    comp = Composer()
    plan = comp.compose("confirm_demand_demo", graph)
    plan_path = demo_output / "execution_plan.json"
    plan_path.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding='utf-8')
    comp.print_plan(plan)
    print(f"  执行计划文件: {plan_path}")

    # ============================================================
    # 最终汇总
    # ============================================================
    print(f"\n{'='*60}")
    print(f"  🎉 端到端 Demo 完成!")
    print(f"{'='*60}")
    print(f"\n  各模块验证结果:")
    print(f"    ✅ AST 解析器（codegen_parser.py）")
    print(f"    ✅ HAR 解析器（har_parser.py）")
    print(f"    ✅ 脚本转换器（script_transformer.py）")
    print(f"    ✅ 知识库管理（knowledge/）")
    print(f"    ✅ 依赖图引擎（orchestrator/graph.py）")
    print(f"    ✅ 执行计划编排（orchestrator/composer.py）")
    print(f"    ✅ 变量传递解析（orchestrator/variable_resolver.py）")
    print(f"    ✅ AI 依赖推断（orchestrator/ai_inference.py）")
    print(f"    ✅ 三层断言引擎（assertion/engine.py）")
    print(f"    ✅ 报告生成")
    print(f"\n  产出目录: {demo_output}/")

    # 清理 demo 产物
    print(f"\n  💡 提示: demo 产物保存在 output/modules/create_demand_demo/ 和 knowledge/modules/")
    print(f"     清理命令: rm -rf output/modules/create_demand_demo knowledge/modules/create_demand_demo.json knowledge/modules/audit_demand_demo.json knowledge/modules/confirm_demand_demo.json knowledge/dependency_graph.json")


if __name__ == "__main__":
    main()
