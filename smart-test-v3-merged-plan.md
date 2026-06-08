# 测试用例智能执行系统 — 融合方案（v3）

> 融合原则：v2 的先进架构设计 + 方案A 的开源捷径，2 周交付核心功能

---

## 一、方案来源与融合决策

| 模块 | v2 方案 | 方案A | 融合决策 | 理由 |
|------|---------|-------|---------|------|
| 录制方式 | 两步录制（codegen → 回放+HAR） | 一条命令 `codegen --save-har` | **v2 两步录制** ✅ | UI-API 精确关联，Trace 双时间线 |
| 自愈引擎 | 自建 accessibility snapshot + AI | playwright-healer 开源 | **先用 playwright-healer** ✅ → 后期可选自建 | 零成本集成，1天可用 |
| HAR 解析 | 自建 HARParser | haralyzer / json.load | **json.load 自解为主** ✅ | HAR 是标准 JSON，自解更可控 |
| AI Provider | 自建 | 复用 project3 | **复用 project3** ✅ | 已验证百炼 DeepSeek/GLM 可用 |
| 模块编排 | 自建依赖图 + 前置链 | 无 | **v2 模块编排** ✅ | 核心差异化能力 |
| 三层断言 | UI + API + MySQL | 无 | **v2 三层断言** ✅ | 商业价值高 |
| 知识库 | SQLite 元素经验库 | playwright-healer 内置缓存 | **先轻量后重度** ✅ | healer 缓存先行，SQLite 后补 |
| Skill/CLI | 7 个斜杠命令 + cli.py | 无 | **P2 后补** ✅ | 先保核心，再服务化 |

---

## 二、系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                Skill 服务层 (P2 迭代)                        │
│  /record-module  /run-test  /self-heal  /assert-report     │
├─────────────────────────────────────────────────────────────┤
│                  智慧编排引擎 (Orchestrator)                  │
│  依赖图(AI推断) → 前置链 → 拓扑排序 → 变量传递 → 执行       │
├────────────┬────────────┬────────────┬─────────────────────┤
│  数据获取   │  自愈机制   │  三层断言   │  知识管理          │
│  (官方框架) │  (开源+自建)│  (自建)    │  (渐进式)          │
│             │            │            │                    │
│  codegen    │ healer固件  │ UI断言     │ healer缓存(先用)   │
│  HAR录制    │ AST备份修补 │ API断言    │ SQLite库(后补)     │
│  Trace回溯  │ accessibility│ DB断言    │ 依赖图JSON         │
│             │ snapshot(预留)│           │                    │
├────────────┴────────────┴────────────┴─────────────────────┤
│                  复用层 (from project3)                      │
│  config/accounts + core/auth + core/api + ai/provider       │
│  + save_login_state + login_state/ + .env                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、核心工作流

### 3.1 模块录制流程（两步录制）

```
用户操作: /record-module create_demand "创建采购需求"
  │
  ├─ Step 1: codegen 录制 UI 操作（用户手动）
  │   npx playwright codegen \
  │     --target=python-pytest \
  │     --load-storage=login_state/storage_state.json \
  │     --viewport-size="1366,768" \
  │     --output=output/modules/create_demand/raw_script.py \
  │     --test-id-attribute=data-testid \
  │     https://www.test.zcygov.cn/demand_front/
  │
  │   用户手动操作完整创建需求流程
  │   → 产出: raw_script.py（含精准选择器 + pytest 格式）
  │
  ├─ Step 2: 自动回放 + HAR + Trace（无人值守）
  │   用 RecordingWrapper 自动执行:
  │   a. 包装 raw_script.py，注入 HAR 录制和 Trace
  │   b. 创建 context 时指定:
  │      - record_har_path="output/modules/create_demand/api.har"
  │      - record_har_url_filter="**/demand/api/**"
  │      - record_har_content="embed"
  │   c. 启动 context.tracing.start(screenshots=True, snapshots=True)
  │   d. 执行 raw_script.py 的每一步操作
  │   e. context.tracing.stop(path="output/modules/create_demand/trace.zip")
  │   f. context.close()  # 必须 close 才保存 HAR
  │
  │   → 产出: api.har + trace.zip
  │
  ├─ Step 3: 解析产物
  │   a. CodegenScriptParser(ast) → UIOperation 列表
  │   b. HARParser(json.load) → APICall 列表（含完整 req/res body）
  │   c. TraceParser(可选) → DOM快照时间线 + 操作-网络关联
  │
  ├─ Step 4: AI 分析
  │   a. 提取变量: 从 API 响应推断 demand_id, demand_name 等
  │   b. 推断参数: 哪些是外部传入的
  │   c. 推断依赖: 与已录制模块的参数依赖链
  │
  └─ Step 5: 保存模块定义
      output/modules/create_demand/module.json
      knowledge/modules/create_demand.json
```

