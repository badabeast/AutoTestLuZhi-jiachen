# 测试用例智能执行系统 — 最终落地方案（v4 Final）

> 结论收敛：融合 v2 架构设计 + 开源捷径 + 前端代码赋能，10 个工作日交付核心能力

---

## 一、方案演进与最终决策

### 1.1 为什么不用 project3

| project3 问题 | 根因 | 结论 |
|--------------|------|------|
| UI 录制拿不到元素 | JS 注入 `document.addEventListener` 在 SPA 中不可靠 | ❌ 架构级缺陷 |
| API 漏请求、缺响应体 | `page.on` + `id(request)` 匹配失败 + `response.json()` 时序问题 | ❌ 架构级缺陷 |
| 选择器质量差 | 自建 `_generate_selector()` 纯字符串拼接，无 Playwright 语法树推断 | ❌ 质量不足 |

**核心认知**：UI 操作数据、API 请求/响应数据，这些都是 Playwright 官方就能可靠获取的，不应自建。

### 1.2 可选方案评估结论

| 方案 | 评估 | 结论 |
|------|------|------|
| `playwright-healer`（PyPI v1.0.7） | Python 原生、5 层自愈、DeepSeek 内置、pytest fixture | ✅ 采用 |
| `ZeroStep`（SaaS） | 仅 TypeScript + 强制 OpenAI + 按调用付费 | ❌ 不适用 |
| `@testmate-agent/core`（npm v0.1.0） | 个人开发 0.1.0、强制 Anthropic、功能同 healer | ❌ 不适用 |
| `haralyzer`（PyPI v2.4.0） | 文档 404、偏老但稳定 | ⚠️ 备选，不如 json.load |
| 自建 accessibility snapshot 定位器 | 理论上限高但投入大 | 🔄 P2 预留 |
| 前端代码补 `data-testid` | 成本极低、收益极高 | ✅ 强烈推荐 |

### 1.3 最终技术选型

| 能力 | 选择 | 理由 |
|------|------|------|
| UI 录制 | `playwright codegen` | 官方录制器，选择器策略成熟（role > text > testid > css） |
| API 捕获 | `record_har_path` + `record_har_content="embed"` | HAR 标准格式，完整请求/响应，零遗漏 |
| 执行回溯 | `context.tracing.start(screenshots=True, snapshots=True)` | DOM 快照 + 截图 + 网络，调试利器 |
| 自愈引擎 | `playwright-healer` | 5 层流水线，DeepSeek 内置，pytest 即插即用 |
| HAR 解析 | `json.load` 直解 | HAR 是标准 JSON，自解比第三方库更可控 |
| AI 分析 | 百炼 DeepSeek / GLM（复用 project3） | 已验证可用，成本低 |
| 三层断言 | 自建（UI + API + MySQL） | 核心差异化能力 |
| 模块编排 | 自建依赖图 + 拓扑排序 | 核心差异化能力 |

---

## 二、系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     用户交互层                                    │
│   CLI: record / run / heal / report                             │
│   Skill: /record-module  /run-test  /self-heal  /assert-report  │
├─────────────────────────────────────────────────────────────────┤
│                     智慧编排引擎 (Orchestrator)                    │
│   依赖图 → 拓扑排序 → 前置链 → 变量传递 → 逐模块执行 → 汇总报告    │
├──────────┬──────────┬───────────┬───────────┬──────────────────┤
│ 数据获取  │  自愈机制  │ 三层断言   │  AI 分析  │   知识管理       │
│ (官方框架)│ (开源+预留)│  (自建)    │ (复用P3)  │   (渐进式)      │
│          │          │           │           │                │
│ codegen  │ healer   │ UI断言    │ 依赖推断   │ healer缓存     │
│ HAR录制  │ 5层流水线  │ API断言   │ 变量提取   │ 依赖图JSON     │
│ Trace回溯│ access.  │ DB断言    │ 参数推断   │ 模块定义JSON   │
│          │ snapshot │           │           │ SQLite库(P2)   │
│          │ (P2预留)  │           │           │                │
├──────────┴──────────┴───────────┴───────────┴──────────────────┤
│                     复用层 (from project3)                        │
│  config/accounts + core/auth + core/api + ai/provider            │
│  + save_login_state + login_state/storage_state.json + .env      │
├─────────────────────────────────────────────────────────────────┤
│                     前端赋能层 (可选，强烈推荐)                     │
│  data-testid 补丁 → 选择器稳定性 +80%                            │
│  路由表提取 → 录制导航优化                                        │
│  API 定义提取 → 补充 HAR 盲区                                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三、核心工作流

