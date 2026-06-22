# 智能测试自动化系统 — 项目架构与链路功能分析报告

## 一、项目概述

本项目是基于 Playwright 的智能端到端自动化测试系统，核心技术路线为 **两步录制法**：
codegen 录制原始操作 → 回放采集 HAR/Trace → 解析分析 → AI 增强 → 生成自愈兼容脚本。

系统包含 **7 大模块层** 和 **4 条核心链路**，实现从录制、脚本生成、自愈修复、编排执行到三层断言的全链路闭环。

---

## 二、模块架构总览

```
smart-test-automation/
├── cli.py                        # CLI 入口层
├── conftest.py                   # pytest 全局配置层
│
├── core/                         # 核心基础层
│   ├── base_page.py              #   BasePage 页面基类（PO 模式）
│   ├── api_client.py             #   HTTP 客户端封装
│   ├── auth_manager.py           #   全局认证管理器
│   └── locator_error.py          #   定位器异常定义
│
├── recorder/                     # 录制层
│   ├── recording_wrapper.py      #   TwoStepRecorder 录制主流程编排
│   ├── codegen_parser.py         #   AST 解析器（codegen 脚本 → UIOperation）
│   ├── har_parser.py             #   HAR 解析器（HAR → APICall）
│   ├── script_transformer.py     #   脚本转换器（原始 → healer 兼容 + PO 分层）
│   ├── guards.py                 #   通用守卫（重试、超时保护）
│   └── dom_schema_capture.py     #   DOM Schema 采集
│
├── self_healing/                 # 自愈引擎层
│   ├── pipeline.py               #   HealingPipeline 五层递进管线调度
│   ├── cache_matcher.py          #   L1 历史缓存匹配
│   ├── semantic_generator.py     #   L2 语义定位生成
│   ├── dynamic_filter_matcher.py #   L3 动态过滤匹配
│   ├── topology_matcher.py       #   L4 DOM 拓扑匹配
│   ├── iframe_shadow_patcher.py  #   L5 iframe/Shadow DOM 穿透
│   ├── ai_healer.py              #   L6 AI 兜底修复
│   ├── monkey_patch_page.py      #   MonkeyPatchPage（拦截 Page 定位方法）
│   ├── source_patcher.py         #   源码回写修复
│   ├── strict_violation_healer.py#   strict mode violation 修复
│   ├── candidate_evaluator.py    #   候选评分器
│   ├── selector_parser.py        #   选择器解析器
│   ├── component_detector.py     #   UI 组件库检测
│   ├── component_manager.py      #   组件库管理器
│   ├── component_profile.py      #   组件库配置
│   ├── dom_trimmer.py            #   DOM 裁剪优化
│   └── healer_config.py          #   自愈配置
│
├── scheduler/                    # 编排引擎层
│   ├── orchestrator.py           #   TestChainOrchestrator 编排主引擎
│   ├── graph.py                  #   TestChainGraph 依赖图引擎
│   ├── composer.py               #   ExecutionPlanComposer 执行计划编排
│   ├── variable_resolver.py      #   CrossModuleVariableBridge 变量传递
│   ├── smart_inference.py        #   CrossModuleInferencer 智能依赖推断
│   ├── strategy.py               #   FailureRepairOrchestrator 回退策略层
│   └── module_definition.py      #   ModuleDefinition 模块定义模型
│
├── assertion/                    # 断言引擎层
│   ├── engine.py                 #   ThreeLayerAssertionEngine 三层断言统一入口
│   ├── ui_assertion.py           #   UI 层断言
│   ├── api_assertion.py          #   API 层断言
│   ├── db_assertion.py           #   DB 层断言
│   ├── assertion_rule.py         #   AssertionResult/Rule 数据模型
│   └── report.py                 #   断言报告生成
│
├── api_test_generator/           # 接口用例生成层
│   ├── param_chain_analyzer.py   #   ParamChainAnalyzer 参数传递链分析
│   ├── ai_reviewer.py            #   ParamChainReviewer AI 二次校验
│   ├── timeline_mapper.py        #   TimelineMapper UI↔API 时间线映射
│   ├── test_script_generator.py  #   TestScriptGenerator pytest 脚本生成
│   ├── incremental_maintainer.py #   IncrementalMaintainer 增量维护
│   ├── models.py                 #   数据模型（UIOperation/ParamChain/APIStep 等）
│   ├── config.py                 #   APIGeneratorConfig 配置
│   └── utils.py                  #   工具函数（JSON 字段提取、值匹配等）
│
├── ai/                           # AI 分析层
│   ├── provider.py               #   OpenAICompatibleProvider 多模型适配
│   ├── dependency_analyzer.py    #   AI 依赖分析器
│   └── models_config.json        #   模型配置文件
│
├── login/                        # 登录管理层
│   ├── auto_login.py             #   自动登录
│   ├── refresh_login_state.py    #   登录态刷新与有效性校验
│   └── save_login_state.py       #   手动登录保存 storage_state
│
├── config/                       # 配置管理层
│   ├── accounts.py               #   AccountManager 测试账号与项目配置
│   ├── env_loader.py             #   .env 文件加载
│   └── test_config.py            #   测试配置
│
├── pages/                        # 业务 Page Object 层
│   └── demand_form_page.py       #   需求单表单 Page
│
├── scripts/                      # 辅助脚本
│   ├── heal_runner.py            #   自愈运行器
│   ├── verify_healer.py          #   自愈验证器
│   └── demo_e2e_flow.py          #   端到端流程演示
│
└── knowledge/                    # 知识库（录制产物存储）
    ├── modules/                  #   各模块定义 JSON
    └── frontend_docs/            #   前端知识文档
```

