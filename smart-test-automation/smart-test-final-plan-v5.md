# 智能测试执行系统 — 最终落地方案（v5 Final）

> 融合两版方案最优决策 + 零前端配合约束，8-10 个工作日交付核心能力

---

## 一、一句话定位

人工录制模块操作 → AI 自动推断依赖关系 → 自动编排前置链 → 三层断言验证 → healer 自愈保障稳定性 → Skill 斜杠命令对外服务

---

## 二、核心原则

**数据获取交给开源框架，智慧层我们构建**

| 层 | 职责 | 用什么 | 来源 |
|---|------|--------|------|
| 数据获取层 | UI 录制、API 捕获、执行回溯 | Playwright codegen + HAR + Trace | Playwright 内置 |
| 自愈层 | 选择器失效自动修复 | playwright-healer（4级策略链） | pip install |
| 智慧层 | 依赖编排、三层断言、AI推断 | 自建 | Python |
| 复用层 | 账号、登录态、AI Provider | project3 已验证模块 | 复制 |
| 辅助层 | 浏览器实时操控调试 | Playwright MCP Server | 可选 |

---

## 三、5 个开源框架的职责

| 框架 | 做什么 | 不做什么 |
|------|--------|---------|
| Playwright codegen | 录制 UI 操作 + 生成精准选择器（role→text→css） | 不录制 API |
| Playwright HAR | 完整捕获所有 API 请求/响应（标准 JSON，零遗漏） | 不生成 UI 选择器 |
| Playwright Trace | DOM 快照 + 截图 + 网络时间线（执行回溯） | 不独立使用，辅助调试 |
| playwright-healer | 选择器失效时自动修复（属性→文本→结构→AI语义 4级） | 不录制、不编排 |
| Playwright MCP | Claude Code 直接操控浏览器（辅助调试/自愈验证） | 不替代整个系统 |

---

## 四、从 project3 复用什么、抛弃什么

### ✅ 复用（实战可靠）

| 文件 | 作用 |
|------|------|
| config/accounts.py | 账号管理（AccountManager） |
| config/test_config.py | 环境配置 |
| core/api_client.py | API 客户端 + AuthClient |
| core/auth_manager.py | 认证状态管理 |
| ai/provider.py | AI Provider（DeepSeek/GLM/Qwen/Ollama） |
| ai/models_config.json | 模型配置 |
| ai/dependency_analyzer.py | AI 依赖推断（已有，增强） |
| save_login_state.py | 登录态保存工具 |
| login_state/storage_state.json | 登录态文件 |
| .env | 环境变量 |

### ❌ 抛弃（问题根源，不再使用）

| 模块 | 原因 |
|------|------|
| playwright_recorder/ 整个目录 | UIListener JS注入不稳定、APICapturer 漏请求 |
| api_analyzer/ 目录 | HAR 解析替代 |
| models/data_models.py | 重写简化 |
| fixtures/ | 不用 Pytest fixture 模式 |
| tests/ | 重写 |

---

## 五、系统架构

```
┌─────────────────────────────────────────────────────────────┐
│             用户交互层                                        │
│  CLI: record / run / heal / report / compose                │
│  Skill: /record-module /run-test /self-heal /assert-report  │
├─────────────────────────────────────────────────────────────┤
│             智慧编排引擎 (Orchestrator)                        │
│  依赖图(AI推断) → 前置链 → 变量传递 → 三层断言编排             │
├──────────┬──────────┬──────────┬──────────┬────────────────┤
│ 数据获取  │ 自愈机制  │ 三层断言  │ AI 分析  │ 知识管理       │
│ (开源框架)│ (开源框架) │ (自建)   │ (复用P3) │ (渐进式)      │
│          │          │          │          │               │
│ codegen  │ healer   │ UI断言   │ 依赖推断  │ healer        │
│ HAR录制  │ 4级策略链 │ API断言  │ 变量提取  │  SelectorStore│
│ Trace    │          │ DB断言   │ 参数推断  │ 依赖图JSON    │
│          │          │          │          │ 模块定义JSON  │
├──────────┴──────────┴──────────┴──────────┴────────────────┤
│             复用层 (from project3)                            │
│  config/accounts + core/auth + core/api + ai/provider       │
│  + save_login_state + login_state/ + .env                   │
├─────────────────────────────────────────────────────────────┤
│             辅助层（可选）                                     │
│  Playwright MCP → Claude Code 实时操控浏览器（调试/验证）      │
└─────────────────────────────────────────────────────────────┘
```

---

## 六、核心工作流

### 6.1 模块录制流程（两步录制法）