### 3.2 测试编排与执行流程

```
用户操作: /run-test confirm_demand "确认采购需求"
  │
  ├─ Step 1: 查询依赖图 → 计算前置链
  │   confirm_demand → audit_demand → create_demand
  │   执行顺序: create_demand → audit_demand → confirm_demand
  │
  ├─ Step 2: 逐模块执行 + 变量传递 + 三层断言
  │
  │   Module A: create_demand
  │     ├─ 执行 UI 脚本（healing_page fixture 自愈）
  │     ├─ 同时捕获 API 响应（route_from_har 或 page.on 监听）
  │     ├─ 三层断言:
  │     │   ├─ UI: expect(page.get_by_text("提交成功")).to_be_visible()
  │     │   ├─ API: POST /demand/api/demand/create → 200 / code:0
  │     │   └─ DB: SELECT * FROM demand WHERE id={{demand_id}} → status=draft
  │     └─ 提取变量: demand_id = "XQ-2026-00518964"
  │
  │   Module B: audit_demand
  │     ├─ 注入变量: demand_id 从 A 传递
  │     ├─ 执行 UI + API + DB 三层断言
  │     └─ 提取变量: audit_result = "approved"
  │
  │   Module C: confirm_demand
  │     ├─ 注入变量: demand_id + audit_result
  │     ├─ 执行 UI + API + DB 三层断言
  │     └─ 最终验证
  │
  └─ Step 3: 汇总三层断言报告
      {
        "module": "confirm_demand",
        "chain": ["create_demand", "audit_demand", "confirm_demand"],
        "results": {
          "ui": {"passed": 3, "failed": 0},
          "api": {"passed": 5, "failed": 1, "detail": "..."},
          "db": {"passed": 2, "failed": 0, "skipped": 1}
        },
        "variables_extracted": {"demand_id": "...", "audit_result": "..."},
        "total_duration_ms": 12345
      }
```

### 3.3 自愈流程

```
UI 脚本执行 → 选择器失效（TimeoutError / ElementalNotFound）
  │
  ├─ Layer 0: playwright-healer 内置缓存
  │   healer 自动从历史修复记录查找 → 命中则直接替换
  │   ↓ 未命中
  ├─ Layer 1: healer 启发式修复
  │   同义文本 / 相似 CSS / 临近元素 → 自动替换
  │   ↓ 未命中
  ├─ Layer 2: healer DOM 模糊匹配
  │   Levenshtein 文本距离 / accessibility tree 匹配 → 自动替换
  │   ↓ 未命中
  ├─ Layer 3: healer AI DOM 定位（DeepSeek）
  │   发送 DOM 片段 + 语义描述 → AI 返回新选择器 → 验证 → 自动替换
  │   ↓ 未命中
  ├─ Layer 4: healer AI 视觉定位（DeepSeek + 截图）
  │   页面截图 + 元素描述 → AI 返回坐标/选择器 → 验证 → 自动替换
  │   ↓ 未命中
  ├─ Layer 5（预留）: 自建 accessibility snapshot 定位
  │   page.accessibility.snapshot() → 自建 AI 语义匹配
  │   → 理论上限更高，但需自建，P2 迭代补充
  │
  └─ 所有层失败 → 记录到 healing-report.json → 人工介入
```

