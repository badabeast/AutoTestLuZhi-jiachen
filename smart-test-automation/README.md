# 智能测试执行系统 v5

基于 Playwright + Pytest + playwright-healer + AI 的端到端自动化测试框架。

## 核心流程

```
人工录制模块操作 → AI 自动推断依赖关系 → 自动编排前置链 → 三层断言验证 → healer 自愈保障稳定性
```

## 技术栈

| 组件 | 用途 |
|------|------|
| Playwright codegen | UI 操作录制 |
| Playwright HAR | API 请求/响应捕获 |
| Playwright Trace | 执行回溯 |
| playwright-healer | 选择器失效自动修复（4级策略链） |
| Pytest | 测试运行框架 |
| AI（DeepSeek/GLM） | 依赖推断、语义修复 |

## 快速开始

### 1. 环境准备

```bash
# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器
playwright install chromium

# 复制环境变量配置并填写
cp .env.example .env
```

### 2. 保存登录态

```bash
python3 save_login_state.py
```

在弹出的浏览器中完成登录，关闭浏览器后自动保存到 `login_state/storage_state.json`。

### 3. 录制业务模块

```bash
python3 cli.py record create_demand --url "https://your-target.com/page/"
```

浏览器弹出后手动操作业务流程，关闭浏览器自动完成：
- codegen 脚本录制
- HAR 接口捕获
- AST 解析 + AI 分析
- 增强脚本生成（healer 兼容）
- PO 分层封装

### 4. 编排执行测试链

```bash
# 查看编排计划
python3 cli.py compose confirm_demand

# 执行测试链（自动按依赖顺序执行前置模块）
python3 cli.py run confirm_demand
```

### 5. 查看报告

```bash
python3 cli.py report
```

## CLI 命令一览

| 命令 | 说明 |
|------|------|
| `python3 cli.py record <模块名>` | 录制业务模块（两步录制法） |
| `python3 cli.py replay <模块名>` | 重放已有脚本，重新生成 HAR/Trace |
| `python3 cli.py run <目标模块>` | 编排 + 执行测试链 |
| `python3 cli.py compose <目标模块>` | 查看编排计划（不执行） |
| `python3 cli.py generate-script <模块名>` | 生成增强脚本 |
| `python3 cli.py heal <模块名>` | 手动触发自愈 |
| `python3 cli.py report` | 查看断言报告 |
| `python3 cli.py list` | 列出已录制模块 |
| `python3 cli.py query-knowledge` | 查询知识库 |

## 项目结构

```
smart-test-automation/
├── cli.py                    # CLI 统一入口
├── conftest.py               # Pytest 全局配置（healer fixture）
├── requirements.txt          # Python 依赖
├── recorder/                 # 录制模块
│   ├── recording_wrapper.py  # 两步录制编排器
│   ├── codegen_parser.py     # AST 解析 codegen 输出
│   ├── har_parser.py         # HAR JSON 解析
│   ├── script_transformer.py # 脚本转换 + PO 分层生成
│   └── guards.py             # 登录守卫 + 弹窗守卫
├── scheduler/                # 编排引擎
│   ├── graph.py              # 依赖图 + 拓扑排序
│   ├── composer.py           # 执行计划编排
│   ├── orchestrator.py       # 测试链执行引擎
│   ├── smart_inference.py    # AI 智能依赖推断
│   ├── variable_resolver.py  # 跨模块变量传递
│   └── module_definition.py  # 模块数据模型
├── assertion/                # 三层断言
│   ├── engine.py             # 断言引擎统一入口
│   ├── ui_assertion.py       # UI 层断言
│   ├── api_assertion.py      # API 层断言
│   ├── db_assertion.py       # DB 层断言（不可达自动跳过）
│   └── report.py             # 报告生成
├── self_healing/             # 自愈配置
│   └── healer_config.py      # healer AI Provider 配置
├── ai/                       # AI 服务
│   ├── provider.py           # AI Provider（多模型支持）
│   └── dependency_analyzer.py # 依赖分析
├── config/                   # 配置管理
│   ├── accounts.py           # 账号管理
│   ├── env_loader.py         # .env 加载
│   └── test_config.py        # 环境配置
├── core/                     # 基础服务
│   ├── api_client.py         # API 客户端
│   └── auth_manager.py       # 认证管理
├── knowledge/                # 知识库（运行时生成，gitignore）
├── output/                   # 录制产物（运行时生成，gitignore）
└── login_state/              # 登录态（gitignore）
```

## 自愈四级策略

| 级别 | 策略 | 说明 |
|------|------|------|
| L1 | 缓存命中 | 从历史修复记录查找 |
| L2 | 启发式匹配 | 同义文本/相似属性/临近元素 |
| L3 | DOM 结构匹配 | Levenshtein 距离 + accessibility tree |
| L4 | AI 语义修复 | DOM 片段 + 语义描述 → AI 返回新选择器 |

## 三层断言

| 层 | 断言内容 | 示例 |
|----|---------|------|
| UI | 元素可见性、文本、URL | "提交成功"提示可见 |
| API | 状态码、业务 code、响应字段 | POST /demand/create → code=0 |
| DB | 记录存在、字段值 | 数据库中记录状态为 draft |

## 环境变量

在 `.env` 中配置以下变量（参考 `.env.example`）：

```bash
# 测试目标
WEB_DEMAND_ACCOUNT=your_account
WEB_DEMAND_PASSWORD=your_password

# AI 平台（healer L4 语义修复）
ANTHROPIC_AUTH_TOKEN=your_api_key
ZCY_HEALER_API_URL=https://your-ai-platform/api/v1/messages
ZCY_HEALER_MODEL=glm-5.1

# 数据库（可选，DB 断言需要）
MYSQL_HOST=
MYSQL_PORT=3306
MYSQL_USER=
MYSQL_PASS=
MYSQL_DB=
```

## 运行 Demo

```bash
python3 demo_e2e_flow.py
```

无浏览器环境下验证各模块功能：AST 解析、HAR 解析、脚本转换、依赖推断、三层断言、报告生成。