```
用户: python3 cli.py record create_demand "创建采购需求"
  │
  ├─ Step 1: 启动 codegen 录制（用户手动操作）
  │   python3 -m playwright codegen \
  │     --target=python-pytest \
  │     --load-storage=login_state/storage_state.json \
  │     --viewport-size=1366,768 \
  │     --output=output/modules/create_demand/raw_script.py \
  │     https://www.test.zcygov.cn/demand_front/
  │
  │   用户在浏览器中手动操作完整流程
  │   关闭浏览器 → 保存 raw_script.py
  │   ✅ 产出: raw_script.py（含 Playwright 推荐的最佳选择器）
  │
  ├─ Step 2: 自动回放 + HAR + Trace（无人值守）
  │   RecordingWrapper 自动执行:
  │   1. 包装 raw_script.py → 注入 HAR/Trace 上下文
  │   2. browser.new_context(
  │        storage_state=...,
  │        record_har_path="output/.../api.har",
  │        record_har_url_filter="**/api/**",
  │        record_har_content="embed"
  │      )
  │   3. context.tracing.start(screenshots=True, snapshots=True)
  │   4. 执行 raw_script.py 每一步操作
  │   5. context.tracing.stop(path="trace.zip")
  │   6. context.close()  # 必须 close 才保存 HAR
  │
  │   ✅ 产出: api.har（完整 API 数据）+ trace.zip（执行回溯）
  │
  ├─ Step 3: 解析产物
  │   a. CodegenScriptParser(ast) → UIOperation 列表
  │   b. HARParser(json.load) → APICall 列表
  │   c. 时间对齐：UI 操作和 API 请求按时间戳关联
  │
  ├─ Step 4: AI 分析
  │   a. 从 API 响应推断提取变量（demand_id 等）
  │   b. 从 API 请求推断所需参数（哪些外部传入）
  │   c. 对比已录制模块 → 推断依赖关系
  │
  ├─ Step 5: 生成增强脚本
  │   a. raw_script.py → healer 兼容（page → healing_page）
  │   b. 注入三层断言（AI 根据操作语义自动生成）
  │   c. 变量模板替换（{{demand_id}} 等）
  │
  └─ Step 6: 保存模块定义
      knowledge/modules/create_demand.json
```

### 6.2 测试编排与执行流程

```
用户: python3 cli.py run confirm_demand
  │
  ├─ Step 1: 查询依赖图 → 前置链
  │   confirm_demand 依赖 → audit_demand 依赖 → create_demand
  │   执行顺序: create_demand → audit_demand → confirm_demand
  │
  ├─ Step 2: 逐模块执行 + 自愈 + 三层断言 + 变量传递
  │
  │   ┌─ Module A: create_demand ────────────────────────┐
  │   │  1. pytest output/modules/create_demand/enhanced_script.py │
  │   │  2. healing_page 自动处理选择器失效（4级策略链）    │
  │   │  3. 三层断言:                                     │
  │   │     ├─ UI: "提交成功" 提示可见                      │
  │   │     ├─ API: POST /demand/create → 200, code:0      │
  │   │     └─ DB: SELECT * FROM demand WHERE id={{id}}     │
  │   │         → status='draft'（DB不可达则跳过）           │
  │   │  4. 提取变量: demand_id = "XQ-2026-00518964"        │
  │   └──────────────────────────────────────────────────┘
  │   ↓ 变量传递: demand_id
  │   ┌─ Module B: audit_demand ────────────────────────────┐
  │   │  1. 注入 demand_id → enhanced_script 执行             │
  │   │  2. 自愈 + 三层断言                                   │
  │   │  3. 提取变量: audit_result = "approved"                │
  │   └──────────────────────────────────────────────────┘
  │   ↓ 变量传递: demand_id + audit_result
  │   ┌─ Module C: confirm_demand ──────────────────────────┐
  │   │  1. 注入变量 → 执行 → 三层断言                        │
  │   │  2. 最终验证: 全链路数据一致性                          │
  │   └──────────────────────────────────────────────────┘
  │
  └─ Step 3: 汇总断言报告
```

### 6.3 自愈流程（4 级策略链）

```
UI 脚本执行 → 选择器失效（TimeoutError / ElementNotFound）
  │
  ├─ L1: healer 内置缓存
  │   从历史修复记录查找 → 命中则直接替换执行
  │   ↓ 未命中
  ├─ L2: healer 启发式修复
  │   同义文本替换 / 相似属性 / 临近元素
  │   ↓ 未命中
  ├─ L3: healer DOM 结构匹配
  │   Levenshtein 文本距离 / accessibility tree 匹配（rapidfuzz）
  │   ↓ 未命中
  ├─ L4: healer AI 语义匹配（DeepSeek/GLM/Qwen）
  │   DOM 片段 + 语义描述 → AI 返回新选择器 → 验证 → 写回源码
  │   ↓ 未命中
  └─ 全部失败 → healing-report.json 记录 → 人工介入
```