---

## 三、7 大模块层职责

| 层级 | 模块 | 核心类 | 职责 |
|------|------|--------|------|
| **1. CLI 入口** | `cli.py` | — | 提供 record/replay/run/compose/heal/repair/report 等子命令 |
| **2. 核心基础** | `core/` | `BasePage`, `APIClient`, `AuthManager` | PO 基类、HTTP 封装、认证管理、异常定义 |
| **3. 录制层** | `recorder/` | `TwoStepRecorder`, `RecordingASTParser`, `HARParser`, `HealingScriptTransformer` | 两步录制、AST 解析、HAR 解析、脚本转换 |
| **4. 自愈引擎** | `self_healing/` | `HealingPipeline`, `MonkeyPatchPage`, `SourcePatcher` | 五层递进自愈 + AI 兜底、选择器回写、strict violation 修复 |
| **5. 编排引擎** | `scheduler/` | `TestChainOrchestrator`, `TestChainGraph`, `ExecutionPlanComposer`, `CrossModuleInferencer` | 依赖图拓扑排序、执行计划、变量传递、智能推断、回退策略 |
| **6. 断言引擎** | `assertion/` | `ThreeLayerAssertionEngine` | UI/API/DB 三层断言 + 报告生成 |
| **7. AI 分析** | `ai/` | `OpenAICompatibleProvider` | 多模型适配（GLM/DeepSeek/Qwen/MiniMax）、依赖分析 |

---

## 四、4 条核心链路

### 链路 1：录制流程（两步录制法）

```
用户操作浏览器
    │
    ▼
[Step 1] codegen 录制 → 生成 raw_script.py
    │
    ▼
[Step 2] 自动回放 + HAR/Trace 采集
    │
    ├── raw_script.py (codegen 原始脚本)
    ├── api.har       (HTTP 归档)
    └── trace.zip     (Playwright Trace)
    │
    ▼
[Step 3] 产物解析
    ├── RecordingASTParser → UIOperation 列表（UI 操作）
    └── HARParser → APICall 列表（业务 API，已过滤静态资源）
    │
    ▼
[Step 4] 智能分析
    ├── TimelineMapper        → UI 操作 ↔ API 调用时间线映射
    ├── ParamChainAnalyzer    → 响应→请求参数传递链（规则引擎）
    ├── 跨模块依赖推断         → CrossModuleInferencer 三级推断
    └── ParamChainReviewer    → AI 二次校验（去误报 + 补漏）
    │
    ▼
[Step 5] 脚本生成
    ├── HealingScriptTransformer → enhanced_script.py（healer 兼容格式）
    └── PO 分层 → pages/ + scripts/ + test_ 用例
    │
    ▼
[Step 6] 知识库存储 → knowledge/modules/<module_name>.json
```

**关键文件调用链**：
`cli.py (record)` → `TwoStepRecorder.record()` → `RecordingASTParser.parse()` → `HARParser.parse_api_sequence()` → `ParamChainAnalyzer.analyze_chains()` → `ParamChainReviewer.review()` → `HealingScriptTransformer.transform()`

---

### 链路 2：编排执行流程

