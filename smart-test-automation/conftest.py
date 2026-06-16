"""
smart-test-automation conftest.py

playwright-healer 自愈配置:
  - healing_config / healing_page 由 playwright-healer 插件自动注册
    (通过 entry_point pytest11，无需在此处定义)
  - 本文件仅负责: 浏览器上下文配置、登录守卫、测试报告 Hooks
  - 自愈参数通过 pytest.ini 的 addopts 或命令行 --ph-* 传入
  - LocatorActionError 自动采集并写入 JSON 报告供 heal_runner 使用

登录态管理:
  - browser_context_args: 加载 storage_state 并清洗 expires=-1 cookie
  - login_state_health_check: session 级 fixture，测试前验证登录态有效性
"""

import json
import os
import time
import traceback

import pytest

from config.env_loader import load_env

# 加载 .env（统一工具函数，支持引号和注释）
load_env()

# 导入通用定位错误异常
from core.locator_error import LocatorActionError


# 自愈错误报告文件路径
HEAL_REPORT_PATH = os.path.join(os.path.dirname(__file__), "output", "heal_report.json")


# LiteReport 截图辅助函数

def screenshot(page, request, label=""):
    """捕获一步截图并附加到 LiteReport 报告

    用法（在测试用例中）:
        from conftest import screenshot
        screenshot(page, request, "1. 打开首页")
    """
    import base64
    try:
        b64 = base64.b64encode(page.screenshot(full_page=True)).decode("utf-8")
        data_uri = f"data:image/png;base64,{b64}"
        request.node.user_properties.append(
            ("screenshot", {"label": label, "data": data_uri})
        )
    except Exception as e:
        print(f"\n[SCREENSHOT] 截图失败: {e}")


# healer 自愈配置

@pytest.fixture(scope="session")
def healing_config():
    """healer 配置：复用 self_healing/healer_config.py 的统一配置"""
    from self_healing.healer_config import get_healer_config
    return get_healer_config()


# 登录态 Cookie 清洗工具