---

## 七、选择器稳定性策略（零前端配合方案）

### 7.1 现实约束

❌ 推动前端补 `data-testid` — 不现实，前端永远有更优先的需求

### 7.2 实际可用的三层保险

```
层级1（80% 场景）：codegen 生成的 role/text 选择器
  → page.get_by_role('button', name='提交')
  → page.get_by_text('待我审批')
  → 按钮文案不会随便改，改了就是需求变更

层级2（15% 场景）：选择器失效 → playwright-healer 自动修复
  → 4 级策略链自动修复
  → 修复后写回源码，下次直接用

层级3（ 5% 场景）：healer 修不了 → 人工看 Trace 手动调
  → npx playwright show-trace trace.zip
  → 找到新选择器，手动更新脚本
```

### 7.3 前端唯一需要知道的约定

不是加 testid，而是：**按钮文案变更时通知 QA**。

| 前端改动类型 | 自动化影响 | healer 能否兜底 | 是否需要通知 QA |
|------------|-----------|----------------|----------------|
| CSS class 重构 | 不影响 role/text | — | ❌ |
| 按钮位置移动 | 不影响 role/text | — | ❌ |
| "提交" → "确认提交" | 脚本断掉 | ✅ healer L2 修复 | 建议 |
| 新增弹窗/页面 | 需补录 | — | ✅ 需要 |
| 组件库升级 | class 全变 | ✅ healer L3/L4 | ❌ |
| 整页重构 | 选择器全废 | ⚠️ 看情况 | ✅ 必须 |

### 7.4 如果未来前端愿意配合（加分项，不是前提）

| 操作 | 成本 | 收益 | 优先级 |
|------|------|------|--------|
| 关键按钮加 `data-testid` | 每个元素一行代码 | 选择器永不失效 | P1 推荐 |
| 提供路由表 | 导出一份 JS | 录制导航优化 | P2 |
| 提供 API 定义 | 导出接口列表 | 补充 HAR 盲区 | P2 |

---

## 八、详细模块设计

### 8.1 数据获取层 (recorder/)

#### 8.1.1 CodegenScriptParser

```python
# recorder/codegen_parser.py

import ast
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class UIOperation:
    step_index: int
    action: str                  # click / fill / select / navigate / press / check
    selector_type: str           # role / text / label / placeholder / css
    selector_value: str          # 选择器参数
    value: Optional[str] = None  # fill 值 / select 选项
    raw_line: str = ""           # 原始代码行（用于修补）

class CodegenScriptParser:
    """用 AST 解析 Playwright codegen 生成的 Python-pytest 脚本"""
    
    SELECTOR_MAP = {
        "get_by_role": "role",
        "get_by_text": "text",
        "get_by_test_id": "test_id",
        "get_by_label": "label",
        "get_by_placeholder": "placeholder",
        "locator": "css",
    }
    
    ACTION_MAP = {
        "click": "click",
        "fill": "fill",
        "select_option": "select",
        "check": "check",
        "press": "press",
        "goto": "navigate",
    }
    
    def parse(self, script_path: str) -> List[UIOperation]:
        with open(script_path, 'r') as f:
            source = f.read()
        tree = ast.parse(source)
        
        operations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                op = self._parse_call_chain(node)
                if op:
                    op.step_index = len(operations)
                    op.raw_line = ast.get_source_segment(source, node) or ""
                    operations.append(op)
        return operations
    
    def _parse_call_chain(self, node: ast.Call) -> Optional[UIOperation]:
        """解析 page.get_by_xxx().action() 调用链"""
        ...
```

#### 8.1.2 HARParser