---

## 四、模块详细设计

### 4.1 数据获取层

#### 4.1.1 CodegenScriptParser — AST 解析 codegen 输出

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
    value: Optional[str]         # fill 的值、select 的选项等
    raw_line: str                # 原始代码行（用于修补）

class CodegenScriptParser:
    """用 AST 解析 Playwright codegen 生成的 Python-pytest 脚本"""
    
    def parse(self, script_path: str) -> List[UIOperation]:
        with open(script_path, 'r') as f:
            source = f.read()
        tree = ast.parse(source)
        operations = []
        step = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                op = self._parse playwright_call(node)
                if op:
                    op.step_index = step
                    step += 1
                    operations.append(op)
        return operations
    
    def _parse_playwright_call(self, node: ast.Call) -> Optional[UIOperation]:
        """解析 page.get_by_xxx().click() / page.goto() 等调用链"""
        # 识别 get_by_role / get_by_text / get_by_test_id / get_by_label
        # 识别 .click() / .fill() / .select_option() / .check()
        # 提取选择器类型 + 参数 + 操作类型 + 值
        ...
```

#### 4.1.2 HARParser — 直接 json.load 解析 HAR

```python
# recorder/har_parser.py

import json
from dataclasses import dataclass
from typing import List, Dict, Optional

@dataclass
class APICall:
    step_index: int              # 在录制序列中的序号
    method: str                  # GET / POST / PUT / DELETE
    url: str                     # 完整 URL
    path: str                    # URL path（去域名）
    request_headers: Dict        # 请求头
    request_body: Optional[Dict] # 请求体（POST/PUT）
    status: int                  # 响应状态码
    response_headers: Dict       # 响应头
    response_body: Optional[Dict]# 响应体
    mime_type: str               # 响应 Content-Type
    timing: Dict                 # 请求耗时
    timestamp: str               # 请求发起时间

class HARParser:
    """解析 Playwright HAR 文件，提取 API 调用序列
    
    不依赖 haralyzer，直接 json.load 解析标准 HAR 1.2 JSON
    更可控，避免第三方库兼容问题
    """
    
    def __init__(self, url_filter: str = None):
        self.url_filter = url_filter  # e.g. "**/demand/api/**"
    
    def parse(self, har_path: str) -> List[APICall]:
        with open(har_path, 'r', encoding='utf-8') as f:
            har = json.load(f)
        
        calls = []
        for i, entry in enumerate(har["log"]["entries"]):
            req = entry["request"]
            res = entry["response"]
            
            url = req["url"]
            if self.url_filter and not self._match_filter(url):
                continue
            
            # 解析 request body
            req_body = None
            if req.get("postData"):
                post_data = req["postData"]
                if post_data.get("mimeType", "").startswith("application/json"):
                    try:
                        req_body = json.loads(post_data.get("text", "{}"))
                    except json.JSONDecodeError:
                        req_body = {"_raw": post_data.get("text", "")}
                else:
                    req_body = {"_raw": post_data.get("text", ""), 
                               "_mime": post_data.get("mimeType", "")}
            
            # 解析 response body
            res_body = None
            content = res.get("content", {})
            if content.get("text"):
                mime = content.get("mimeType", "")
                if "json" in mime:
                    try:
                        res_body = json.loads(content["text"])
                    except json.JSONDecodeError:
                        res_body = {"_raw": content["text"]}
                else:
                    res_body = {"_raw": content["text"][:500]}  # 截断非JSON
            
            calls.append(APICall(
                step_index=i,
                method=req["method"],
                url=url,
                path=self._extract_path(url),
                request_headers={h["name"]: h["value"] for h in req.get("headers", [])},
                request_body=req_body,
                status=res["status"],
                response_headers={h["name"]: h["value"] for h in res.get("headers", [])},
                response_body=res_body,
                mime_type=content.get("mimeType", ""),
                timing=entry.get("timings", {}),
                timestamp=entry.get("startedDateTime", "")
            ))
        
        return calls
    
    def _match_filter(self, url: str) -> bool:
        """简单 glob 匹配（支持 **/api/** 模式）"""
        # 实现略，可用 fnmatch 或简单字符串匹配
        ...
    
    def _extract_path(self, url: str) -> str:
        """从完整 URL 提取 path 部分"""
        from urllib.parse import urlparse
        return urlparse(url).path