### 3.1 模块录制流程（两步录制法）

```
用户: python3 cli.py record create_demand "创建采购需求"
  │
  ├─ Step 1: 启动 codegen 录制（用户手动操作）
  │   ┌──────────────────────────────────────────────────────┐
  │   │  npx playwright codegen                              │
  │   │    --target=python-pytest                             │
  │   │    --load-storage=login_state/storage_state.json      │
  │   │    --viewport-size="1366,768"                         │
  │   │    --test-id-attribute=data-testid                    │
  │   │    --output=output/modules/create_demand/raw_script.py│
  │   │    https://www.test.zcygov.cn/demand_front/           │
  │   └──────────────────────────────────────────────────────┘
  │   用户在浏览器中手动操作完整流程
  │   关闭浏览器 → 保存 raw_script.py
  │   ✅ 产出: raw_script.py（含 Playwright 推荐的最佳选择器）
  │
  ├─ Step 2: 自动回放 + HAR + Trace（无人值守）
  │   ┌──────────────────────────────────────────────────────┐
  │   │  RecordingWrapper 自动执行:                           │
  │   │  1. 包装 raw_script.py，注入 HAR/Trace 上下文        │
  │   │  2. browser.new_context(                              │
  │   │       record_har_path="output/.../api.har",           │
  │   │       record_har_url_filter="**/api/**",              │
  │   │       record_har_content="embed"                      │
  │   │     )                                                 │
  │   │  3. context.tracing.start(screenshots=True,           │
  │   │                           snapshots=True)             │
  │   │  4. 执行 raw_script.py 每一步操作                     │
  │   │  5. context.tracing.stop(path="trace.zip")            │
  │   │  6. context.close()  # 必须 close 才保存 HAR          │
  │   └──────────────────────────────────────────────────────┘
  │   ✅ 产出: api.har + trace.zip
  │
  ├─ Step 3: 解析产物
  │   a. CodegenScriptParser(ast) → UIOperation 列表
  │   │  提取每步的 action + selector_type + selector_value + value
  │   b. HARParser(json.load) → APICall 列表
  │   │  提取 method + url + request_body + response_body + status
  │   c. 时间对齐：UI 操作和 API 请求按时间戳关联
  │
  ├─ Step 4: AI 分析
  │   a. 从 API 响应中推断提取变量（demand_id, demand_name 等）
  │   b. 从 API 请求中推断所需参数（哪些外部传入）
  │   c. 对比已录制模块 → 推断依赖关系
  │
  ├─ Step 5: 生成增强脚本
  │   a. raw_script.py → healer 兼容（page → healing_page）
  │   b. 注入三层断言（AI 根据操作语义自动生成）
  │   c. 变量模板替换（{{demand_id}} 等）
  │
  └─ Step 6: 保存模块定义
      knowledge/modules/create_demand.json:
      {
        "id": "create_demand",
        "name": "创建采购需求",
        "raw_script": "output/modules/create_demand/raw_script.py",
        "enhanced_script": "output/modules/create_demand/enhanced_script.py",
        "har_file": "output/modules/create_demand/api.har",
        "selectors": [
          {"type": "role", "value": "button", "name": "提交", "stability": 1.0},
          {"type": "test_id", "value": "btn-submit", "stability": 0.95}
        ],
        "api_endpoints": [
          {"method": "POST", "path": "/demand/api/demand/create", "has_request_body": true}
        ],
        "extract_variables": [
          {"name": "demand_id", "from_api": "POST /demand/api/demand/create", "from_field": "data.id"}
        ],
        "required_params": []
      }
```