```python
# recorder/har_parser.py

import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from urllib.parse import urlparse

@dataclass
class APICall:
    step_index: int
    method: str
    url: str
    path: str
    request_headers: Dict = field(default_factory=dict)
    request_body: Optional[Dict] = None
    status: int
    response_headers: Dict = field(default_factory=dict)
    response_body: Optional[Dict] = None
    mime_type: str = ""
    timing: Dict = field(default_factory=dict)
    timestamp: str = ""

class HARParser:
    """直接用 json.load 解析 HAR 1.2 标准文件，不依赖 haralyzer"""
    
    def __init__(self, url_filter: str = None):
        self.url_filter = url_filter
    
    def parse(self, har_path: str) -> List[APICall]:
        with open(har_path, 'r', encoding='utf-8') as f:
            har = json.load(f)
        
        calls = []
        for i, entry in enumerate(har["log"]["entries"]):
            req = entry["request"]
            res = entry["response"]
            url = req["url"]
            
            if self.url_filter and not self._match(url):
                continue
            
            calls.append(APICall(
                step_index=i,
                method=req["method"],
                url=url,
                path=urlparse(url).path,
                request_headers={h["name"]: h["value"] for h in req.get("headers", [])},
                request_body=self._parse_body(req.get("postData")),
                status=res["status"],
                response_headers={h["name"]: h["value"] for h in res.get("headers", [])},
                response_body=self._parse_content(res.get("content", {})),
                mime_type=res.get("content", {}).get("mimeType", ""),
                timing=entry.get("timings", {}),
                timestamp=entry.get("startedDateTime", "")
            ))
        return calls
    
    def _parse_body(self, post_data) -> Optional[Dict]:
        if not post_data:
            return None
        text = post_data.get("text", "")
        mime = post_data.get("mimeType", "")
        if "json" in mime:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"_raw": text}
        return {"_raw": text[:2000], "_mime": mime}
    
    def _parse_content(self, content: dict) -> Optional[Dict]:
        text = content.get("text", "")
        if not text:
            return None
        mime = content.get("mimeType", "")
        if "json" in mime:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"_raw": text[:5000]}
        return None
    
    def _match(self, url: str) -> bool:
        if not self.url_filter:
            return True
        pattern = self.url_filter.replace("**", "*").replace("*", "")
        return pattern in url
```

#### 8.1.3 RecordingWrapper

```python
# recorder/recording_wrapper.py

import subprocess
import sys
from pathlib import Path

class RecordingWrapper:
    """编排两步录制流程
    
    Step 1: codegen 录制 UI（用户手动操作）
    Step 2: 回放 + HAR + Trace（自动，无人值守）
    """
    
    def record(self, module_name: str, target_url: str,
               storage_state: str = "login_state/storage_state.json",
               har_url_filter: str = "**/api/**"):
        
        output_dir = Path(f"output/modules/{module_name}")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # ===== Step 1: codegen 录制 =====
        raw_script = output_dir / "raw_script.py"
        print(f"🎬 Step 1: 启动 codegen 录制...")
        print(f"   请在浏览器中完成 [{module_name}] 的全部操作")
        print(f"   操作完成后关闭浏览器即可\n")
        
        cmd = [
            sys.executable, "-m", "playwright", "codegen",
            "--target=python-pytest",
            f"--output={raw_script}",
            f"--load-storage={storage_state}",
            "--viewport-size=1366,768",
            target_url,
        ]
        subprocess.run(cmd)  # 阻塞直到用户关闭浏览器
        
        if not raw_script.exists():
            print("❌ codegen 未生成脚本，退出")
            return None
        
        print(f"\n✅ Step 1 完成: {raw_script}")
        
        # ===== Step 2: 回放 + HAR + Trace =====
        api_har = output_dir / "api.har"
        trace_file = output_dir / "trace.zip"
        
        print(f"\n🔄 Step 2: 自动回放 + HAR + Trace 录制...")
        
        wrapper_script = self._generate_wrapper(
            raw_script=str(raw_script),
            har_path=str(api_har),
            trace_path=str(trace_file),
            storage_state=storage_state,
            har_url_filter=har_url_filter,
        )
        
        result = subprocess.run(
            [sys.executable, "-m", "pytest", wrapper_script, "-x", "-v"],
            capture_output=True, text=True
        )
        
        if api_har.exists():
            print(f"✅ Step 2 完成: {api_har}")
        else:
            print(f"⚠️ HAR 文件未生成，可能回放失败")
        
        return {
            "raw_script": str(raw_script),
            "api_har": str(api_har) if api_har.exists() else None,
            "trace": str(trace_file) if trace_file.exists() else None,
        }
    
    def _generate_wrapper(self, raw_script, har_path, trace_path,
                          storage_state, har_url_filter):
        """生成临时 wrapper 脚本，注入 HAR + Trace 上下文"""
        wrapper = Path(raw_script).parent / "_wrapper_recording.py"
        wrapper.write_text(f'''
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

def test_record_har_trace():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state="{storage_state}",
            record_har_path="{har_path}",
            record_har_url_filter="{har_url_filter}",
            record_har_content="embed",
            viewport={{"width": 1366, "height": 768}}
        )
        context.tracing.start(screenshots=True, snapshots=True)
        
        page = context.new_page()
        
        # 动态导入并执行 raw_script 的操作
        import importlib.util
        spec = importlib.util.spec_from_file_location("raw", "{raw_script}")
        raw = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(raw)
        for name in dir(raw):
            if name.startswith("test_"):
                getattr(raw, name)(page)
                break
        
        context.tracing.stop(path="{trace_path}")
        context.close()  # 必须 close 才保存 HAR
        browser.close()
''')
        return str(wrapper)
```

