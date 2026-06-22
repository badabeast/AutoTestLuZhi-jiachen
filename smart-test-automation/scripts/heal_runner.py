#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
heal_runner.py — 自愈测试运行器

完整流程：
  1. 运行 pytest 测试（带 --tb=long 获取详细错误信息）
  2. 分析 pytest 输出，按规则分类错误：
     - 定位错误（LocatorError）→ 调用 healer 四级策略修复源码
     - 断言错误（AssertionError）→ 报告业务 bug，不修复
     - 环境错误（EnvError）→ 报告环境问题，不修复
  3. 对定位错误：提取选择器 + 文件路径 + 行号 → 调用 healer pipeline
  4. 自愈成功后回写源码文件
  5. 重跑测试验证修复效果

运行方式：
    python3 heal_runner.py                                          # 跑全部测试
    python3 heal_runner.py tests/test_demand_form.py::test_entry7   # 指定测试
    python3 heal_runner.py output/modules/create_demand/po/         # 指定目录
    python3 heal_runner.py --max-rounds 3                           # 最多修复轮数
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

# 确保项目根目录在 import 路径
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.env_loader import load_env

load_env()


# ============================================================
# 错误分类
# ============================================================

class ErrorCategory(Enum):
    """错误分类"""
    LOCATOR = "locator"       # 定位错误 → 需要自愈修复
    ASSERTION = "assertion"   # 断言错误 → 业务 bug，不修复
    ENVIRONMENT = "env"       # 环境错误 → 需人工介入
    UNKNOWN = "unknown"       # 未知错误 → 不修复


@dataclass
class TestFailure:
    """测试失败记录"""
    test_name: str               # 测试用例名
    error_category: ErrorCategory  # 错误分类
    error_message: str           # 完整错误信息
    file_path: str = ""          # 出错的源文件路径
    line_no: int = 0             # 出错行号
    selector: str = ""           # 失效的选择器（定位错误时）
    traceback_text: str = ""     # 完整 traceback


# ============================================================
# 错误分类器
# ============================================================