### 3.2 测试编排与执行流程

```
用户: python3 cli.py run confirm_demand
  │
  ├─ Step 1: 查询依赖图 → 计算前置链
  │   confirm_demand 依赖 → audit_demand 依赖 → create_demand
  │   执行顺序: create_demand → audit_demand → confirm_demand
  │
  ├─ Step 2: 逐模块执行 + 自愈 + 三层断言 + 变量传递
  │
  │   ┌─ Module A: create_demand ──────────────────────────┐
  │   │  1. pytest output/modules/create_demand/enhanced_script.py │
  │   │  2. healing_page 自动处理选择器失效                      │
  │   │  3. 三层断言:                                         │
  │   │     ├─ UI: "提交成功" 提示可见                          │
  │   │     ├─ API: POST /demand/create → 200, code:0          │
  │   │     └─ DB: SELECT * FROM demand WHERE id={{demand_id}}  │
  │   │         → status='draft'（DB不可达则跳过）              │
  │   │  4. 提取变量: demand_id = "XQ-2026-00518964"           │
  │   └──────────────────────────────────────────────────────┘
  │   ↓ 变量传递: demand_id
  │   ┌─ Module B: audit_demand ───────────────────────────┐
  │   │  1. 注入 demand_id → enhanced_script 执行            │
  │   │  2. 自愈 + 三层断言                                   │
  │   │  3. 提取变量: audit_result = "approved"               │
  │   └──────────────────────────────────────────────────────┘
  │   ↓ 变量传递: demand_id + audit_result
  │   ┌─ Module C: confirm_demand ─────────────────────────┐
  │   │  1. 注入变量 → 执行 → 三层断言                        │
  │   │  2. 最终验证: 全链路数据一致性                          │
  │   └──────────────────────────────────────────────────────┘
  │
  └─ Step 3: 汇总断言报告
      ┌──────────────────────────────────────────┐
      │ 📊 三层断言报告                            │
      │                                           │
      │ 模块链: create → audit → confirm           │
      │ 总耗时: 45.2s                              │
      │                                           │
      │ UI 层:  ✅ 5/5 通过                        │
      │ API 层: ✅ 8/8 通过                        │
      │ DB 层:  ⏭️ 2/2 跳过（MySQL不可达）           │
      │                                           │
      │ 选择器自愈: 1次触发 → 1次修复成功            │
      │ 变量传递: demand_id ✅                      │
      └──────────────────────────────────────────┘
```

### 3.3 自愈流程（6 层递进）

```
UI 脚本执行 → 选择器失效（TimeoutError / ElementNotFound）
  │
  ├─ L0: healer 内置缓存
  │   从历史修复记录查找 → 命中则直接替换执行
  │   ↓ 未命中
  ├─ L1: healer 启发式修复
  │   同义文本 / 相似CSS / 临近元素替换
  │   ↓ 未命中
  ├─ L2: healer DOM 模糊匹配
  │   Levenshtein文本距离 / accessibility tree 匹配
  │   ↓ 未命中
  ├─ L3: healer AI DOM 定位（DeepSeek）
  │   DOM片段 + 语义描述 → AI 返回新选择器 → 验证 → 写回源码
  │   ↓ 未命中
  ├─ L4: healer AI 视觉定位（DeepSeek + 截图）
  │   页面截图 + 元素描述 → AI 返回坐标/选择器
  │   ↓ 未命中
  ├─ L5（P2 预留）: 自建 accessibility snapshot 定位
  │   page.accessibility.snapshot() → 语义树搜索 → 自建 AI 匹配
  │   → 理论上限更高，解决 healer 天花板问题
  │
  └─ 全部失败 → healing-report.json 记录 → 人工介入
```

---

## 四、前端代码赋能策略

### 4.1 能带来什么