def _sanitize_storage_state(storage_state_path: str) -> str | None:
    """加载 storage_state.json，清洗 expires=-1 的 session cookie 后写回。

    Playwright 在新浏览器 context 中会忽略 expires=-1 的 cookie，
    导致关键的 SESSION/SSOSESSION 等认证 cookie 丢失。
    修复策略：将 expires=-1 改为 7 天后的 Unix 时间戳。

    Args:
        storage_state_path: storage_state.json 文件路径

    Returns:
        清洗后的文件路径（如果无修改则返回原路径），文件不存在返回 None
    """
    if not os.path.exists(storage_state_path):
        return None

    try:
        with open(storage_state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        print(f"\n[LOGIN] 读取 storage_state 失败: {e}")
        return None

    cookies = state.get("cookies", [])
    if not cookies:
        return storage_state_path

    # 修复 expires=-1 的 session cookie
    seven_days_later = time.time() + 7 * 24 * 3600
    fixed_count = 0
    for cookie in cookies:
        if cookie.get("expires", 0) == -1:
            cookie["expires"] = seven_days_later
            fixed_count += 1
            print(f"[LOGIN] 修复 session cookie: {cookie['name']} (expires=-1 -> 7d)")

    # 检查关键认证 cookie 是否存在且未过期
    now = time.time()
    expired_keys = []
    for cookie in cookies:
        expires = cookie.get("expires", 0)
        if 0 < expires < now:
            expired_keys.append(cookie["name"])

    if expired_keys:
        print(f"[LOGIN] 以下 cookie 已过期: {expired_keys}")

    # 有修复则写回文件
    if fixed_count > 0:
        try:
            with open(storage_state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            print(f"[LOGIN] 已修复 {fixed_count} 个 session cookie 并写回 storage_state")
        except Exception as e:
            print(f"[LOGIN] 写回 storage_state 失败: {e}")

    return storage_state_path


# 浏览器上下文配置

@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, playwright):
    """全局浏览器上下文配置：带登录态、忽略 HTTPS、允许本地网络

    关键修复：加载 storage_state 前先清洗 expires=-1 的 cookie，
    避免 Playwright 在新 context 中忽略 session cookie 导致登录态丢失。
    """
    args = {
        "ignore_https_errors": True,
        "viewport": {"width": 1366, "height": 768},
        "permissions": ["local-network-access"],
    }
    storage_state = "login_state/storage_state.json"
    sanitized_path = _sanitize_storage_state(storage_state)
    if sanitized_path:
        args["storage_state"] = sanitized_path
    else:
        print(f"\n[LOGIN] 未找到有效的 storage_state: {storage_state}")
        print("[LOGIN] 测试将依赖 BasePage._check_and_handle_login 自动登录")
    return args


# 登录态健康检查

@pytest.fixture(scope="session")
def login_state_health_check(browser_context_args):
    """Session 级登录态健康检查：在首个使用该 fixture 的测试前运行。

    检查逻辑:
    1. 如果 storage_state.json 不存在，打印警告（后续由 auto_login 处理）
    2. 检查关键 cookie（SESSION, SSOSESSION）是否过期
    3. 过期则打印预警，但不阻塞测试（由 _check_and_handle_login 兜底）
    """
    storage_state_path = "login_state/storage_state.json"
    if not os.path.exists(storage_state_path):
        print("\n[LOGIN-HEALTH] storage_state.json 不存在，测试将依赖自动登录")
        return {"status": "missing", "cookies": []}

    try:
        with open(storage_state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        print(f"\n[LOGIN-HEALTH] 读取 storage_state 失败: {e}")
        return {"status": "error", "cookies": []}

    cookies = state.get("cookies", [])
    now = time.time()

    # 关键认证 cookie
    auth_cookie_names = ["SESSION", "SSOSESSION"]
    auth_status = {}

    for cookie in cookies:
        name = cookie.get("name", "")
        if name in auth_cookie_names:
            expires = cookie.get("expires", -1)
            if expires == -1:
                auth_status[name] = "session_only"
            elif 0 < expires < now:
                auth_status[name] = "expired"
            else:
                remaining_hours = (expires - now) / 3600
                auth_status[name] = f"valid ({remaining_hours:.1f}h remaining)"

    # 输出健康检查结果
    print(f"\n{'='*50}")
    print("[LOGIN-HEALTH] 登录态健康检查")
    print(f"  存储文件: {storage_state_path}")
    print(f"  Cookie 总数: {len(cookies)}")
    for name, status in auth_status.items():
        icon = "OK" if "valid" in status else ("WARN" if status == "session_only" else "EXPIRED")
        print(f"  [{icon}] {name}: {status}")
    print(f"{'='*50}")

    has_expired = any(v == "expired" for v in auth_status.values())
    if has_expired:
        print("[LOGIN-HEALTH] WARNING: 检测到过期认证 cookie，测试可能遇到登录态问题")
        print("[LOGIN-HEALTH] 建议运行: cd smart-test-automation && python3 login/auto_login.py")

    return {"status": "expired" if has_expired else "ok", "auth_status": auth_status}


# 测试报告 Hooks

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """测试失败时：截图 + 采集 LocatorActionError 写入 JSON 报告"""
    outcome = yield
    report = outcome.get_result()

    if report.when == "call" and report.failed:
        # 获取 page 对象（兼容 healing_page 和原生 page）
        page = None
        hp = item.funcargs.get("healing_page")
        if hp is not None:
            page = getattr(hp, "raw_page", hp)
        if page is None:
            page = item.funcargs.get("page")

        # ── 截图 ──
        screenshot_path = ""
        if page:
            import base64

            screenshot_dir = "output/screenshots"
            os.makedirs(screenshot_dir, exist_ok=True)
            screenshot_path = f"{screenshot_dir}/{item.name}_failed.png"
            try:
                page.screenshot(path=screenshot_path)
                print(f"\n[SCREENSHOT] 失败截图已保存: {screenshot_path}")
            except Exception:
                screenshot_path = ""

            # 附加到 LiteReport（通过 user_properties → 报告截图树）
            try:
                with open(screenshot_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                data_uri = f"data:image/png;base64,{b64}"
                item.user_properties.append(
                    ("screenshot", {"label": "[Auto] 失败截图", "data": data_uri})
                )
            except Exception:
                pass

        # ── 采集 LocatorActionError 写入 JSON 报告 ──
        # 策略层子进程里不写报告，避免和外层进程争抢文件
        if not os.environ.get("STRATEGY_REPAIR_RUNNING"):
            _collect_locator_errors(item, call, report, screenshot_path)


def _collect_locator_errors(item, call, report, screenshot_path: str):
    """从测试失败的异常链中提取 LocatorActionError，写入 JSON 报告

    JSON 报告格式:
    {
      "timestamp": "...",
      "failures": [
        {
          "test_name": "test_xxx",
          "category": "locator",       # locator / assertion / env / unknown
          "action": "click",
          "selector": ".btn-entrance",
          "page_url": "https://...",
          "file": "create_demand_page.py",
          "line": 156,
          "screenshot": "output/screenshots/xxx.png",
          "error_message": "Timeout 5000ms exceeded..."
        }
      ]
    }
    """
    if not call.excinfo:
        return

    # 从异常链中找 LocatorActionError
    exc = call.excinfo.value
    locator_error = None

    # 检查异常本身
    if _is_locator_error(exc):
        locator_error = exc
    # 检查 __cause__ 链（from e 链式异常）
    elif exc.__cause__ and _is_locator_error(exc.__cause__):
        locator_error = exc.__cause__
    # 检查 __context__ 链
    elif exc.__context__ and _is_locator_error(exc.__context__):
        locator_error = exc.__context__

    # 分类错误
    if locator_error:
        category = "locator"
    elif isinstance(exc, AssertionError) or "AssertionError" in type(exc).__name__:
        category = "assertion"
    elif _is_env_error(exc):
        category = "env"
    else:
        # 再检查异常链中是否有定位错误关键词
        tb_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        if any(kw in tb_text for kw in ["waiting for locator", "waiting for selector",
                                          "Locator.wait_for", "Timeout waiting for locator",
                                          "strict mode violation"]):
            category = "locator"
        elif any(kw in tb_text for kw in ["ERR_NAME_NOT_RESOLVED", "ERR_CONNECTION_REFUSED",
                                            "Navigation Timeout", "browser has been closed",
                                            "Browser closed"]):
            category = "env"
        else:
            category = "unknown"

    # 提取文件和行号
    file_path, line_no = _extract_failure_location(call)

    # 构建报告条目
    entry = {
        "test_name": item.name,
        "category": category,
        "action": getattr(locator_error, "action", "") if locator_error else "",
        "selector": getattr(locator_error, "selector", "") if locator_error else "",
        "page_url": getattr(locator_error, "page_url", "") if locator_error else "",
        "file": file_path,
        "line": line_no,
        "screenshot": screenshot_path,
        "error_message": str(exc)[:500],
    }

    # 写入 JSON 报告（追加模式）
    _append_heal_report(entry)


def _is_locator_error(exc) -> bool:
    """判断异常是否为 LocatorActionError"""
    return isinstance(exc, LocatorActionError)


def _is_env_error(exc) -> bool:
    """判断是否为环境错误"""
    msg = str(exc)
    env_keywords = [
        "ERR_NAME_NOT_RESOLVED", "ERR_CONNECTION_REFUSED",
        "ERR_CONNECTION_TIMED_OUT", "Navigation Timeout",
        "browser has been closed", "Browser closed",
        "ERR_SSL", "ERR_TUNNEL",
    ]
    return any(kw in msg for kw in env_keywords)


def _extract_failure_location(call) -> tuple:
    """从异常 traceback 中提取失败位置（文件路径+行号）"""
    exc = call.excinfo.value if call.excinfo else None
    if not exc or not exc.__traceback__:
        return "", 0

    skip_patterns = [
        "site-packages", "playwright/", "_pytest", "pluggy",
        "asyncio", "concurrent", "conftest.py", "__pycache__",
    ]

    tb = exc.__traceback__
    while tb is not None:
        frame = tb.tb_frame
        fname = frame.f_code.co_filename
        lineno = tb.tb_lineno
        if not any(skip in fname for skip in skip_patterns):
            return fname, lineno
        tb = tb.tb_next

    return "", 0


def _append_heal_report(entry: dict):
    """追加一条失败记录到 heal_report.json"""
    os.makedirs(os.path.dirname(HEAL_REPORT_PATH), exist_ok=True)

    # 读取已有报告
    report = {"timestamp": "", "failures": []}
    if os.path.exists(HEAL_REPORT_PATH):
        try:
            with open(HEAL_REPORT_PATH, "r", encoding="utf-8") as f:
                report = json.load(f)
        except Exception:
            pass

    # 追加
    import datetime
    report["timestamp"] = datetime.datetime.now().isoformat()
    report["failures"].append(entry)

    # 写回
    with open(HEAL_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 打印结构化日志
    icon = {"locator": "🔧", "assertion": "🐛", "env": "🌐"}.get(entry["category"], "❓")
    print(f"\n{icon} [HEAL-REPORT] {entry['category']} | {entry['test_name']}")
    if entry["selector"]:
        print(f"   selector={entry['selector']!r} action={entry['action']}")


# ── 自动自愈触发 ──────────────────────────────────────────────

def pytest_sessionfinish(session, exitstatus):
    """测试 session 结束后：使用回退优先级策略层处理所有失败类型

    流程：
      1. 读取 output/heal_report.json
      2. 对每个失败条目进行细粒度分类（locator/assertion/env/flow）
      3. 决策引擎选择最优修复策略（patch/replay/re-record/env_fix/skip）
      4. 按优先级执行修复，失败时自动降级到回退链
      5. 生成修复报告

    兼容：如果策略层导入失败，回退到旧的仅 locator 自愈逻辑

    防递归：策略层的 replay/retry 会启动子进程 pytest，
    子进程也会触发这个 hook，用环境变量阻止递归。
    """
    # 防递归：策略层子进程里不再触发策略层
    if os.environ.get("STRATEGY_REPAIR_RUNNING"):
        return

    if not os.path.exists(HEAL_REPORT_PATH):
        return

    try:
        with open(HEAL_REPORT_PATH, "r", encoding="utf-8") as f:
            report = json.load(f)
    except Exception:
        return

    all_failures = report.get("failures", [])
    if not all_failures:
        return

    # 尝试使用新的策略层
    try:
        from scheduler.strategy import FailureRepairOrchestrator
        project_root = os.path.dirname(__file__)
        scheduler = FailureRepairOrchestrator(project_root)
        scheduler.run(HEAL_REPORT_PATH)
    except ImportError:
        # 策略层不可用，回退到旧逻辑（仅处理 locator）
        print(f"\n⚠️ 策略层未就绪，使用旧版自愈逻辑")
        locator_failures = [e for e in all_failures if e.get("category") == "locator"]
        if locator_failures:
            _auto_heal(locator_failures)
    except Exception as e:
        print(f"\n⚠️ 策略层执行异常: {e}")
        print(f"   回退到旧版自愈逻辑")
        locator_failures = [e for e in all_failures if e.get("category") == "locator"]
        if locator_failures:
            _auto_heal(locator_failures)

    # 归档报告文件（不删除，保留供 repair 命令重跑）
    try:
        import shutil
        archive_dir = os.path.join(os.path.dirname(HEAL_REPORT_PATH), "archive")
        os.makedirs(archive_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        archive_path = os.path.join(archive_dir, f"heal_report_{ts}.json")
        shutil.move(HEAL_REPORT_PATH, archive_path)
        print(f"📦 报告已归档: {archive_path}")
    except Exception:
        pass


def _auto_heal(failures: list):
    """对定位错误调用 healer pipeline 进行自动修复"""
    import datetime

    for entry in failures:
        selector = entry.get("selector", "")
        page_url = entry.get("page_url", "")
        file_path = entry.get("file", "")
        test_name = entry.get("test_name", "")

        if not selector:
            print(f"\n  ⚠️ [{test_name}] 选择器为空，跳过")
            continue

        print(f"\n  📍 [{test_name}]")
        print(f"     选择器: {selector!r}")
        print(f"     页面:   {page_url}")

        # 调用 healer pipeline（同步桥接）
        healed = _call_healer(selector, page_url)

        if healed and healed != selector:
            # 回写源码
            success = _patch_source(file_path, selector, healed)
            if success:
                print(f"     ✅ 修复成功: {selector!r} → {healed!r}")
                # 记录修复日志
                _log_heal_result(test_name, selector, healed, file_path, success=True)
            else:
                print(f"     ⚠️ healer 找到了新选择器但源码回写失败")
                _log_heal_result(test_name, selector, healed, file_path, success=False)
        else:
            print(f"     ❌ healer 未能修复此选择器")
            _log_heal_result(test_name, selector, "", file_path, success=False)

    print(f"\n{'='*60}")
    print(f"🩹 自愈完成，可重新运行测试验证修复效果")
    print(f"{'='*60}")


def _call_healer(selector: str, page_url: str) -> str | None:
    """同步调用 healer pipeline 进行选择器修复

    Returns:
        修复后的选择器，或 None
    """
    import asyncio

    async def _heal():
        from playwright.async_api import async_playwright
        from self_healing.healer_config import get_healer_config

        config = get_healer_config()

        from playwright.async_api import async_playwright
        from playwright_healer.pipeline import HealingPipeline

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--ignore-certificate-errors"],
            )

            # 使用已有登录态
            storage_state_path = os.path.join(os.path.dirname(__file__), "login_state", "storage_state.json")
            context_args = {
                "viewport": {"width": 1366, "height": 768},
                "ignore_https_errors": True,
            }
            if os.path.exists(storage_state_path):
                context_args["storage_state"] = storage_state_path

            context = await browser.new_context(**context_args)
            page = await context.new_page()

            # 导航到目标页面
            if page_url and page_url != "about:blank":
                try:
                    await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(3000)
                except Exception as e:
                    print(f"     ⚠️ 导航失败: {e}")

            # 创建 pipeline 并调用自愈
            pipeline = HealingPipeline(page, config, test_name="auto_heal")

            try:
                await pipeline.find(selector, selector)

                # 从 session_report 获取修复后的选择器
                healed_selector = None
                for event in pipeline.session_report.events:
                    if event.selector == selector and event.healed_selector:
                        healed_selector = event.healed_selector
                        break

                return healed_selector

            except Exception as e:
                print(f"     ❌ healer pipeline 异常: {e}")
                return None
            finally:
                try:
                    await pipeline.shutdown()
                except Exception:
                    pass
                await browser.close()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # pytest 内部有事件循环 → 用线程池
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, _heal())
            return future.result(timeout=120)
    else:
        return asyncio.run(_heal())


def _patch_source(file_path: str, old_selector: str, new_selector: str) -> bool:
    """在源文件中替换失效的选择器"""
    if not file_path or not os.path.exists(file_path):
        print(f"     ⚠️ 源文件不存在: {file_path}")
        return False

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    if old_selector not in content:
        print(f"     ⚠️ 源文件中未找到选择器: {old_selector!r}")
        return False

    # 备份
    backup_path = file_path + ".bak"
    if not os.path.exists(backup_path):
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(content)

    new_content = content.replace(old_selector, new_selector)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    return True


def _log_heal_result(test_name: str, old_sel: str, new_sel: str, file_path: str, success: bool):
    """追加修复日志到 output/heal_log.json"""
    import datetime

    log_path = os.path.join(os.path.dirname(__file__), "output", "heal_log.json")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    logs = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except Exception:
            pass

    logs.append({
        "timestamp": datetime.datetime.now().isoformat(),
        "test_name": test_name,
        "old_selector": old_sel,
        "new_selector": new_sel,
        "file": file_path,
        "success": success,
    })

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)