#### 8.1.4 ScriptTransformer

```python
# recorder/script_transformer.py

import re

class ScriptTransformer:
    """将 codegen 输出转换为 playwright-healer 兼容格式
    
    核心转换:
    1. page → healing_page (healer 自注册 fixture)
    2. 类型注解 Page → 删除
    3. 注入断言桩（AI 后续填充）
    """
    
    def transform(self, input_path: str, output_path: str,
                  module_name: str = "",
                  extract_vars: list = None):
        with open(input_path, 'r') as f:
            source = f.read()
        
        # 1. 替换 page 参数为 healing_page
        source = re.sub(
            r'def (test_\w+)\(page:\s*Page\)',
            r'def \1(healing_page)',
            source
        )
        
        # 2. 替换所有 page. → healing_page.
        source = source.replace('page.', 'healing_page.')
        
        # 3. 添加文件头注释
        header = f'''"""
Auto-generated by smart-test-automation
Module: {module_name}
Self-healing enabled via playwright-healer (healing_page fixture)
选择器策略: role > text > label > css (codegen 原生策略)
若选择器失效, healer 4级策略链自动修复
"""

'''
        source = header + source
        
        # 4. 注入变量提取桩
        if extract_vars:
            extract_block = "\n    # === 变量提取 ===\n"
            for var in extract_vars:
                extract_block += f"    # {var['name']} = 从API响应中提取 ({var.get('from_api', '')})\n"
            last_action = source.rfind('healing_page.')
            if last_action > 0:
                line_end = source.find('\n', last_action)
                source = source[:line_end] + extract_block + source[line_end:]
        
        # 5. 注入断言桩
        assert_block = '''
    # === 三层断言 ===
    # UI: expect(healing_page.get_by_text("成功")).to_be_visible()
    # API: 验证关键接口返回 code=0
    # DB:  验证记录写入（如可连接数据库）
'''
        source = source.rstrip() + assert_block
        
        with open(output_path, 'w') as f:
            f.write(source)
```

### 8.2 模块编排引擎 (scheduler/)

```python
# scheduler/graph.py

from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional
import json

@dataclass
class ModuleDefinition:
    id: str
    name: str
    description: str = ""
    raw_script_path: str = ""
    enhanced_script_path: str = ""
    har_path: str = ""
    selectors: List[Dict] = field(default_factory=list)
    api_endpoints: List[Dict] = field(default_factory=list)
    extract_variables: List[Dict] = field(default_factory=list)
    required_params: List[Dict] = field(default_factory=list)

class DependencyGraph:
    """模块依赖图引擎
    
    AI 自动推断模块间依赖 → 拓扑排序计算前置链 → 支持人工确认编辑
    """
    
    def __init__(self):
        self.modules: Dict[str, ModuleDefinition] = {}
        self.edges: Dict[str, Set[str]] = {}        # module → 依赖的模块集
        self.variable_map: Dict[str, Dict] = {}     # var_name → {producer, field_path}
    
    def add_module(self, module: ModuleDefinition):
        self.modules[module.id] = module
        for var in module.extract_variables:
            self.variable_map[var["name"]] = {
                "producer": module.id,
                "from_api": var.get("from_api", ""),
                "from_field": var.get("from_field", ""),
            }
        for param in module.required_params:
            if param["name"] in self.variable_map:
                producer = self.variable_map[param["name"]]["producer"]
                self.edges.setdefault(module.id, set()).add(producer)
    
    def get_execution_chain(self, target_module: str) -> List[str]:
        """拓扑排序 → 返回从根到 target 的前置链"""
        chain = []
        visited = set()
        def dfs(mid: str):
            if mid in visited:
                return
            visited.add(mid)
            for dep in self.edges.get(mid, set()):
                dfs(dep)
            chain.append(mid)
        dfs(target_module)
        return chain
    
    def save(self, path: str = "knowledge/dependency_graph.json"):
        data = {
            "modules": {k: v.__dict__ for k, v in self.modules.items()},
            "edges": {k: sorted(v) for k, v in self.edges.items()},
            "variable_map": self.variable_map,
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    @classmethod
    def load(cls, path: str = "knowledge/dependency_graph.json"):
        g = cls()
        with open(path, 'r') as f:
            data = json.load(f)
        for mid, mdict in data["modules"].items():
            g.modules[mid] = ModuleDefinition(**mdict)
        for mid, deps in data["edges"].items():
            g.edges[mid] = set(deps)
        g.variable_map = data.get("variable_map", {})
        return g
```