| 维度 | 无前端代码 | 有前端代码 |
|------|-----------|-----------|
| 定位器 | 被动等 codegen 生成 | 主动查找/补上缺失的 `data-testid` |
| 组件层级 | 靠猜/DOM 观察 | 看源码知道嵌套和动态渲染逻辑 |
| API 端点 | 靠 HAR 被动捕获 | 源码里全搜出来，含条件触发的 |
| 路由映射 | 不知道 URL 对应哪个页面 | `router.ts` 一目了然 |
| 动态元素 | 回放经常挂 | 知道哪些是条件渲染、异步加载 |

### 4.2 操作步骤

```
Step 1: 确认技术栈
  cat package.json | grep -E "react|vue|angular|antd|element"

Step 2: 统计 data-testid 覆盖现状
  grep -rn "data-testid\|testId\|test-id" src/ | wc -l

Step 3: 给前端补"最小 testid 清单"（性价比最高的操作）
  只覆盖关键交互元素：
  - P0: 提交/确认按钮 → data-testid="btn-submit"
  - P0: 列表操作列按钮 → data-testid="btn-audit"
  - P1: 搜索/筛选表单 → data-testid="input-search"
  - P2: 面包屑/Tab切换 → data-testid="tab-pending"
  前端每个元素只加一行，对自动化稳定性提升 80%+

Step 4: 提取路由表 → 录制脚本导航优化
Step 5: 提取 API 定义 → 补充 HAR 盲区
Step 6: codegen 录制时 --test-id-attribute=data-testid 生效
```

### 4.3 testid + healer 的协同关系

```
data-testid (80% 场景) ──→ 选择器永远稳定，不需要修复
  ↓ 剩余 20% 场景（按钮文案改了、新增了弹窗等）
playwright-healer (自动修复) ──→ 选择器失效时自动修复
  ↓ healer 修复不了的极端场景（<5%）
accessibility snapshot (P2) ──→ 语义级兜底

三层保险，基本消灭"定位器失效导致脚本挂掉"的问题
```

---

## 五、详细模块设计

### 5.1 数据获取层

#### 5.1.1 CodegenScriptParser — AST 解析 codegen 输出

```python
# recorder/codegen_parser.py

import ast
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class UIOperation:
    step_index: int              # 步骤序号
    action: str                  # click / fill / select / navigate / press / check
    selector_type: str           # role / text / test_id / label / placeholder / css
    selector_value: str          # 选择器参数
    value: Optional[str] = None  # fill 值 / select 选项
    raw_line: str = ""           # 原始代码行（用于修补）

class CodegenScriptParser:
    """用 AST 解析 Playwright codegen 生成的 Python-pytest 脚本"""
    
    # 选择器调用链映射
    SELECTOR_MAP = {
        "get_by_role": "role",
        "get_by_text": "text",
        "get_by_test_id": "test_id",
        "get_by_label": "label",
        "get_by_placeholder": "placeholder",
        "locator": "css",
    }
    
    # 操作方法映射
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
        # 递归解析链式调用，提取 selector_type + selector_value + action + value
        ...
```

#### 5.1.2 HARParser — 直接 json.load

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
    """直接用 json.load 解析 HAR 1.2 标准文件
    
    不依赖 haralyzer，更可控
    """
    
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
        return None  # 非JSON响应不存储（图片/CSS等）
    
    def _match(self, url: str) -> bool:
        """简单 glob 匹配"""
        if not self.url_filter:
            return True
        # 支持 **/api/** 模式
        pattern = self.url_filter.replace("**", "*").replace("*", "")
        return pattern in url
```

#### 5.1.3 RecordingWrapper — 两步录制编排

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
            "--test-id-attribute=data-testid",
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
        
        # 生成 wrapper 脚本（注入 HAR/Trace 上下文）
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
        
        # === 在此处导入并执行 raw_script 的操作 ===
        # 通过动态导入方式复用 step1 的操作序列
        import importlib.util
        spec = importlib.util.spec_from_file_location("raw", "{raw_script}")
        raw = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(raw)
        # 调用 step1 中定义的 test 函数
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

#### 5.1.4 ScriptTransformer — healer 兼容转换

```python
# recorder/script_transformer.py