```

#### 4.1.3 RecordingWrapper — 两步录制编排器

```python
# recorder/recording_wrapper.py

import subprocess
import time
from pathlib import Path

class RecordingWrapper:
    """编排两步录制流程
    
    Step 1: 启动 codegen → 用户手动操作 → 保存 raw_script.py
    Step 2: 执行 raw_script.py + HAR + Trace（自动，无人值守）
    """
    
    def record(self, module_name: str, target_url: str,
               storage_state: str = "login_state/storage_state.json",
               har_url_filter: str = "**/api/**"):
        
        output_dir = Path(f"output/modules/{module_name}")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Step 1: codegen 录制
        raw_script = output_dir / "raw_script.py"
        self._run_codegen(
            target_url=target_url,
            output=str(raw_script),
            storage_state=storage_state,
        )
        
        # Step 2: 回放 + HAR + Trace
        api_har = output_dir / "api.har"
        trace_file = output_dir / "trace.zip"
        self._replay_with_har(
            script_path=str(raw_script),
            har_path=str(api_har),
            trace_path=str(trace_file),
            storage_state=storage_state,
            har_url_filter=har_url_filter,
        )
        
        return {
            "raw_script": str(raw_script),
            "api_har": str(api_har),
            "trace": str(trace_file),
        }
    
    def _run_codegen(self, target_url: str, output: str, storage_state: str):
        """启动 Playwright codegen，用户在此期间手动操作浏览器"""
        cmd = [
            "npx", "playwright", "codegen",
            "--target=python-pytest",
            f"--output={output}",
            f"--load-storage={storage_state}",
            "--viewport-size=1366,768",
            "--test-id-attribute=data-testid",
            target_url,
        ]
        subprocess.run(cmd)  # 阻塞直到用户关闭浏览器
    
    def _replay_with_har(self, script_path: str, har_path: str,
                         trace_path: str, storage_state: str,
                         har_url_filter: str):
        """执行 raw_script.py 并同时录制 HAR + Trace
        
        通过 pytest conftest 注入 HAR/Trace 上下文
        """
        # 生成临时 wrapper 脚本，在 raw_script 外层包装 HAR/Trace 上下文
        wrapper = self._generate_wrapper(
            script_path, har_path, trace_path, storage_state, har_url_filter
        )
        subprocess.run(["python3", "-m", "pytest", wrapper, "-x"])
```

### 4.2 模块编排引擎

```python
# orchestrator/graph.py

from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional
import json

@dataclass
class ModuleDefinition:
    id: str                             # "create_demand"
    name: str                           # "创建采购需求"
    raw_script_path: str                # codegen 脚本路径
    har_path: str                       # HAR 文件路径
    selectors: List[Dict]               # 提取的选择器列表
    api_endpoints: List[Dict]           # 提取的 API 端点列表
    extract_variables: List[Dict]       # [{"name": "demand_id", "from_api": "...", "from_field": "data.id"}]
    required_params: List[Dict]         # [{"name": "title", "type": "string", "source": "external"}]