```python
# scheduler/composer.py

class Composer:
    """执行计划编排器
    
    根据前置链生成执行计划，管理变量传递
    """
    
    def compose(self, target_module: str, graph: DependencyGraph,
                external_params: dict = None) -> dict:
        chain = graph.get_execution_chain(target_module)
        
        plan = {
            "target": target_module,
            "chain": chain,
            "steps": [],
            "variables": dict(external_params or {}),
        }
        
        for i, mid in enumerate(chain):
            module = graph.modules[mid]
            step = {
                "module_id": mid,
                "script": module.enhanced_script_path,
                "needs": {},
                "produces": {},
            }
            for param in module.required_params:
                if param["name"] in plan["variables"]:
                    step["needs"][param["name"]] = plan["variables"][param["name"]]
                elif param["name"] in graph.variable_map:
                    source = graph.variable_map[param["name"]]
                    step["needs"][param["name"]] = f"from_module:{source['producer']}"
            
            for var in module.extract_variables:
                step["produces"][var["name"]] = var.get("from_field", "")
            
            plan["steps"].append(step)
        
        return plan
```

### 8.3 三层断言框架 (assertion/)

```python
# assertion/report.py

from dataclasses import dataclass, field
from typing import List, Dict
from datetime import datetime

@dataclass
class AssertionResult:
    layer: str           # "ui" / "api" / "db"
    name: str
    passed: bool
    detail: str = ""
    skipped: bool = False
    duration_ms: float = 0

@dataclass
class ModuleReport:
    module_id: str
    chain: List[str]
    results: List[AssertionResult] = field(default_factory=list)
    healing_events: List[Dict] = field(default_factory=list)
    variables: Dict = field(default_factory=dict)
    duration_ms: float = 0
    
    @property
    def summary(self) -> dict:
        layers = {"ui": {"passed": 0, "failed": 0, "skipped": 0},
                  "api": {"passed": 0, "failed": 0, "skipped": 0},
                  "db": {"passed": 0, "failed": 0, "skipped": 0}}
        for r in self.results:
            if r.skipped:
                layers[r.layer]["skipped"] += 1
            elif r.passed:
                layers[r.layer]["passed"] += 1
            else:
                layers[r.layer]["failed"] += 1
        return layers
    
    def to_json(self) -> dict:
        return {
            "module_id": self.module_id,
            "chain": self.chain,
            "summary": self.summary,
            "results": [r.__dict__ for r in self.results],
            "healing_events": self.healing_events,
            "variables": self.variables,
            "duration_ms": self.duration_ms,
            "timestamp": datetime.now().isoformat()
        }
```

### 8.4 playwright-healer 集成

```python
# conftest.py（项目根目录）

"""
playwright-healer 自动注册 healing_page fixture

环境变量配置（.env 文件或系统环境变量）:
  DEEPSEEK_API_KEY=sk-xxx                  # 百炼 DeepSeek API Key
  PH_STRATEGY=SMART                        # 策略: SMART(推荐) / HEURISTIC_ONLY / FULL
  PH_PREFER_ARIA=true                      # 优先修复为 ARIA 选择器
  PH_AUTO_PATCH_SOURCE=true                # 自动修补源码
  PH_PATCH_SOURCE_BACKUP=true              # 修补前备份原文件

说明:
   healer 安装后自动注册 fixture，无需额外 import
   只需确保 requirements.txt 中有 playwright-healer[ai]>=1.0.7
"""
```

---

## 九、自建 vs 开源对照

| 自建项 | 问题 | 开源替代 | 优势 |
|--------|------|---------|------|
| UIListener (JS注入) | 选择器不可靠，实测拿不到 | Playwright codegen | 官方录制器，生产级选择器 |
| APICapturer (page.on) | 漏请求，接口拿不全 | Playwright HAR | 标准格式，零遗漏 |
| 自建知识库 (SQLite) | 维护成本高 | healer SelectorStore | 内置 JSON 持久化，零开发 |
| 自建AI定位器 | 只有AI一种策略 | healer 4级策略链 | 属性→文本→结构→AI，快+稳 |

---

## 十、项目目录结构