class ErrorClassifier:
    """解析 pytest 输出，分类错误"""

    # 定位错误关键词
    LOCATOR_PATTERNS = [
        r"waiting for locator\(",
        r"waiting for selector",
        r"waiting for get_by_",
        r"strict mode violation",
        r"Element is not attached",
        r"locator\.(click|fill|type|check|hover|select).*Timeout",
        r"Locator\.wait_for.*Timeout",
        r"Timeout.*waiting for.*visible",
        r"Timeout.*waiting for.*attached",
        r"no element matches",
        r"Could not find element",
    ]

    # 环境错误关键词
    ENV_PATTERNS = [
        r"net::ERR_NAME_NOT_RESOLVED",
        r"net::ERR_CONNECTION_REFUSED",
        r"net::ERR_CONNECTION_TIMED_OUT",
        r"Navigation Timeout",
        r"browser closed",
        r"storage_state.*not found",
        r"ERR_SSL",
        r"ERR_TUNNEL_CONNECTION_FAILED",
    ]

    # 断言错误关键词
    ASSERTION_PATTERNS = [
        r"AssertionError",
        r"assert ",
        r"Expected.*but received",
        r"expect\(.*\)\.",
    ]

    @classmethod
    def classify(cls, test_name: str, tb_text: str) -> TestFailure:
        """分类一个测试失败

        Args:
            test_name: 测试用例名
            tb_text: traceback 文本

        Returns:
            TestFailure 记录
        """
        failure = TestFailure(
            test_name=test_name,
            error_category=ErrorCategory.UNKNOWN,
            error_message=tb_text[:2000],
            traceback_text=tb_text,
        )

        # 先检查环境错误（优先级最高，避免误判为定位错误）
        for pattern in cls.ENV_PATTERNS:
            if re.search(pattern, tb_text):
                failure.error_category = ErrorCategory.ENVIRONMENT
                return failure

        # 检查断言错误
        for pattern in cls.ASSERTION_PATTERNS:
            if re.search(pattern, tb_text):
                failure.error_category = ErrorCategory.ASSERTION
                return failure

        # 检查定位错误
        for pattern in cls.LOCATOR_PATTERNS:
            if re.search(pattern, tb_text):
                failure.error_category = ErrorCategory.LOCATOR
                # 尝试提取文件路径和行号
                cls._extract_location(failure, tb_text)
                # 尝试提取选择器
                cls._extract_selector(failure, tb_text)
                return failure

        # 如果是 Playwright TimeoutError 但不匹配上面的模式
        if "TimeoutError" in tb_text and "locator" in tb_text.lower():
            failure.error_category = ErrorCategory.LOCATOR
            cls._extract_location(failure, tb_text)
            cls._extract_selector(failure, tb_text)
            return failure

        return failure

    @staticmethod
    def _extract_location(failure: TestFailure, tb_text: str):
        """从 traceback 提取出错文件路径和行号"""
        # 匹配格式: File "xxx.py", line N
        # 跳过 playwright 内部、site-packages、conftest 等
        skip_patterns = [
            "site-packages", "playwright/", "_pytest", "pluggy",
            "asyncio", "concurrent", "conftest.py", "__pycache__",
        ]
        for line in tb_text.split("\n"):
            m = re.match(r'\s*File "(.+\.py)", line (\d+)', line)
            if m:
                fpath = m.group(1)
                lineno = int(m.group(2))
                if not any(skip in fpath for skip in skip_patterns):
                    failure.file_path = fpath
                    failure.line_no = lineno
                    return

    @staticmethod
    def _extract_selector(failure: TestFailure, tb_text: str):
        """从错误信息中提取失效的选择器"""
        # 模式1: locator("xxx") / locator('.xxx')
        m = re.search(r'locator\(["\'](.+?)["\']\)', tb_text)
        if m:
            failure.selector = m.group(1)
            return
        # 模式2: get_by_text("xxx") / get_by_role("xxx", name="yyy")
        m = re.search(r'get_by_(text|role|label|placeholder)\(["\'](.+?)["\']', tb_text)
        if m:
            failure.selector = f"get_by_{m.group(1)}({m.group(2)})"
            return
        # 模式3: waiting for selector "xxx"
        m = re.search(r'waiting for selector ["\'](.+?)["\']', tb_text)
        if m:
            failure.selector = m.group(1)
            return
        # 模式4: CSS 选择器在 nth-child / div.xxx 等
        m = re.search(r'(?:div|span|input|button|table|a)\.[\w\-]+[\w\-. >:*\(\)]*', tb_text)
        if m:
            failure.selector = m.group(0).split("\n")[0].strip()


# ============================================================
# pytest 输出解析器
# ============================================================

def parse_pytest_failures(output: str) -> List[TestFailure]:
    """解析 pytest --tb=long 输出，提取失败用例列表

    pytest 输出格式:
        ==== FAILURES ====
        ____ test_name ____
        (traceback...)
        ==== short test summary ====
        FAILED test_file.py::test_name - ErrorType: message
    """
    failures = []

    # 分割出每个 FAILURES 段
    # 模式: _____ test_name _____
    failure_sections = re.split(r'_{5,}\s+', output)

    for section in failure_sections:
        # 匹配测试名 (在分割后的第一行)
        lines = section.strip().split("\n")
        if not lines:
            continue

        # 第一行可能是 test_name 后面跟着 ____
        first_line = lines[0].strip().rstrip("_").strip()
        if not first_line or "test_" not in first_line:
            continue

        test_name = first_line

        # 从 short test summary 中提取更准确的测试名
        # FAILED xxx.py::test_name - Error
        summary_match = re.search(
            r'FAILED\s+([\w./\\]+::[\w\[\]]+)',
            output
        )

        # 整个 section 就是 traceback
        tb_text = section

        failure = ErrorClassifier.classify(test_name, tb_text)

        # 如果有 summary 信息，覆盖 test_name 为完整路径
        if summary_match:
            failure.test_name = summary_match.group(1)

        failures.append(failure)

    return failures


# ============================================================
# healer 同步桥接
# ============================================================