class DependencyGraph:
    """模块依赖图引擎
    
    - AI 自动推断模块间依赖（参数传递链）
    - 支持人工确认/编辑
    - 拓扑排序计算执行顺序
    """
    
    def __init__(self):
        self.modules: Dict[str, ModuleDefinition] = {}
        self.edges: Dict[str, Set[str]] = {}  # module_id → 依赖的 module_id 集合
        self.variable_map: Dict[str, Dict] = {}  # variable_name → {producer_module, field_path}
    
    def add_module(self, module: ModuleDefinition):
        self.modules[module.id] = module
        # 注册产出变量
        for var in module.extract_variables:
            self.variable_map[var["name"]] = {
                "producer": module.id,
                "from_api": var.get("from_api", ""),
                "from_field": var.get("from_field", ""),
            }
        # 检查消费变量 → 建立依赖边
        for param in module.required_params:
            if param["name"] in self.variable_map:
                producer = self.variable_map[param["name"]]["producer"]
                self.edges.setdefault(module.id, set()).add(producer)
    
    def get_execution_order(self, target_module: str) -> List[str]:
        """拓扑排序 → 返回从根到 target 的前置链"""
        chain = []
        visited = set()
        def dfs(module_id: str):
            if module_id in visited:
                return
            visited.add(module_id)
            for dep in self.edges.get(module_id, set()):
                dfs(dep)
            chain.append(module_id)
        dfs(target_module)
        return chain
    
    def save(self, path: str = "knowledge/dependency_graph.json"):
        data = {
            "modules": {k: v.__dict__ for k, v in self.modules.items()},
            "edges": {k: list(v) for k, v in self.edges.items()},
            "variable_map": self.variable_map,
        }
        with open(path, 'w') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
```

```python
# orchestrator/ai_inference.py

class AIDependencyInferrer:
    """AI 依赖推断器
    
    对比各模块的 API 参数依赖链，自动推断模块间依赖关系
    使用 project3 已有的 ai/provider.py
    """
    
    def __init__(self, ai_provider):
        self.ai = ai_provider
    
    def infer(self, module: ModuleDefinition, existing_modules: Dict[str, ModuleDefinition]) -> List[str]:
        """推断 module 依赖哪些已有的模块
        
        核心逻辑:
        1. 提取 module 的 HAR 中所有 API 请求的参数
        2. 检查这些参数是否在已有模块的 API 响应中产出
        3. 如果匹配 → 建立依赖关系
        4. 模糊匹配的给 AI 判断（如 demandId vs demand_id）
        """
        dependencies = []
        for api in module.api_endpoints:
            if api["method"] in ("POST", "PUT") and api.get("request_body"):
                # 检查 request_body 中的字段是否来自其他模块的 response
                for field_name, field_value in self._flatten_body(api["request_body"]):
                    for existing_id, existing_module in existing_modules.items():
                        for var in existing_module.extract_variables:
                            if self._is_match(field_name, var["name"]):
                                dependencies.append(existing_id)
        
        # 去重
        return list(set(dependencies))
    
    def _flatten_body(self, body: dict, prefix="") -> List[tuple]:
        """递归展平嵌套 JSON body"""
        ...
    
    def _is_match(self, field_name: str, var_name: str) -> bool:
        """模糊匹配字段名（驼峰/下划线/缩写）"""
        ...
```

### 4.3 三层断言框架

```python
# assertion/ui_assertion.py

from playwright.sync_api import Page, expect

class UIAssertion:
    """UI 层断言 — 基于 Playwright expect API"""
    
    def assert_visible(self, page: Page, text: str):
        expect(page.get_by_text(text)).to_be_visible()
    
    def assert_url_contains(self, page: Page, path: str):
        expect(page).to_have_url(lambda url: path in url)
    
    def assert_element_count(self, page: Page, selector: str, count: int):
        expect(page.locator(selector)).to_have_count(count)

# assertion/api_assertion.py

class APIAssertion:
    """API 层断言 — 对比 HAR 基线 vs 实时响应"""
    
    def assert_status(self, api_call: APICall, expected_status: int = 200):
        assert api_call.status == expected_status
    
    def assert_code(self, response_body: dict, expected_code: int = 0):
        assert response_body.get("code") == expected_code
    
    def assert_field_value(self, response_body: dict, field_path: str, expected_value):
        """支持变量模板: field_path="data.demand_id", expected_value="{{demand_id}}" """
        actual = self._get_nested(response_body, field_path)
        assert actual == expected_value, f"Expected {expected_value}, got {actual}"

# assertion/db_assertion.py

import pymysql