import re

class ScriptTransformer:
    """将 codegen 输出转换为 playwright-healer 兼容格式
    
    核心转换:
    1. page → healing_page (fixture 参数)
    2. 类型注解 Page → 删除（healer 用自注册 fixture）
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
        
        # 3. 在文件头部添加 healer 导入说明
        healer_comment = '''"""
Auto-generated by smart-test-automation
Module: {module}
Self-healing enabled via playwright-healer (healing_page fixture)
"""'''.format(module=module_name)
        
        source = healer_comment + "\n\n" + source
        
        # 4. 注入变量提取桩
        if extract_vars:
            extract_block = "\n    # === 变量提取 ===\n"
            for var in extract_vars:
                extract_block += f"    # {var['name']} = 从API响应中提取 ({var.get('from_api', '')})\n"
            # 在最后一个 action 后插入
            last_action = source.rfind('healing_page.')
            if last_action > 0:
                line_end = source.find('\n', last_action)
                source = source[:line_end] + extract_block + source[line_end:]
        
        # 5. 注入断言桩
        assert_block = f'''
    # === 断言桩（AI 生成或手动补充）===
    # UI: expect(healing_page.get_by_text("成功")).to_be_visible()
    # API: 验证关键接口返回 code=0
    # DB:  验证记录写入（如可连接数据库）
'''
        source = source.rstrip() + assert_block
        
        with open(output_path, 'w') as f:
            f.write(source)
```

### 5.2 模块编排引擎

```python
# orchestrator/graph.py

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
    
    - AI 自动推断模块间依赖（参数传递链）
    - 支持人工确认/编辑
    - 拓扑排序计算执行顺序
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
    
    def get_variable_source(self, var_name: str) -> Optional[Dict]:
        """查询变量的产出模块"""
        return self.variable_map.get(var_name)
    
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
# orchestrator/composer.py

class Composer:
    """执行计划编排器
    
    根据前置链生成 pytest 执行计划，管理变量传递
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
            # 解析该模块需要哪些外部变量
            for param in module.required_params:
                if param["name"] in plan["variables"]:
                    step["needs"][param["name"]] = plan["variables"][param["name"]]
                elif param["name"] in graph.variable_map:
                    source = graph.variable_map[param["name"]]
                    step["needs"][param["name"]] = f"from_module:{source['producer']}"
            
            # 记录该模块将产出的变量
            for var in module.extract_variables:
                step["produces"][var["name"]] = var.get("from_field", "")
            
            plan["steps"].append(step)
        
        return plan
```

### 5.3 三层断言框架

```python
# assertion/report.py

from dataclasses import dataclass, field
from typing import List, Dict
from datetime import datetime

@dataclass
class AssertionResult:
    layer: str           # "ui" / "api" / "db"
    name: str            # 断言名称
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

### 5.4 playwright-healer 集成

```python
# conftest.py（项目根目录）

"""
playwright-healer 自动注册 healing_page fixture
只需安装 playwright-healer 和配置环境变量即可

环境变量配置（.env 文件或系统环境变量）:
  DEEPSEEK_API_KEY=sk-xxx                  # 百炼 DeepSeek API Key
  DEEPSEEK_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1  # 如 healer 支持
  DEEPSEEK_MODEL=deepseek-v4-pro           # 模型名
  PH_STRATEGY=SMART                        # 策略: SMART (推荐) / HEURISTIC_ONLY / FULL
  PH_PREFER_ARIA=true                      # 优先修复为 ARIA 选择器
  PH_AUTO_PATCH_SOURCE=true                # 自动修补源码
  PH_PATCH_SOURCE_BACKUP=true              # 修补前备份原文件
"""

# healer 安装后会自动注册 fixture，无需额外 import
# 只需确保 requirements.txt 中有 playwright-healer>=1.0.7
```