```
用户执行: cli.py run <target_module>
    │
    ▼
[1] 加载知识库
    ├── list_modules() → 遍历所有已录制模块
    └── load_module_definition() → 加载每个模块定义
    │
    ▼
[2] 构建依赖图
    ├── TestChainGraph.add_module() → 注册模块 + 产出变量
    ├── TestChainGraph.add_dependency() → 添加依赖边
    └── 自动推断：模块所需参数名 == 已有模块产出变量名 → 建边
    │
    ▼
[3] 拓扑排序
    └── ExecutionPlanComposer.compose()
        ├── graph.get_execution_chain(target) → DFS 拓扑排序
        └── 生成 ExecutionPlan（chain + steps + needs + produces）
        │
        示例: run confirm_demand
        → chain: ["create_demand", "audit_demand", "confirm_demand"]
    │
    ▼
[4] 逐模块执行
    for step in plan.steps:
        │
        ├── resolver.inject_to_env()
        │   └── 设置 TEST_CONTEXT_VARS 环境变量
        │
        ├── _execute_module(script_path)
        │   └── subprocess: pytest <script> --ph-strategy=SMART --ph-auto-patch-source
        │
        ├── 失败检查自愈
        │   └── _check_heal_result() → 查 heal_log.json
        │       ├── 修复成功 → 标记 healed=True，继续
        │       └── 修复失败 → break 终止链路
        │
        ├── resolver.extract_from_module_result()
        │   └── 读取 extracted_vars.json → 写入 context_vars
        │
        └── 三层断言
            └── ThreeLayerAssertionEngine.run_assertions()
                ├── API 断言: status code 校验
                ├── UI 断言: 页面元素检查
                └── DB 断言: 数据库状态验证
    │
    ▼
[5] 汇总报告 → orchestration_report.json
```

**关键文件调用链**：
`cli.py (run)` → `TestChainOrchestrator.run()` → `TestChainGraph.get_execution_chain()` → `ExecutionPlanComposer.compose()` → `_execute_module()` → `ThreeLayerAssertionEngine.run_assertions()`

---

### 链路 3：自愈修复流程

```
pytest 执行测试脚本
    │
    ▼
MonkeyPatchPage 拦截 Page 定位方法
    └── page.get_by_role() → 返回 HealingLocator
        └── HealingLocator.click() / .fill() 失败时
            └── 捕获异常 → 触发 HealingPipeline
    │
    ▼
HealingPipeline.heal(selector, error_context)
    │
    ├── L1: CacheMatcher — 查历史修复缓存
    │   └── 命中 → 直接返回修复后的选择器
    │
    ├── L2: SemanticGenerator — 语义定位
    │   └── 根据文本/role/placeholder 生成候选
    │
    ├── L3: DynamicFilterMatcher — 动态属性过滤
    │   └── 排除动态 ID/class，用稳定属性匹配
    │
    ├── L4: TopologyMatcher — DOM 拓扑匹配
    │   └── 基于 DOM 树结构关系定位
    │
    ├── L5: IframeShadowPatcher — iframe/Shadow DOM 穿透
    │   └── 检测并处理 iframe 和 Shadow DOM 边界
    │
    └── L6: AIHealer — AI 兜底（全挂才调 AI）
        └── 截取 DOM 快照 + 错误上下文 → AI 推断新选择器
    │
    ▼
CandidateEvaluator — 所有层的候选统一评分
    └── 取最优候选 → SourcePatcher 回写源码
    │
    ▼
回写成功后：
    ├── 更新 L1 缓存（下次同选择器直接命中）
    └── 写入 heal_log.json（供编排引擎检查修复状态）
```

**关键文件调用链**：
`MonkeyPatchPage` → `HealingLocator` 异常 → `HealingPipeline.heal()` → L1~L6 → `CandidateEvaluator.score()` → `SourcePatcher.patch()`

---

### 链路 4：登录态管理

```
[录制前]
    │
    ├── 检查 storage_state.json 是否存在
    │   ├── 存在 → codegen --load-storage 自动带登录态
    │   └── 不存在 → 提示用户手动登录
    │
    ▼
[首次录制]
    └── 用户手动登录 → save_login_state.py 保存 storage_state.json
        └── 包含 cookies + localStorage（expires=-1 → 清洗为 7 天后）
    │
    ▼
[后续录制/回放]
    ├── conftest._sanitize_storage_state() → 清洗 expires=-1 cookie
    ├── login_state_health_check → session 级 fixture 验证登录态有效性
    │   ├── 有效 → 继续
    │   └── 失效 → refresh_login_state.py 刷新
    │       ├── 刷新成功 → 更新 storage_state.json
    │       └── 刷新失败 → 提示重新登录
    │
    ▼
[执行阶段]
    └── 编排引擎执行模块时
        ├── 登录态有效 → 正常执行
        └── 登录态失效 → strategy.py 识别为 ENV_AUTH → env_fix 策略 → 自动刷新
```

