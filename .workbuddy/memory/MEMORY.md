# 项目长期记忆

## 项目定位：Playwright 通用录制工具（playwright_luzhi）

基于 Pytest 架构开发通用录制工具，借助原生 Playwright 能力捕获用户操作、生成带元素定位器的 UI 自动化步骤、拦截全部网络接口请求，并依托大模型分析接口调用依赖关系。

### 核心分工（铁律）
- **UI 自动化 = 原生 Playwright Python**：使用 `playwright.sync_api` 编写，独立可运行，不依赖 Pytest 执行
- **接口自动化 = Pytest 框架**：使用 `class TestXxx` / `def test_xxx` / fixture / assert 规范
- **工具整体架构 = Pytest 项目结构**：conftest.py、fixture、测试用例模块、工具模块

### 最终代码结构
```
playwright_recorder/  — UI 录制核心模块（原生 Playwright）
tests/api/            — 接口自动化用例（Pytest）
conftest.py           — Pytest fixture 配置
output/ui/            — 导出的 UI 脚本（Playwright）
output/api/           — 导出的接口用例（Pytest）
report/               — 依赖分析报告
```

### 关键约束
- 不使用 Node.js、不使用浏览器扩展
- 界面操作录制参照 Playwright codegen 生成稳定定位器
- 定位优先级：data-testid > 无障碍属性 > 语义属性 > CSS/XPath
- 录制后自动执行流程：保存UI脚本 → 保存接口用例 → 自动调试UI脚本 → 自动生成接口测试用例 → 全部无误后通知用户
- 三类产物：UI 自动化脚本、接口自动化用例、接口依赖分析报告

### 技术栈
- Python 3.11+ / Pytest / Playwright Python
- LLM 大模型接口依赖分析
- JSON 结构化接口数据存储
- 支持配置浏览器类型、无头模式、输出路径、资源过滤规则

### 运行环境约定
- **执行 Python 脚本必须用 `python3`**（非 `python`）
- Playwright Chrome 浏览器装在 `python3` 环境下（`python3 -m playwright install chromium`）
- 运行命令示例：`python3 script.py`、`python3 -m pytest`

### 项目合并记录（2026-05-22）
- 项目1（简单版）：`scripts/skill_generator/core/` 下有 recorder/ui_listener/api_capturer 等
- 项目2（完整版，含登录账号/UI脚本）：`core/` + `config/` + `scripts/recorder/` + `utils/` + `fixtures/` + `tests/`
- 合并产出：`project3/` — 39个关键文件，25/26 模块导入验证通过
- 废弃文件：unified_recorder.py, ai_recorder.py, record_api_requests.py, generate_ui_script.py, generate_scripts.py, enhanced_recorder.py, db_client.py, redis_client.py, playwright_client.py
- 修复项：AccountManager调用bug、硬编码路径、明文凭据→环境变量
- 待办：mock_data_helper需要pymysql依赖（非核心），可后续补充测试示例

### 已修复：录制器端到端验证 ✅
- **根因**：`UIListener._generate_selector()` 在 `expose_binding` 回调中调用 Playwright 同步 API（如 `page.get_by_xxx().count()`），导致 fiber 事件循环死锁
- **修复方案**：将选择器生成改为纯字符串拼接（不调用 Playwright API），唯一性验证延迟到脚本生成阶段
- **修改文件**：`project3/playwright_recorder/ui_listener.py` 的 `_generate_selector()` 方法
- **附带修复**：`recorder.py` 关闭时先 `unroute("**/*")` 避免取消错误，先关 context 再关 browser
- **测试结果**：端到端验证全部通过，三类产物正确生成
  - ✅ 录制→UI 操作捕获→脚本生成→独立运行
  - ✅ API 拦截→JSON 存储→Pytest 用例生成
  - ✅ 测试脚本：`project3/test_e2e.py`

### QA 验收通过 ✅（2026-05-22）
- 端到端测试全流程通过：录制 → UI脚本生成 → API用例生成
- 生成的 UI 脚本可用 `python3 script.py` 独立运行 ✅
- 生成的定位器 `page.get_by_role('link', name='Learn more')` 在 Python Playwright 中正确执行 ✅
- SmartTestGenerator 已有 JS→Python 选择器转换逻辑（getByRole→get_by_role 等）✅
- 测试脚本：`project3/test_e2e.py`、`project3/test_e2e_full.py`
- 已知小问题：Playwright 关闭时的 `TargetClosedError` 异步警告，不影响功能

### AI Provider 已配置 ✅（2026-05-22）
- 默认：腾讯云 TokenPlan / GLM-5.1
- 可用模型：glm-5.1、minimax-2.7、qwen3.7-max、qwen3.6-plus、dashscope-glm-5.1、deepseek-v4-pro、minimax、zhipu、openai、ollama
- API Key 存储在 `project3/.env`（已加入 .gitignore）
- 修复：URL 拼接 bug（腾讯云 TokenPlan URL 已含 /chat/completions，不可重复拼接）
- 验证：GLM-5.1 ✅、Qwen3.7-Max ✅、意图分析链路 ✅

### 登录态持久化 ✅（2026-05-22）
- recorder.py 支持 `storage_state` 加载/保存
- 默认视口 1366×768
- `save_login_state.py` 交互式登录工具（处理验证码）
- `login_state/storage_state.json` 保存登录态（已加入 .gitignore）
- SSO 登录页有验证码，必须手动登录保存状态
- 切换账号：`python3 save_login_state.py --fresh`
- 查看状态：`python3 save_login_state.py --info`