def run_healer_sync(
    page_url: str,
    selector: str,
    description: str = "",
    screenshot_path: str = "",
) -> Optional[str]:
    """同步调用 healer pipeline 进行自愈

    通过 asyncio 桥接调用 HealingPipeline.find()。

    Args:
        page_url: 页面 URL（用于 healer 上下文）
        selector: 失效的选择器
        description: 选择器描述
        screenshot_path: 截图路径（用于 AI Visual 阶段）

    Returns:
        自愈成功返回修复后的选择器，失败返回 None
    """
    # playwright-healer 已移除，使用本地 healer_config 替代
    try:
        from self_healing.healer_config import HealerConfig, get_healer_config
        config = get_healer_config(strategy="SMART", auto_patch_source=True, patch_source_backup=True)
    except ImportError:
        print("❌ 需要 healer_config 模块")
        return None
    # get_healer_config 已在上方调用，直接使用 config 对象


    async def _heal():
        from playwright.async_api import async_playwright
        # playwright-healer 已移除，使用本地五层引擎
        from self_healing.pipeline import HealingPipeline

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--ignore-certificate-errors"],
            )

            # 使用已有登录态
            storage_state_path = str(PROJECT_ROOT / "login_state" / "storage_state.json")
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
                await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)

            # 创建 pipeline 并调用自愈
            pipeline = HealingPipeline(page, config, test_name="heal_runner")

            try:
                healed_locator = await pipeline.find(selector, description or selector)
                healed_selector = ""
                # 从 session_report 获取修复后的选择器
                for event in pipeline.session_report.events:
                    if event.selector == selector and event.healed_selector:
                        healed_selector = event.healed_selector
                        break

                await pipeline.shutdown()
                await browser.close()
                return healed_selector

            except Exception as e:
                print(f"   ❌ healer pipeline 失败: {e}")
                try:
                    await pipeline.shutdown()
                except Exception:
                    pass
                await browser.close()
                return None

    try:
        # 尝试在已有事件循环中运行（pytest 环境）
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # 已有事件循环运行中 → 用线程池
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, _heal())
                return future.result(timeout=120)
        else:
            return asyncio.run(_heal())

    except Exception as e:
        print(f"   ❌ healer 同步桥接异常: {e}")
        traceback.print_exc()
        return None


# ============================================================
# 源码修复器
# ============================================================

def patch_source_file(file_path: str, old_selector: str, new_selector: str) -> bool:
    """在源文件中替换失效的选择器

    Args:
        file_path: 源文件路径
        old_selector: 原选择器
        new_selector: 修复后的选择器

    Returns:
        是否替换成功
    """
    if not file_path or not os.path.exists(file_path):
        print(f"   ⚠️ 源文件不存在: {file_path}")
        return False

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    if old_selector not in content:
        print(f"   ⚠️ 源文件中未找到选择器: {old_selector}")
        return False

    # 备份
    backup_path = file_path + ".bak"
    if not os.path.exists(backup_path):
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(content)

    # 替换
    new_content = content.replace(old_selector, new_selector)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"   ✅ 源码已修复: {old_selector!r} → {new_selector!r}")
    print(f"   📁 文件: {file_path}")
    return True


# ============================================================
# 主流程
# ============================================================

@dataclass
class HealResult:
    """一轮自愈的结果"""
    round_no: int
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    locator_errors: int = 0
    assertion_errors: int = 0
    env_errors: int = 0
    healed_count: int = 0
    healed_details: List[dict] = field(default_factory=list)
    failures: List[TestFailure] = field(default_factory=list)