class DBAssertion:
    """MySQL 数据库断言层"""
    
    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        self.conn_params = {
            "host": host, "port": port,
            "user": user, "password": password,
            "database": database
        }
        self._available = None
    
    @property
    def available(self) -> bool:
        """检查 DB 是否可连接，不可用时自动跳过"""
        if self._available is None:
            try:
                conn = pymysql.connect(**self.conn_params, connect_timeout=3)
                conn.close()
                self._available = True
            except Exception:
                self._available = False
        return self._available
    
    def assert_record_exists(self, table: str, conditions: dict, variables: dict = None):
        """断言记录存在，支持变量模板
        conditions: {"id": "{{demand_id}}", "status": "draft"}
        variables: {"demand_id": "XQ-2026-00518964"}
        """
        if not self.available:
            return  # 静默跳过
        
        resolved = self._resolve_variables(conditions, variables)
        where = " AND ".join(f"{k}=%s" for k in resolved.keys())
        sql = f"SELECT COUNT(*) FROM {table} WHERE {where}"
        
        conn = pymysql.connect(**self.conn_params)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, list(resolved.values()))
                count = cur.fetchone()[0]
                assert count > 0, f"No record found in {table} where {resolved}"
        finally:
            conn.close()
```

### 4.4 自愈机制（playwright-healer 集成）

```python
# self_healing/fixture.py

"""
集成策略:
1. 安装 playwright-healer: pip install playwright-healer
2. 在 conftest.py 中注册 healing_page fixture（healer 自注册，无需额外配置）
3. 代码中用 healing_page 替代 page
4. healer 自动拦截选择器失败 → 按5层流水线修复 → 自动写回源文件

环境变量配置:
  DEEPSEEK_API_KEY=sk-xxx          # 百炼 DeepSeek key
  DEEPSEEK_MODEL=deepseek-v4-pro   # 模型名
  PH_STRATEGY=SMART                # 策略: SMART/HEURISTIC_ONLY/FULL
  PH_PREFER_ARIA=true              # 优先修复为 ARIA 选择器
  PH_AUTO_PATCH_SOURCE=true        # 自动修补源代码
  PH_PATCH_SOURCE_BACKUP=true      # 修补前备份原文件
"""

# conftest.py — 只需这几行即可启用自愈
"""
import pytest

# playwright-healer 会自动注册 healing_page fixture
# 无需额外代码，只需安装包 + 配置环境变量
"""

# 脚本模板 — 从 codegen 输出转换为 healer 兼容
# codegen 生成:
#   def test_create_demand(page: Page):
#       page.get_by_role("button", name="提交").click()
#
# healer 兼容（自动转换）:
#   def test_create_demand(healing_page):  # 替换 page → healing_page
#       healing_page.get_by_role("button", name="提交").click()
#       # 如果选择器失效 → healer 自动修复，无需手动干预
```

```python
# self_healing/accessibility_locator.py（预留，P2 迭代）