**关键文件调用链**：
`conftest.py` → `_sanitize_storage_state()` → `login_state_health_check` fixture → `refresh_login_state.refresh()` → `save_login_state.save()`

---

## 五、核心数据结构

### 5.1 录制产物

| 产物 | 格式 | 来源 | 用途 |
|------|------|------|------|
| `raw_script.py` | Python | codegen 录制 | 原始操作脚本 |
| `enhanced_script.py` | Python | script_transformer 转换 | healer 兼容 + PO 分层脚本 |
| `api.har` | HAR JSON | Step2 回放采集 | HTTP 归档（业务 API） |
| `trace.zip` | Trace | Step2 回放采集 | Playwright Trace 调试 |
| `extracted_vars.json` | JSON | 运行时变量提取 | 跨模块变量传递 |
| `assertion_report.json` | JSON | 断言引擎 | 三层断言结果 |
| `orchestration_report.json` | JSON | 编排引擎 | 执行链结果 |
| `knowledge/modules/*.json` | JSON | 录制完成时存储 | 模块定义（操作、API、变量、依赖） |

### 5.2 关键数据模型

| 模型 | 文件 | 字段 |
|------|------|------|
| `UIOperation` | `models.py` | step_index, action, selector_type, selector_value, value, raw_line |
| `APICall` | `har_parser.py` | method, url, path, request_headers/body, status, response_headers/body, timing |
| `ParamChain` | `models.py` | source_api, source_field, source_example, target_api, target_field, chain_type, confidence |
| `TimelineMapping` | `models.py` | ui_operation, api_calls, time_range, confidence |
| `APIStep` | `models.py` | step_index, method, url, headers, body, extract_vars, depends_on |
| `ModuleDefinition` | `module_definition.py` | id, operations, api_calls, extract_variables, required_params |
| `ExecutionPlan` | `composer.py` | target, chain, steps, variables |
| `HealingResult` | `pipeline.py` | original_selector, healed_selector, confidence, source_level, verified |

---

## 六、模块间依赖关系

```
                    ┌──────────┐
                    │  cli.py  │ ← 用户入口
                    └────┬─────┘
           ┌─────────────┼─────────────┐
           ▼             ▼             ▼
    ┌──────────┐  ┌────────────┐  ┌──────────┐
    │ recorder │  │ scheduler  │  │  heal    │
    └────┬─────┘  └─────┬──────┘  └────┬─────┘
         │              │              │
    ┌────┴────┐   ┌─────┴──────┐  ┌───┴────────┐
    │api_test │   │ assertion  │  │self_healing│
    │generator│   └────────────┘  └───┬────────┘
    └────┬────┘                       │
         │                            │
         ▼                            ▼
    ┌─────────┐                  ┌──────────┐
    │   ai    │                  │   ai     │
    └─────────┘                  └──────────┘
         │                            │
         ▼                            ▼
    ┌─────────────────────────────────────┐
    │              config/                │
    │    (env_loader, accounts)           │
    └─────────────────────────────────────┘
```

---

## 七、技术亮点总结

| 特性 | 实现方式 | 价值 |
|------|---------|------|
| **两步录制法** | codegen 录制 + 回放采 HAR/Trace + 解析 | 无侵入式录制，分离操作与网络数据 |
| **五层递进自愈** | L1 缓存→L2 语义→L3 过滤→L4 拓扑→L5 穿透→L6 AI | 规则优先省 token，全挂了才调 AI |
| **MonkeyPatchPage** | 拦截 Playwright Page 所有定位方法 | 无需修改业务代码即实现统一错误捕获 |
| **拓扑排序编排** | 依赖图 + DFS 拓扑排序 + 跨模块变量传递 | 自动计算前置执行链，变量自动注入 |
| **三层断言** | UI + API + DB 统一断言引擎 | 多维度验证，报告分层展示 |
| **智能依赖推断** | 三级策略：精确名→相似度→AI 仲裁 | 新模块录制后自动推断跨模块依赖 |
| **回退策略层** | 分类→策略决策→执行→回退链 | 修复失败自动降级，最大化自愈率 |
| **多模型 AI 适配** | OpenAI 兼容协议（GLM/DeepSeek/Qwen/MiniMax） | AI 服务可切换，不绑定单一供应商 |
| **增量维护** | API diff + 链合并 + 置信度衰减 | 重复录制只更新差异，链稳定性递增 |