```
smart-test-automation/
├── config/                           # ← 复制 from project3
│   ├── __init__.py
│   ├── accounts.py                   # 账号管理（AccountManager）
│   └── test_config.py                # 环境配置
│
├── core/                             # ← 复制 from project3
│   ├── __init__.py
│   ├── api_client.py                 # API 客户端（断言层用）
│   └── auth_manager.py               # 认证管理
│
├── ai/                               # ← 复制 from project3
│   ├── __init__.py
│   ├── provider.py                   # AI Provider（百炼 DeepSeek/GLM）
│   ├── models_config.json            # 模型配置
│   └── dependency_analyzer.py        # AI 依赖推断（已有，增强）
│
├── login_state/                      # ← 复制 from project3
│   └── storage_state.json
│
├── save_login_state.py               # ← 复制 from project3
│
├── recorder/                         # 新建 — 数据获取层
│   ├── __init__.py
│   ├── codegen_parser.py             # codegen 脚本 AST 解析器
│   ├── har_parser.py                 # HAR JSON 直接解析器
│   ├── recording_wrapper.py          # 两步录制编排器
│   └── script_transformer.py         # raw_script → healer 兼容转换
│
├── scheduler/                      # 新建 — 模块编排引擎
│   ├── __init__.py
│   ├── module_definition.py          # 模块定义数据模型
│   ├── graph.py                      # 依赖图引擎
│   ├── composer.py                   # 执行计划编排器
│   ├── ai_inference.py               # AI 依赖推断器
│   └── variable_resolver.py          # 变量传递解析器
│
├── assertion/                        # 新建 — 三层断言框架
│   ├── __init__.py
│   ├── assertion_rule.py             # 断言规则数据模型
│   ├── ui_assertion.py               # Playwright UI 断言
│   ├── api_assertion.py              # API 响应断言
│   ├── db_assertion.py               # MySQL 断言（pymysql，不可达自动跳过）
│   └── report.py                     # 三层断言报告
│
├── self_healing/                     # 新建 — 自愈机制（轻量集成）
│   ├── __init__.py
│   └── healer_config.py             # healer 环境配置 + SelectorStore 路径
│
├── knowledge/                        # 知识库存储（运行时自动生成）
│   ├── selectors.json                # healer SelectorStore 缓存
│   ├── dependency_graph.json         # 模块依赖图
│   └── modules/                      # 模块定义
│       └── (录制后自动生成)
│
├── output/                           # 录制产物输出
│   ├── modules/
│   │   └── {module_name}/
│   │       ├── raw_script.py         # codegen 原始脚本
│   │       ├── enhanced_script.py    # healer兼容+断言注入
│   │       ├── api.har               # HAR 文件
│   │       └── trace.zip             # Trace 文件
│   └── reports/
│
├── tests/                            # 测试入口
│   ├── conftest.py                   # healer fixture 已注册
│   └── test_chains/
│
├── cli.py                            # CLI 入口
├── conftest.py                       # 顶层 pytest 配置
├── requirements.txt
├── .env                              # ← 复制 from project3
├── .gitignore
└── README.md
```

### 依赖清单

```
# requirements.txt
playwright>=1.59.0
pytest>=8.0
pytest-playwright>=0.5.0
playwright-healer[ai]>=1.0.7       # 4级自愈引擎（DeepSeek 内置）
rapidfuzz>=3.0.0                    # healer DOM 文本模糊匹配依赖
pymysql>=1.1.0                      # MySQL 断言层（可选，不可达自动跳过）
```

**不再依赖**：`haralyzer`、`python-dotenv`（3.14兼容问题，手动读.env）、`testmate-agent`、`zerostep`

---

## 十一、交付计划（8-10 个工作日）

### Phase 1: 录制层 + healer 集成（Day 1-3）

| 天 | 任务 | 产出验证 |
|----|------|---------|
| Day 1 | 创建项目骨架 + 复用层 + 安装全部依赖 | `python3 -c "import playwright_healer; print('OK')"` |
| Day 1 | CodegenScriptParser 实现 | 解析采购系统 codegen 脚本 → UIOperation 列表 |
| Day 2 | HARParser + RecordingWrapper | `python3 cli.py record create_demand` 两步录制完整跑通 |
| Day 2 | ScriptTransformer | raw_script → enhanced_script 自动转换 |
| Day 3 | playwright-healer 集成 + 百炼 DeepSeek 配置验证 | 选择器失效后 healer 自动修复 ✅ |
| Day 3 | 用采购系统完整录制一次 | 三份产物齐全：enhanced_script.py + api.har + trace.zip |

**Phase 1 交付标准**：
- ✅ 一条命令录制模块，UI 操作 + API 数据零遗漏
- ✅ healer 集成，选择器变更自动修复
- ✅ 采购系统真实业务验证通过

### Phase 2: 编排引擎 + AI 依赖推断（Day 4-6）

| 天 | 任务 | 产出验证 |
|----|------|---------|
| Day 4 | ModuleDefinition + DependencyGraph | 录制 3 个模块 → 自动建图 |
| Day 5 | AI 依赖推断器 + 变量传递解析器 | AI 自动推断 create→audit→confirm 依赖链 |
| Day 6 | Composer 执行编排 + 多模块链式执行验证 | `python3 cli.py run confirm_demand` 自动编排 A→B→C 执行 |