### 采购管理系统真实业务验证 ✅（2026-05-22）
- 账号 tmind_admin / Zfcg@123456 登录成功（**无需验证码，headless 可行**）
- SSO 登录流程：填写 input[name=username/password] → 点击 .doraemon-checkbox-inner → 点击 .login-btn → 等待 SSOSESSION/SESSION cookie
- 登录后自动跳转 `demand_front/#/review/demand/list`（审批列表页）
- 登录态保存在 `login_state/storage_state.json`（12+ cookies，含 SSOSESSION/SESSION）
- **待我审批列表有 10 行数据**（XQ-2026-00518964 等），之前 API 场景数据为空是因为 URL 用错了（用的是 purchase 子域而非 www 子域）
- 正确 URL：`https://www.test.zcygov.cn/demand_front/#/review/demand/waitReview?_app_=zcy.demand`
- **审核按钮是 `<A>` 标签**（不是 BUTTON），在操作列，位于坐标约 (1134, 277)
- 点击审核后跳转详情页：`#/review/demand/review/7462485552018720787?audit=true`
- API 完整链路（44个）已验证：列表→详情有明确数据依赖
  - 列表 API：`POST /demand/api/demand/list/getMyApprovalDemandManageList`
  - 详情 API：`GET /demand/api/demand/detail/{id}`（id 来自列表返回）
  - 流程 API：`GET /demand/api/workflow/get/scheule/{id}/1`
- 验证脚本：`project3/debug_click_v2.py`、`project3/run_recorder.py`

### 关键 Bug：page.route() 阻塞页面交互 ✅已修复（2026-05-22）
- **根因**：`page.route("**/*", handler)` + `route.fetch()` + `route.fulfill()` 在 Playwright 事件循环中同步执行，阻塞页面交互（点击按钮无响应）
- **修复方案**：改用 `page.on("request")` + `page.on("response")` 纯监听模式，不拦截/不阻塞请求
- **修改文件**：
  - `recorder.py`：删除 `_handle_route()`，新增 `_on_request()` / `_on_response()` + `_pending_requests` 字典
  - `special_handlers.py`：TabManager.register_page() 和 IFrameHandler.on_frame_attached() 不再注册 route handler
- **注意**：纯监听模式无法修改请求/响应（不能 mock），但录制场景不需要此能力

### 踩坑经验
- `python-dotenv` 的 `load_dotenv()` 在 Python 3.14 报 `AssertionError`（`frame.f_back is None`），改用手动读取 .env 文件
- SSO 登录后 URL 仍显示 login 页（前端路由未更新），需用 cookie 判断登录状态而非 URL
- 采购系统正确域名为 `www.test.zcygov.cn`（不是 `purchase.test.zcygov.cn` 后者会跳转到旧平台）
- `page.route()` 会阻塞页面交互！录制工具必须用 `page.on("request"/"response")` 纯监听模式
- Playwright headless=True 下 SSO 登录可正常工作（tmind_admin 无验证码），不需要交互式浏览器

### 项目重构决策（2026-06-04）
- project3 的 JS注入 + page.on 监听架构被否决，改用 Playwright 官方能力
- 新项目名：smart-test-automation，独立于 project3
- 核心技术栈：codegen(录制) + HAR(网络) + playwright-healer(自愈) + 百炼DeepSeek(AI)
- 录制方式：两步录制（先codegen手动操作，再回放+HAR+Trace自动采集）
- HAR解析：直接json.load自解，不依赖haralyzer
- 核心差异化：模块编排器(依赖图+前置链+变量传递) + 三层断言(UI+API+MySQL)
- 自愈：先用playwright-healer(5层流水线)，P2预留自建accessibility snapshot定位器
- 融合方案文档：smart-test-v3-merged-plan.md
- 最终落地方案：smart-test-final-plan.md（v4 Final）
- 最终合并方案：smart-test-final-plan-v5.md（v5 Final，合并版）

### 自愈框架评估结论（2026-06-04）
- playwright-healer ✅：Python原生 + DeepSeek内置 + 免费 + 确定性修复 → 采用
- ZeroStep ❌：仅TypeScript + 强制OpenAI + SaaS付费 + 非确定 → 不适用
- @testmate-agent/core ❌：TypeScript + 强制Anthropic + v0.1.0个人开发 → 不适用

### 前端配合策略更新（2026-06-04）
- ❌ 推动前端补 testid 不现实，前端永远有更优先需求
- ✅ 零前端配合也能完整运行：role/text(80%) + healer(15%) + 人工调Trace(5%)
- 加分项（非前提）：前端愿加 testid → 选择器永不失效；按钮文案变更通知 QA
- codegen 录制不加 --test-id-attribute 参数（没有 testid 可用）

### 最终合并方案 v5 Final（2026-06-04）
- 合并了两版方案最优决策，文件：smart-test-final-plan-v5.md
- 关键调整：知识库用 healer 内置 SelectorStore JSON（不用 SQLite）；自愈 4 级（去掉 AI 视觉层）；零前端配合约束；8-10 天工期
- 工期缓冲：承诺 8-10 天（原 6-8 天 + 2 天风险缓冲）

### 待完善项
- tests/api/ 下的实际业务用例示例
- SmartTestGenerator 生成的脚本需配置登录账号才能完整运行

## 更新日志
- 2026-05-22: 初始化项目长期记忆，记录核心分工铁律和架构约束
- 2026-05-22: 合并项目1+项目2到project3，创建干净项目代码，39个文件