```python
# self_healing/accessibility_locator.py（P2 预留）

"""
当 playwright-healer 遇到天花板时的增强方案

技术原理:
- page.accessibility.snapshot() 返回页面语义树
- 每个节点: role, name, value, description, checked, disabled, focused
- 可以做结构化语义搜索，比文本模糊匹配更精确
- AI 最擅长理解结构化语义树，token 效率远优于原始 HTML

实现路线（P2）:
1. snapshot = page.accessibility.snapshot()
2. 递归遍历 → 找 role + name 匹配的节点
3. 记录节点路径 → 生成 Playwright 选择器
4. 失败 → 截取局部 tree → 发送给百炼 DeepSeek
5. AI 返回定位策略 → 验证 → 更新知识库

与 healer 的关系:
- healer 处理 95% 的常规选择器失效
- 此模块处理 healer 无法修复的 5%（如整页重构、组件库升级）
- 互补而非替代
"""
```

---

## 六、项目结构与依赖

### 6.1 目录结构

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
├── orchestrator/                     # 新建 — 模块编排引擎
│   ├── __init__.py
│   ├── module_definition.py          # 模块定义数据模型
│   ├── graph.py                      # 依赖图引擎
│   ├── composer.py                   # 执行计划编排器
│   ├── ai_inference.py               # AI 依赖推断器
│   └── variable_resolver.py          # 变量传递解析器
│
├── assertion/                        # 新建 — 三层断言框架
│   ├── __init__.py
│   ├── ui_assertion.py               # Playwright UI 断言
│   ├── api_assertion.py              # API 响应断言
│   ├── db_assertion.py               # MySQL 数据库断言
│   ├── report.py                     # 三层断言报告
│   └── assertion_rule.py             # 断言规则数据模型
│
├── self_healing/                     # 新建 — 自愈机制
│   ├── __init__.py
│   ├── fixture_integration.py        # healer fixture 集成说明
│   ├── accessibility_locator.py      # 预留: AI 语义定位器(P2)
│   └── knowledge_sync.py             # 预留: healer缓存→SQLite同步(P2)
│
├── knowledge/                        # 知识库存储
│   ├── dependency_graph.json         # 模块依赖图
│   └── modules/                      # 模块定义
│       └── (录制后自动生成)
│
├── output/                           # 录制产物输出
│   ├── modules/                      # 每模块录制产物
│   │   └── {module_name}/
│   │       ├── raw_script.py         # codegen 原始脚本
│   │       ├── enhanced_script.py    # healer兼容+断言注入
│   │       ├── api.har               # HAR 文件
│   │       └── trace.zip             # Trace 文件
│   └── reports/                      # 断言报告
│
├── tests/                            # 测试入口
│   ├── conftest.py                   # healer fixture 注册
│   └── test_chains/                  # 业务链测试
│       └── test_demand_flow.py
│
├── cli.py                            # CLI 入口
├── conftest.py                       # 顶层 pytest 配置
├── requirements.txt                  # 依赖
├── .env                              # ← 复制 from project3
├── .gitignore
└── README.md
```

### 6.2 依赖清单

```
# requirements.txt
playwright>=1.59.0
pytest>=8.0
pytest-playwright>=0.5.0
playwright-healer>=1.0.7       # 5 层自愈引擎（DeepSeek 内置）
pymysql>=1.1.0                 # MySQL 断言层（可选）
python-dotenv>=1.0.0           # 注意 Python 3.14 兼容性问题，可能需手动读 .env
```

**不再依赖**：`haralyzer`（改用 json.load）、`testmate-agent`（TypeScript）、`zerostep`（SaaS 不适用）

---

## 七、前端赋能操作清单

| 序号 | 操作 | 命令/动作 | 收益 |
|------|------|----------|------|
| 1 | 确认技术栈 | `cat package.json \| grep react/vue/antd/element` | 决定选择器策略 |
| 2 | 统计 testid 覆盖 | `grep -rn "data-testid\|testId" src/ \| wc -l` | 评估现状 |
| 3 | 推动前端补 testid | 给前端"最小 testid 清单"（P0: 提交/操作按钮） | 选择器稳定性 +80% |
| 4 | 提取路由表 | 找到 `router.ts` / `routes.tsx` | 录制导航优化 |
| 5 | 提取 API 定义 | `grep -rn "axios\.\|fetch(\|request(" src/` | 补充 HAR 盲区 |

---

## 八、交付计划（10 个工作日）

### Phase 1: 录制层 + 年愈集成（Day 1-3）

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

### Phase 4: 打磨 + 文档（Day 9-10，可选）

| 天 | 任务 | 产出验证 |
|----|------|---------|
| Day 9 | CLI 完善 + 错误处理 + 异常场景兜底 | `python3 cli.py record/run/heal/report` 全可用 |
| Day 10 | README + 录制演示 + 前端 testid 清单模板 | 文档齐全，可交接 |

---

## 九、风险与对策

| 风险 | 概率 | 影响 | 对策 |
|------|------|------|------|
| healer 不支持百炼自定义 base_url | 中 | 高 | 查看 `playwright_healer/ai_providers.py` 源码；不行就 fork 改一行；或用 `PH_API_URL` 环境变量 |
| codegen 回放行为不确定（弹窗、动画） | 中 | 高 | 回放失败提示用户重录；Trace 文件辅助定位；headless=False 人工观察 |
| AI 依赖推断不准确 | 中 | 中 | 生成草稿后人工确认编辑；提供 JSON 编辑器（P3 可视化界面） |
| MySQL 内网不可达 | 高 | 低 | DB 断言层自动跳过，不影响 UI/API 断言 |
| python-dotenv 3.14 兼容性 | 低 | 低 | 手动读 `.env`（已有解决方案） |
| healer 异步/同步兼容 | 低 | 中 | healer 1.0.7 已支持 sync；不行用 `asyncio.run()` 包装 |

---

## 十、方案对比：我们 vs 对方 AI

| 维度 | 我们的方案 | 对方方案 |
|------|-----------|---------|
| **语言栈** | ✅ 纯 Python | ❌ TypeScript + Python 子进程 |
| **自愈框架** | ✅ playwright-healer（PyPI v1.0.7） | ❌ @testmate-agent/core（npm v0.1.0，个人开发） |
| **AI 提供商** | ✅ 百炼 DeepSeek（已有 Key） | ❌ Anthropic Claude（需新购） |
| **工期** | ✅ 10 天 | ❌ 4 周 |
| **数据安全** | ✅ 自部署（数据不出内网） | ❌ 数据发 Anthropic 云 |
| **录制方式** | ✅ 两步录制（精确 UI-API 关联） | — 未明确 |
| **差异化** | ✅ 三层断言 + 模块编排 | — 未涉及 |
| **成本** | ✅ 百炼 API 几块钱 | ❌ Claude API + 额外 Key |
| **确定性** | ✅ healer 修复后写回源码 | ❌ ZeroStep 每次动态决策 |

---

## 十一、成功标准

| 验证项 | 通过标准 |
|--------|---------|
| 🎬 录制 | `cli.py record xxx` 一条命令完成，UI 操作 + API 数据零遗漏 |
| 🔄 自愈 | 选择器变更后，healer 自动修复率 ≥ 80% |
| 🔗 编排 | 指定目标模块，自动计算前置链并按序执行 |
| 📊 断言 | 三层断言汇总报告，DB 不可用自动跳过 |
| 🤖 AI | 依赖推断准确率 ≥ 70%（草稿 + 人工确认） |
| ⏱️ 效率 | 录制一个模块 ≤ 10 分钟（含手动操作） |
| 🏗️ 前端赋能 | testid 补全后选择器失效下降 80% |

---

## 十二、下一步行动

1. **创建项目骨架** → `smart-test-automation/` 目录
2. **复制复用层** → config/, core/, ai/, login_state/, .env
3. **安装依赖** → `pip install playwright playwright-healer pytest-playwright pymysql`
4. **验证 healer + 百炼 DeepSeek 连通性**
5. **用采购系统跑第一次 codegen 录制**
6. **前端 testid 清单发给前端团队**（同步推进）