**Phase 2 交付标准**：
- ✅ 录制多个模块 → AI 自动推断依赖
- ✅ 指定目标模块 → 自动计算前置链 + 按序执行
- ✅ 模块间变量自动传递

### Phase 3: 三层断言框架（Day 7-8）

| 天 | 任务 | 产出验证 |
|----|------|---------|
| Day 7 | UIAssertion + APIAssertion + 断言规则模型 | UI/API 两层断言通过 |
| Day 8 | DBAssertion + Report 汇总 + DB 不可用自动跳过 | 三层汇总报告完整 |

**Phase 3 交付标准**：
- ✅ UI 断言（元素可见/URL/数量）
- ✅ API 断言（status/code/字段值）+ 变量模板
- ✅ MySQL 断言（记录存在/字段值）+ DB 不可达自动跳过
- ✅ 三层汇总报告

### Phase 4: CLI + Skill（Day 9-10，可选）

| 天 | 任务 | 产出验证 |
|----|------|---------|
| Day 9 | CLI 完善 + 错误处理 | `python3 cli.py record/run/heal/report` 全可用 |
| Day 10 | 7 个 Skill 命令文档 + README | 可交接 |

Skill 命令清单：

| 命令 | 说明 |
|------|------|
| /record-module | 录制业务模块 |
| /run-test | 编排执行测试链 |
| /compose-test | 查看编排结果（不执行） |
| /generate-script | 生成增强脚本 |
| /self-heal | 手动触发选择器修复 |
| /query-knowledge | 查询定位经验 |
| /assert-report | 查看断言报告 |

---

## 十二、风险与对策

| 风险 | 概率 | 影响 | 对策 |
|------|------|------|------|
| healer 不支持百炼自定义 base_url | 中 | 高 | 查看 `playwright_healer/ai_providers.py` 源码；fork 改一行；或用 `PH_API_URL` 环境变量 |
| codegen 回放不确定（弹窗/动画） | 中 | 高 | 回放失败提示重录；Trace 辅助定位；headless=False 人工观察 |
| AI 依赖推断不准确 | 中 | 中 | 生成草稿后人工确认编辑 |
| MySQL 内网不可达 | 高 | 低 | DB 断言层自动跳过，不影响 UI/API 断言 |
| healer 异步/同步兼容 | 低 | 中 | healer 1.0.7 已支持 sync |

---

## 十三、方案对比：我们 vs 对方 AI

| 维度 | 我们的方案 | 对方方案 |
|------|-----------|---------|
| **语言栈** | ✅ 纯 Python | ❌ TypeScript + Python 子进程 |
| **自愈框架** | ✅ playwright-healer(PyPI v1.0.7) | ❌ @testmate-agent/core(npm v0.1.0) |
| **AI 提供商** | ✅ 百炼 DeepSeek（已有 Key） | ❌ Anthropic Claude（需新购） |
| **工期** | ✅ 8-10 天 | ❌ 4 周 |
| **数据安全** | ✅ 自部署 | ❌ 数据发 Anthropic 云 |
| **录制方式** | ✅ 两步录制（精确 UI-API 关联） | — 未明确 |
| **差异化** | ✅ 三层断言 + 模块编排 | — 未涉及 |
| **成本** | ✅ 百炼 API 几块钱 | ❌ Claude API + 额外 Key |
| **前端配合** | ✅ 零配合即可运行 | — 依赖不明 |
| **确定性** | ✅ healer 修复后写回源码 | ❌ ZeroStep 每次动态决策 |

---

## 十四、成功标准

| 验证项 | 通过标准 |
|--------|---------|
| 🎬 录制 | `cli.py record xxx` 一条命令完成，UI 操作 + API 数据零遗漏 |
| 🔄 自愈 | 选择器变更后，healer 自动修复率 ≥ 80% |
| 🔗 编排 | 指定目标模块，自动计算前置链并按序执行 |
| 📊 断言 | 三层断言汇总报告，DB 不可用自动跳过 |
| 🤖 AI | 依赖推断准确率 ≥ 70%（草稿 + 人工确认） |
| ⏱️ 效率 | 录制一个模块 ≤ 10 分钟（含手动操作） |
| 🛡️ 零前端配合 | 不依赖任何前端改动即可完整运行 |

---

## 十五、下一步行动

1. **创建项目骨架** → `smart-test-automation/` 目录
2. **复制复用层** → config/, core/, ai/, login_state/, .env
3. **安装依赖** → `pip install playwright playwright-healer[ai] pytest-playwright pymysql rapidfuzz`
4. **验证 healer + 百炼 DeepSeek 连通性**
5. **用采购系统跑第一次 codegen 录制**