"""
当 playwright-healer 遇到天花板时的增强方案:
- healer 的 AI 定位依赖 DeepSeek 文本分析
- 但 accessibility snapshot 提供结构化语义树，比纯文本更精确
- 这个模块在 healer 无法修复时作为二次兜底

实现思路:
1. page.accessibility.snapshot() → 获取页面对象树
2. 在树中搜索 role + name 匹配的节点
3. 如果找到 → 计算到该节点的选择器路径
4. 如果没找到 → 发送 accessibility tree 片段给 AI
5. AI 返回定位策略 → 验证 → 写入知识库

技术要点:
- page.accessibility.snapshot() 返回嵌套 dict
- 每个节点有: role, name, value, description, checked, disabled, focused 等
- 可以用递归遍历 + 模糊匹配实现高效语义搜索
"""
```

---

## 五、新项目目录结构

```
smart-test-automation/
├── config/                          # 复用 from project3
│   ├── __init__.py
│   ├── accounts.py                  # 账号管理
│   └── test_config.py               # 环境配置
│
├── core/                            # 复用 from project3
│   ├── __init__.py
│   ├── api_client.py                # API 客户端（断言层用）
│   └── auth_manager.py              # 认证管理
│
├── ai/                              # 复用 from project3
│   ├── __init__.py
│   ├── provider.py                  # AI Provider（百炼 DeepSeek/GLM）
│   ├── models_config.json           # 模型配置
│   └── dependency_analyzer.py       # AI 依赖推断（已有，增强了）
│
├── login_state/                     # 复用 from project3
│   └── storage_state.json
│
├── save_login_state.py              # 复用 from project3
│
├── recorder/                        # 新建 — 数据获取层
│   ├── __init__.py
│   ├── codegen_parser.py            # codegen 脚本 AST 解析器
│   ├── har_parser.py                # HAR JSON 直接解析器
│   ├── recording_wrapper.py         # 两步录制编排器
│   └── script_transformer.py        # raw_script → healer 兼容转换
│
├── orchestrator/                    # 新建 — 模块编排引擎
│   ├── __init__.py
│   ├── module_definition.py         # 模块定义数据模型
│   ├── graph.py                     # 依赖图引擎
│   ├── composer.py                  # 执行计划编排器
│   ├── ai_inference.py              # AI 依赖推断器
│   └── variable_resolver.py         # 变量传递解析器
│
├── assertion/                       # 新建 — 三层断言框架
│   ├── __init__.py
│   ├── ui_assertion.py              # Playwright UI 断言
│   ├── api_assertion.py             # API 响应断言
│   ├── db_assertion.py              # MySQL 数据库断言
│   ├── report.py                    # 三层断言报告
│   └── assertion_rule.py            # 断言规则数据模型
│
├── self_healing/                    # 新建 — 自愈机制
│   ├── __init__.py
│   ├── fixture_integration.py       # healer fixture 集成指南
│   ├── accessibility_locator.py     # 预留: AI 语义定位器(P2)
│   └── knowledge_sync.py            # 预留: healer缓存→SQLite同步(P2)
│
├── knowledge/                       # 知识库存储
│   ├── dependency_graph.json        # 模块依赖图
│   └── modules/                     # 模块定义
│       ├── create_demand.json
│       ├── audit_demand.json
│       └── confirm_demand.json
│
├── output/                          # 录制产物输出
│   ├── modules/
│   │   └── create_demand/
│   │       ├── raw_script.py        # codegen 生成的脚本
│   │       ├── enhanced_script.py   # healer兼容+断言注入
│   │       ├── api.har              # HAR 文件
│   │       └── trace.zip            # Trace 文件
│   └── reports/                     # 断言报告
│
├── tests/                           # 测试入口
│   ├── conftest.py                  # healer fixture 注册
│   └── test_chains/                 # 业务链测试
│       └── test_demand_flow.py
│
├── conftest.py                      # 顶层 fixture 配置
├── cli.py                           # CLI 入口（P2）
├── requirements.txt
├── .env                             # 复用 from project3
├── .gitignore
└── README.md
```

---

## 六、依赖清单

```
# requirements.txt
playwright>=1.59.0
pytest>=8.0
pytest-playwright>=0.5.0
playwright-healer>=1.0.7       # 自愈引擎
pymysql>=1.1.0                 # MySQL 断言层
python-dotenv>=1.0.0           # 环境变量（注意 Python 3.14 兼容性）
```

**注意**：不再依赖 `haralyzer`，HAR 解析直接用 `json.load`。

---

## 七、阶段性交付计划

### Phase 1: 数据获取层 + 自愈集成（3天）

| 天 | 任务 | 产出 |
|----|------|------|
| Day 1 | 创建项目骨架 + 复用层 + 安装依赖 + CodegenScriptParser | 项目可运行 + AST 解析器 |
| Day 2 | HARParser + RecordingWrapper（两步录制） + ScriptTransformer | 完整录制流程可用 |
| Day 3 | playwright-healer 集成 + 百炼 DeepSeek 配置验证 + 用采购系统跑一次完整录制 | 自愈功能验证 ✅ |

**Phase 1 交付物**：
- ✅ codegen 录制 → raw_script.py（含精准选择器）
- ✅ 回放 + HAR → api.har（含完整请求/响应数据）
- ✅ healer 集成 → 选择器失效自动修复
- 🎯 **验证命令**：一条命令完成录制，一条命令回放验证

### Phase 2: 模块编排 + AI 依赖推断（3天）

| 天 | 任务 | 产出 |
|----|------|------|
| Day 4 | ModuleDefinition 数据模型 + DependencyGraph 引擎 | 依赖图核心逻辑 |
| Day 5 | AI 依赖推断器 + 变量传递解析器 | AI 自动推断模块依赖 |
| Day 6 | Composer 执行编排 + 用 2-3 个实际模块验证编排链 | 前置链执行验证 ✅ |

**Phase 2 交付物**：
- ✅ 录制多个模块 → AI 自动推断依赖关系
- ✅ 指定目标模块 → 自动计算前置链 + 按序执行
- ✅ 模块间变量自动传递（demand_id 等）
- 🎯 **验证场景**：create_demand → audit_demand 自动编排执行

### Phase 3: 三层断言框架（2天）

| 天 | 任务 | 产出 |
|----|------|------|
| Day 7 | UIAssertion + APIAssertion + 断言规则模型 | UI/API 两层断言 |
| Day 8 | DBAssertion + Report 汇总 + DB 不可用自动跳过 | 三层断言完整 ✅ |

**Phase 3 交付物**：
- ✅ UI 断言（元素可见/URL/数量）
- ✅ API 断言（status/code/字段值）+ 变量模板
- ✅ MySQL 断言（记录存在/字段值）+ DB 不可用自动跳过
- ✅ 三层汇总报告
- 🎯 **验证场景**：create_demand 执行后 UI+API+DB 三层全验证

### Phase 4: 打磨 + 文档 + Skill（2天，可选）

| 天 | 任务 | 产出 |
|----|------|------|
| Day 9 | CLI 入口 + 错误处理 + 边界场景 | cli.py 可用 |
| Day 10 | Skill 斜杠命令 + README + 录制视频演示 | 文档齐全 |

---

## 八、关键技术风险与对策

| 风险 | 概率 | 影响 | 对策 |
|------|------|------|------|
| playwright-healer 不支持百炼自定义 base_url | 中 | 高 | 查看 healer 源码确认；不行就 fork 改一行 base_url |
| codegen 生成的脚本回放时行为不确定 | 中 | 高 | Step2 回放失败时提示用户手动重录；Trace 文件协助调试 |
| AI 依赖推断不准 | 中 | 中 | 生成草稿后人工确认；提供 Web UI 编辑器（P3） |
| MySQL 内网不可达 | 高 | 低 | DB 断言层自动跳过，不影响 UI/API 断言 |
| playwright-healer 异步优先，同步支持弱 | 低 | 中 | healer 1.0.7 已支持 sync；如不行用 asyncio.run 包装 |

---

## 九、与 project3 的关系

| 维度 | 说明 |
|------|------|
| 继承 | config/, core/, ai/, login_state/, save_login_state.py, .env 直接复制 |
| 斩断 | playwright_recorder/, api_analyzer/, models/data_models.py 不再使用 |
| 新建 | recorder/, orchestrator/, assertion/, self_healing/ 全新实现 |
| 并存 | 两个项目独立，新项目不修改 project3 任何文件 |

---

## 十、成功标准

| 验证项 | 标准 |
|--------|------|
| 🎬 录制 | 一条命令录制模块，UI 操作 + API 数据零遗漏 |
| 🔄 自愈 | 选择器变更后，healer 自动修复率 ≥ 80% |
| 🔗 编排 | 指定目标模块，自动计算前置链并按序执行 |
| 📊 断言 | 三层断言（UI+API+DB）汇总报告，DB 不可用自动跳过 |
| 🤖 AI | 依赖推断准确率 ≥ 70%（草稿+人工确认） |
| ⏱️ 效率 | 录制一个模块 ≤ 10 分钟（含手动操作） |