def run_pytest(test_target: str, extra_args: List[str] = None) -> Tuple[int, str]:
    """运行 pytest 并返回 (退出码, 完整输出)

    Args:
        test_target: 测试目标（文件/目录/用例）
        extra_args: 额外 pytest 参数

    Returns:
        (exit_code, stdout+stderr output)
    """
    cmd = [
        sys.executable, "-m", "pytest",
        test_target,
        "--tb=long",
        "-v",
        "--no-header",
    ]
    if extra_args:
        cmd.extend(extra_args)

    print(f"\n{'='*60}")
    print(f"🚀 运行: {' '.join(cmd)}")
    print(f"{'='*60}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )

    output = result.stdout + "\n" + result.stderr
    return result.returncode, output


def analyze_failures(output: str) -> List[TestFailure]:
    """分析 pytest 输出，返回分类后的失败列表"""
    failures = parse_pytest_failures(output)

    print(f"\n{'='*60}")
    print(f"📊 错误分析结果")
    print(f"{'='*60}")

    for f in failures:
        icon = {
            ErrorCategory.LOCATOR: "🔧",
            ErrorCategory.ASSERTION: "🐛",
            ErrorCategory.ENVIRONMENT: "🌐",
            ErrorCategory.UNKNOWN: "❓",
        }.get(f.error_category, "❓")

        print(f"\n  {icon} [{f.error_category.value:10s}] {f.test_name}")
        if f.error_category == ErrorCategory.LOCATOR:
            print(f"     选择器: {f.selector!r}")
            print(f"     位置:   {f.file_path}:{f.line_no}")

    return failures


def heal_locator_errors(
    failures: List[TestFailure],
    test_target: str,
) -> int:
    """对定位错误调用 healer 修复

    Returns:
        成功修复的数量
    """
    locator_failures = [f for f in failures if f.error_category == ErrorCategory.LOCATOR]

    if not locator_failures:
        print("\n  没有定位错误需要修复")
        return 0

    print(f"\n{'='*60}")
    print(f"🩹 开始自愈修复 ({len(locator_failures)} 个定位错误)")
    print(f"{'='*60}")

    healed = 0
    for f in locator_failures:
        print(f"\n  📍 修复: {f.test_name}")
        print(f"     选择器: {f.selector!r}")
        print(f"     文件:   {f.file_path}:{f.line_no}")

        if not f.selector:
            print(f"     ⚠️ 无法提取选择器，跳过")
            continue

        # 从 traceback 中提取页面 URL（healer 需要访问页面）
        page_url = _extract_page_url(f.traceback_text)

        # 调用 healer
        healed_selector = run_healer_sync(
            page_url=page_url,
            selector=f.selector,
            description=f.selector,
        )

        if healed_selector and healed_selector != f.selector:
            # 修复源码
            success = patch_source_file(f.file_path, f.selector, healed_selector)
            if success:
                healed += 1
        else:
            print(f"     ❌ healer 未能修复此选择器")

    print(f"\n  📋 修复完成: {healed}/{len(locator_failures)} 个成功")
    return healed


def _extract_page_url(tb_text: str) -> str:
    """从 traceback 中提取页面 URL"""
    # 匹配 Page url='xxx'
    m = re.search(r"Page url='([^']+)'", tb_text)
    if m:
        return m.group(1)
    # 匹配 page.goto("xxx")
    m = re.search(r'goto\(["\']([^"\']+)["\']\)', tb_text)
    if m:
        return m.group(1)
    # 从环境变量取默认 URL
    return os.environ.get("WEB_DEMAND_URL", "about:blank")


def print_summary(results: List[HealResult]):
    """打印最终汇总"""
    print(f"\n{'='*60}")
    print(f"📋 自愈运行汇总")
    print(f"{'='*60}")

    for r in results:
        print(f"\n  第 {r.round_no} 轮:")
        print(f"    通过: {r.passed}  失败: {r.failed}")
        print(f"    定位错误: {r.locator_errors}  断言错误: {r.assertion_errors}  环境错误: {r.env_errors}")
        print(f"    修复成功: {r.healed_count}")

    last = results[-1]
    if last.failed == 0:
        print(f"\n  ✅ 全部测试通过!")
    elif last.locator_errors == 0:
        print(f"\n  🐛 剩余失败均为断言/环境错误，需人工排查")
    else:
        print(f"\n  ⚠️ 仍有 {last.locator_errors} 个定位错误未修复")


def main():
    """主入口"""
    import argparse

    parser = argparse.ArgumentParser(description="自愈测试运行器")
    parser.add_argument("test_target", nargs="?", default="", help="测试目标")
    parser.add_argument("--max-rounds", type=int, default=3, help="最大修复轮数")
    parser.add_argument("--dry-run", action="store_true", help="只分析不修复")
    args = parser.parse_args()

    test_target = args.test_target
    max_rounds = args.max_rounds

    if not test_target:
        # 默认跑 entry7 和 entry9
        test_target = "output/modules/create_demand/po/test_create_demand.py"

    print("=" * 60)
    print("🩹 自愈测试运行器")
    print(f"   目标: {test_target}")
    print(f"   最大轮数: {max_rounds}")
    print("=" * 60)

    all_results: List[HealResult] = []

    for round_no in range(1, max_rounds + 1):
        print(f"\n{'#'*60}")
        print(f"  第 {round_no} 轮")
        print(f"{'#'*60}")

        # 清除上一轮的 JSON 报告
        heal_report_path = str(PROJECT_ROOT / "output" / "heal_report.json")
        if os.path.exists(heal_report_path):
            os.remove(heal_report_path)

        # 1. 运行 pytest（conftest hook 会自动写 heal_report.json）
        exit_code, output = run_pytest(test_target)

        # 解析通过/失败数
        passed = output.count("PASSED")
        failed = output.count("FAILED")

        result = HealResult(
            round_no=round_no,
            total_tests=passed + failed,
            passed=passed,
            failed=failed,
        )

        # 全部通过
        if exit_code == 0:
            print(f"\n  ✅ 全部测试通过! (通过: {passed})")
            all_results.append(result)
            break

        # 2. 从 JSON 报告读取结构化失败信息（由 conftest hook 写入）
        failures = read_heal_report(heal_report_path)

        # 如果 JSON 报告为空，回退到解析 pytest 输出
        if not failures:
            print("  ⚠️ JSON 报告为空，回退到 pytest 输出解析")
            failures = analyze_failures(output)

        result.failures = failures
        result.locator_errors = sum(1 for f in failures if f.error_category == ErrorCategory.LOCATOR)
        result.assertion_errors = sum(1 for f in failures if f.error_category == ErrorCategory.ASSERTION)
        result.env_errors = sum(1 for f in failures if f.error_category in (ErrorCategory.ENVIRONMENT, ErrorCategory.UNKNOWN))

        # 打印分析结果
        print(f"\n{'='*60}")
        print(f"📊 错误分析结果")
        print(f"{'='*60}")
        for f in failures:
            icon = {
                ErrorCategory.LOCATOR: "🔧",
                ErrorCategory.ASSERTION: "🐛",
                ErrorCategory.ENVIRONMENT: "🌐",
                ErrorCategory.UNKNOWN: "❓",
            }.get(f.error_category, "❓")
            print(f"  {icon} [{f.error_category.value:10s}] {f.test_name}")
            if f.error_category == ErrorCategory.LOCATOR:
                print(f"     选择器: {f.selector!r}")
                print(f"     位置:   {f.file_path}:{f.line_no}")

        # 3. dry-run 模式到此为止
        if args.dry_run:
            all_results.append(result)
            break

        # 4. 没有定位错误，不需要修复
        if result.locator_errors == 0:
            print(f"\n  没有定位错误，无需修复")
            all_results.append(result)
            break

        # 5. 调用 healer 修复定位错误
        healed = heal_locator_errors(failures, test_target)
        result.healed_count = healed

        all_results.append(result)

        # 6. 如果没有修复成功，不再继续
        if healed == 0:
            print(f"\n  ⚠️ 本轮无修复成功，停止")
            break

    # 打印汇总
    print_summary(all_results)

    # 保存修复日志
    log_path = str(PROJECT_ROOT / "output" / "heal_log.json")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(
            [{"round": r.round_no, "passed": r.passed, "failed": r.failed,
              "healed": r.healed_count} for r in all_results],
            f, ensure_ascii=False, indent=2
        )
    print(f"\n📁 修复日志: {log_path}")


def read_heal_report(report_path: str) -> List[TestFailure]:
    """从 conftest 写入的 heal_report.json 读取结构化失败信息"""
    if not os.path.exists(report_path):
        return []

    try:
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
    except Exception:
        return []

    failures = []
    for entry in report.get("failures", []):
        category_map = {
            "locator": ErrorCategory.LOCATOR,
            "assertion": ErrorCategory.ASSERTION,
            "env": ErrorCategory.ENVIRONMENT,
            "unknown": ErrorCategory.UNKNOWN,
        }
        cat = category_map.get(entry.get("category", ""), ErrorCategory.UNKNOWN)
        failures.append(TestFailure(
            test_name=entry.get("test_name", ""),
            error_category=cat,
            error_message=entry.get("error_message", ""),
            file_path=entry.get("file", ""),
            line_no=entry.get("line", 0),
            selector=entry.get("selector", ""),
            traceback_text="",
        ))

    return failures


if __name__ == "__main__":
    main()
