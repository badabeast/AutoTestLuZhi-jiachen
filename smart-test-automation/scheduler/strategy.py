#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回退优先级策略层 — 失败修复决策引擎

核心职责:
  1. 对测试失败进行穷举分类（locator / assertion / env / flow）
  2. 根据分类 + 上下文信息计算最优修复策略
  3. 执行修复动作并验证结果
  4. 提供回退链：策略1失败 → 自动降级到策略2 → ...

修复策略（按成本从低到高）:
  - PATCH_SCRIPT   : 直接改脚本（选择器修复、断言逻辑修复）
  - REPLAY_VERIFY  : 回放复现问题（确认是否可复现、收集更多诊断信息）
  - RE_RECORD      : 重新录制（流程变化、页面结构大改）
  - ENV_FIX        : 环境修复（登录态刷新、网络重试）
  - SKIP           : 跳过（不可修复或超出范围）

用法::

    engine = StrategyDecisionEngine()
    decision = engine.decide(failure_entry)
    # decision.strategy = RepairStrategy.PATCH_SCRIPT
    # decision.score = 0.85
    # decision.reasoning = "选择器失效，healer 可直接修复"

    executor = RepairExecutor()
    result = executor.execute(decision)
"""

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable

logger = logging.getLogger(__name__)


class FailureCategory(str, Enum):
    LOCATOR_TIMEOUT = "locator_timeout"        # 选择器超时（元素找不到）
    LOCATOR_STRICT = "locator_strict"          # strict mode violation（多个匹配）
    LOCATOR_DETACHED = "locator_detached"      # 元素已脱离 DOM
    LOCATOR_HIDDEN = "locator_hidden"          # 元素存在但不可见
    ASSERTION_VALUE = "assertion_value"        # 断言值不匹配
    ASSERTION_EXISTENCE = "assertion_existence" # 断言元素/数据不存在
    ASSERTION_LOGIC = "assertion_logic"        # 断言逻辑错误（脚本写错了）
    ENV_NETWORK = "env_network"                # 网络问题（DNS/连接超时）
    ENV_AUTH = "env_auth"                      # 登录态失效
    ENV_BROWSER = "env_browser"                # 浏览器崩溃/无响应
    FLOW_CHANGED = "flow_changed"              # 页面流程变化（新增步骤/顺序变化）
    FLOW_REMOVED = "flow_removed"              # 目标页面/功能已下线
    UNKNOWN = "unknown"                        # 无法分类


class RepairStrategy(str, Enum):
    PATCH_SCRIPT = "patch_script"         # 直接改脚本
    REPLAY_VERIFY = "replay_verify"       # 回放复现
    RE_RECORD = "re_record"               # 重新录制
    ENV_FIX = "env_fix"                   # 环境修复
    SKIP = "skip"                         # 跳过（不可修复）


class StrategyPriority(int, Enum):
    P0_IMMEDIATE = 0    # 立即执行（成功率高、成本低）
    P1_RETRY = 1        # 重试（可能成功）
    P2_FALLBACK = 2     # 回退方案（成本较高）
    P3_MANUAL = 3       # 需要人工介入



@dataclass
class FailureEntry:
    test_name: str
    category: str
    sub_category: FailureCategory = FailureCategory.UNKNOWN
    action: str = ""
    selector: str = ""
    page_url: str = ""
    file: str = ""
    line: int = 0
    screenshot: str = ""
    error_message: str = ""
    retry_count: int = 0               # 已重试次数
    timestamp: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "FailureEntry":
        return cls(
            test_name=d.get("test_name", ""),
            category=d.get("category", "unknown"),
            action=d.get("action", ""),
            selector=d.get("selector", ""),
            page_url=d.get("page_url", ""),
            file=d.get("file", ""),
            line=d.get("line", 0),
            screenshot=d.get("screenshot", ""),
            error_message=d.get("error_message", ""),
            retry_count=d.get("retry_count", 0),
            timestamp=d.get("timestamp", ""),
        )


@dataclass
class RepairDecision:
    strategy: RepairStrategy
    priority: StrategyPriority
    score: float                         # 0.0 ~ 1.0，评估分数
    reasoning: str                       # 决策理由
    fallback_chain: List[RepairStrategy] = field(default_factory=list)  # 回退链
    params: Dict[str, Any] = field(default_factory=dict)  # 策略参数

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "priority": self.priority.name,
            "score": self.score,
            "reasoning": self.reasoning,
            "fallback_chain": [s.value for s in self.fallback_chain],
            "params": self.params,
        }


@dataclass
class RepairResult:
    # 修复结果
    strategy: RepairStrategy
    success: bool
    old_value: str = ""       # 修复前的值
    new_value: str = ""       # 修复后的值
    file_patched: str = ""    # 修改的文件
    message: str = ""
    duration_ms: int = 0
    verification_passed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "success": self.success,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "file_patched": self.file_patched,
            "message": self.message,
            "duration_ms": self.duration_ms,
            "verification_passed": self.verification_passed,
        }



class FailureClassifier:

    # 先匹配到的生效
    _PATTERNS: List[tuple] = [
        ("strict mode violation", FailureCategory.LOCATOR_STRICT),
        ("matches multiple", FailureCategory.LOCATOR_STRICT),
        ("strict mode", FailureCategory.LOCATOR_STRICT),       # 兜底
        ("element is detached", FailureCategory.LOCATOR_DETACHED),
        ("not attached to the DOM", FailureCategory.LOCATOR_DETACHED),  # 精确匹配
        ("element is not visible", FailureCategory.LOCATOR_HIDDEN),
        ("waiting for locator", FailureCategory.LOCATOR_TIMEOUT),
        ("waiting for selector", FailureCategory.LOCATOR_TIMEOUT),
        ("Timeout waiting for locator", FailureCategory.LOCATOR_TIMEOUT),
        ("locator.*timeout", FailureCategory.LOCATOR_TIMEOUT),

        # assertion
        ("expected.*but got", FailureCategory.ASSERTION_VALUE),
        ("to_have_text", FailureCategory.ASSERTION_VALUE),
        ("to_contain_text", FailureCategory.ASSERTION_VALUE),
        ("to_have_value", FailureCategory.ASSERTION_VALUE),
        ("to_be_visible", FailureCategory.ASSERTION_EXISTENCE),
        ("AssertionError", FailureCategory.ASSERTION_VALUE),   # 兜底

        # env
        ("ERR_NAME_NOT_RESOLVED", FailureCategory.ENV_NETWORK),
        ("ERR_CONNECTION_REFUSED", FailureCategory.ENV_NETWORK),
        ("ERR_CONNECTION_TIMED_OUT", FailureCategory.ENV_NETWORK),
        ("Navigation Timeout", FailureCategory.ENV_NETWORK),
        ("ERR_SSL", FailureCategory.ENV_NETWORK),
        ("ERR_TUNNEL", FailureCategory.ENV_NETWORK),
        ("browser has been closed", FailureCategory.ENV_BROWSER),   # 精确
        ("Browser closed", FailureCategory.ENV_BROWSER),
        ("Target closed.*Browser", FailureCategory.ENV_BROWSER),    # 需同时包含 Browser
        ("session expired", FailureCategory.ENV_AUTH),
        ("unauthorized", FailureCategory.ENV_AUTH),
        ("HTTP 401", FailureCategory.ENV_AUTH),              # 精确匹配 HTTP 状态码
        ("status.*401", FailureCategory.ENV_AUTH),

        # flow
        ("page.goto.*failed.*404", FailureCategory.FLOW_REMOVED),   # goto + 404
        ("page.goto.*failed", FailureCategory.FLOW_REMOVED),
        ("HTTP 404", FailureCategory.FLOW_REMOVED),          # 精确匹配 HTTP 状态码
        ("status.*404", FailureCategory.FLOW_REMOVED),

        # 宽泛兜底（放在最后，避免误匹配前面的精确规则）
        ("Target closed", FailureCategory.LOCATOR_DETACHED),  # 无 Browser 关键词 → 元素问题
        ("not visible", FailureCategory.LOCATOR_HIDDEN),      # 兜底
        ("not attached", FailureCategory.LOCATOR_DETACHED),   # 兜底
        ("401", FailureCategory.ENV_AUTH),                    # 兜底
        ("login.*failed", FailureCategory.ENV_AUTH),          # 仅 login+failed 才算登录问题
        ("login.*error", FailureCategory.ENV_AUTH),           # 仅 login+error 才算登录问题
        ("not found", FailureCategory.FLOW_REMOVED),          # 兜底
    ]

    @classmethod
    def classify(cls, entry: FailureEntry) -> FailureCategory:
        error_msg = entry.error_message or ""
        original_cat = entry.category or ""

        # 1. 先按 conftest 的粗分类缩小范围
        if original_cat == "locator":
            return cls._classify_locator(error_msg)
        elif original_cat == "assertion":
            return cls._classify_assertion(error_msg)
        elif original_cat == "env":
            return cls._classify_env(error_msg)
        else:
            #  全文匹配
            return cls._match_patterns(error_msg)

    @classmethod
    def _classify_locator(cls, error_msg: str) -> FailureCategory:
        for pattern, cat in cls._PATTERNS:
            if cat.value.startswith("locator") and _match(pattern, error_msg):
                return cat
        return FailureCategory.LOCATOR_TIMEOUT  # locator 默认归为超时

    @classmethod
    def _classify_assertion(cls, error_msg: str) -> FailureCategory:
        for pattern, cat in cls._PATTERNS:
            if cat.value.startswith("assertion") and _match(pattern, error_msg):
                return cat
        return FailureCategory.ASSERTION_VALUE

    @classmethod
    def _classify_env(cls, error_msg: str) -> FailureCategory:
        for pattern, cat in cls._PATTERNS:
            if cat.value.startswith("env") and _match(pattern, error_msg):
                return cat
        return FailureCategory.ENV_NETWORK

    @classmethod
    def _match_patterns(cls, error_msg: str) -> FailureCategory:
        for pattern, cat in cls._PATTERNS:
            if _match(pattern, error_msg):
                return cat
        return FailureCategory.UNKNOWN


def _match(pattern: str, text: str) -> bool:
    import re
    try:
        return bool(re.search(pattern, text, re.IGNORECASE))
    except re.error:
        return pattern.lower() in text.lower()


# 选择器问题→healer修→回放确认→重录；断言→先回放确认复现再判断；网络→重试3次；登录态→跑auto_login；流程变化→跳过等人工
_DECISION_RULES: Dict[FailureCategory, List[Dict]] = {
    FailureCategory.LOCATOR_TIMEOUT: [
        {"max_retry": 0, "strategy": RepairStrategy.PATCH_SCRIPT,
         "priority": StrategyPriority.P0_IMMEDIATE, "score": 0.80,
         "reasoning": "选择器找不到元素，先让 healer 自动修",
         "fallback": [RepairStrategy.REPLAY_VERIFY, RepairStrategy.RE_RECORD]},
        {"max_retry": 2, "strategy": RepairStrategy.REPLAY_VERIFY,
         "priority": StrategyPriority.P1_RETRY, "score": 0.50,
         "reasoning": "healer 修不了，回放看看能不能复现",
         "fallback": [RepairStrategy.RE_RECORD]},
    ],
    FailureCategory.LOCATOR_STRICT: [
        {"max_retry": 0, "strategy": RepairStrategy.PATCH_SCRIPT,
         "priority": StrategyPriority.P0_IMMEDIATE, "score": 0.85,
         "reasoning": "选择器匹配到多个元素，收窄选择器或加 .first",
         "fallback": [RepairStrategy.RE_RECORD]},
    ],
    FailureCategory.LOCATOR_DETACHED: [
        {"max_retry": 0, "strategy": RepairStrategy.PATCH_SCRIPT,
         "priority": StrategyPriority.P1_RETRY, "score": 0.70,
         "reasoning": "元素已经从 DOM 树上摘掉了，可能页面还没加载完",
         "fallback": [RepairStrategy.REPLAY_VERIFY, RepairStrategy.RE_RECORD]},
    ],
    FailureCategory.LOCATOR_HIDDEN: [
        {"max_retry": 0, "strategy": RepairStrategy.PATCH_SCRIPT,
         "priority": StrategyPriority.P1_RETRY, "score": 0.75,
         "reasoning": "元素在 DOM 里但是看不见，可能要滚动或等动画",
         "fallback": [RepairStrategy.REPLAY_VERIFY]},
    ],

    # 先回放确认能复现，再判断是接口问题还是脚本问题
    FailureCategory.ASSERTION_VALUE: [
        {"max_retry": 0, "strategy": RepairStrategy.REPLAY_VERIFY,
         "priority": StrategyPriority.P1_RETRY, "score": 0.60,
         "reasoning": "断言值不匹配，先回放确认能复现，再判断是接口问题还是脚本问题",
         "fallback": [RepairStrategy.PATCH_SCRIPT, RepairStrategy.RE_RECORD]},
    ],
    FailureCategory.ASSERTION_EXISTENCE: [
        {"max_retry": 0, "strategy": RepairStrategy.REPLAY_VERIFY,
         "priority": StrategyPriority.P1_RETRY, "score": 0.60,
         "reasoning": "断言目标不存在，先回放确认：是页面变了还是数据没了",
         "fallback": [RepairStrategy.PATCH_SCRIPT, RepairStrategy.RE_RECORD]},
    ],
    FailureCategory.ASSERTION_LOGIC: [
        {"max_retry": 0, "strategy": RepairStrategy.PATCH_SCRIPT,
         "priority": StrategyPriority.P2_FALLBACK, "score": 0.50,
         "reasoning": "断言逻辑本身写错了，需要改脚本",
         "fallback": [RepairStrategy.RE_RECORD]},
    ],

    # ── 环境问题 ──
    FailureCategory.ENV_NETWORK: [
        {"max_retry": 0, "strategy": RepairStrategy.ENV_FIX,
         "priority": StrategyPriority.P0_IMMEDIATE, "score": 0.70,
         "reasoning": "网络抖了，重试最多 3 次，都不行就跳过",
         "fallback": [RepairStrategy.SKIP]},
    ],
    FailureCategory.ENV_AUTH: [
        {"max_retry": 0, "strategy": RepairStrategy.ENV_FIX,
         "priority": StrategyPriority.P0_IMMEDIATE, "score": 0.85,
         "reasoning": "登录态过期了，跑一下 login/auto_login.py 自动刷新",
         "fallback": [RepairStrategy.SKIP]},
    ],
    FailureCategory.ENV_BROWSER: [
        {"max_retry": 0, "strategy": RepairStrategy.ENV_FIX,
         "priority": StrategyPriority.P1_RETRY, "score": 0.60,
         "reasoning": "浏览器崩了或卡死，下次跑会自动重启浏览器",
         "fallback": [RepairStrategy.SKIP]},
    ],

    # 流程变化
    FailureCategory.FLOW_CHANGED: [
        {"max_retry": 0, "strategy": RepairStrategy.SKIP,
         "priority": StrategyPriority.P3_MANUAL, "score": 0.90,
         "reasoning": "页面流程变了，需要人工确认是需求变更还是 bug",
         "fallback": []},
    ],
    FailureCategory.FLOW_REMOVED: [
        {"max_retry": 0, "strategy": RepairStrategy.SKIP,
         "priority": StrategyPriority.P3_MANUAL, "score": 0.90,
         "reasoning": "页面或功能已经下线了，等人工确认要不要删用例",
         "fallback": []},
    ],


    FailureCategory.UNKNOWN: [
        {"max_retry": 0, "strategy": RepairStrategy.REPLAY_VERIFY,
         "priority": StrategyPriority.P1_RETRY, "score": 0.40,
         "reasoning": "分不清是什么问题，先回放看看能不能复现",
         "fallback": [RepairStrategy.PATCH_SCRIPT, RepairStrategy.RE_RECORD]},
    ],
}


class StrategyDecisionEngine:
    """策略决策引擎 — 根据失败分类 + 上下文信息选择最优修复策略"""

    def __init__(self, custom_rules: Optional[Dict] = None):
        self.rules = custom_rules or _DECISION_RULES
        self.classifier = FailureClassifier()
        self.decision_history: List[Dict] = []

    def decide(self, entry: FailureEntry) -> RepairDecision:
        sub_cat = self.classifier.classify(entry)
        entry.sub_category = sub_cat

        rules = self.rules.get(sub_cat, self.rules[FailureCategory.UNKNOWN])

        selected = rules[0]  # 默认第一条
        for rule in rules:
            if entry.retry_count <= rule["max_retry"]:
                selected = rule
                break
        else:
            # 所有规则都超过重试次数，取最后一条
            selected = rules[-1]

        decision = RepairDecision(
            strategy=selected["strategy"],
            priority=selected["priority"],
            score=selected["score"],
            reasoning=selected["reasoning"],
            fallback_chain=selected.get("fallback", []),
            params=self._build_params(entry, selected["strategy"]),
        )

        self.decision_history.append({
            "test_name": entry.test_name,
            "sub_category": sub_cat.value,
            "strategy": decision.strategy.value,
            "score": decision.score,
            "retry_count": entry.retry_count,
        })

        logger.info("决策: %s → %s (评估分数=%.2f)",
                     entry.test_name, decision.strategy.value, decision.score)

        return decision

    def decide_batch(self, entries: List[FailureEntry]) -> List[tuple]:
        pairs = []
        for entry in entries:
            decision = self.decide(entry)
            pairs.append((entry, decision))

        # 按优先级排序（P0 先执行），但 entry 和 decision 始终绑定
        pairs.sort(key=lambda pair: pair[1].priority.value)
        return pairs

    def _build_params(self, entry: FailureEntry, strategy: RepairStrategy) -> Dict[str, Any]:
        return _build_strategy_params(entry, strategy)

    def get_decision_summary(self) -> Dict[str, Any]:
        if not self.decision_history:
            return {"total": 0}

        strategy_counts = {}
        for d in self.decision_history:
            s = d["strategy"]
            strategy_counts[s] = strategy_counts.get(s, 0) + 1

        return {
            "total": len(self.decision_history),
            "by_strategy": strategy_counts,
            "decisions": self.decision_history,
        }


def _extract_module_name(entry: FailureEntry) -> str:
    # 从失败记录中推断模块名
    if entry.file:
        parts = Path(entry.file).parts
        for i, part in enumerate(parts):
            if part == "modules" and i + 1 < len(parts):
                return parts[i + 1]
    # 从测试名推断: test_xxx → xxx
    if entry.test_name:
        return entry.test_name.replace("test_", "")
    return "unknown"


def _build_strategy_params(entry: FailureEntry, strategy: RepairStrategy) -> Dict[str, Any]:
    """根据失败信息构建策略参数（供 StrategyDecisionEngine 和 RepairExecutor 共用）"""
    params: Dict[str, Any] = {}

    if strategy == RepairStrategy.PATCH_SCRIPT:
        params["selector"] = entry.selector
        params["page_url"] = entry.page_url
        params["file"] = entry.file
        params["line"] = entry.line
        params["action"] = entry.action
        params["error_message"] = entry.error_message
        if entry.sub_category.value.startswith("locator"):
            params["patch_type"] = "healer"
        elif entry.sub_category.value.startswith("assertion"):
            params["patch_type"] = "ai_analysis"
        else:
            params["patch_type"] = "manual"

    elif strategy == RepairStrategy.REPLAY_VERIFY:
        params["script_path"] = entry.file
        params["headless"] = True
        params["collect_trace"] = True

    elif strategy == RepairStrategy.RE_RECORD:
        params["module_name"] = _extract_module_name(entry)
        params["page_url"] = entry.page_url

    elif strategy == RepairStrategy.ENV_FIX:
        if entry.sub_category == FailureCategory.ENV_AUTH:
            params["fix_type"] = "refresh_login"
            params["storage_state"] = "login_state/storage_state.json"
        elif entry.sub_category == FailureCategory.ENV_NETWORK:
            params["fix_type"] = "retry_with_backoff"
            params["max_retries"] = 3
        elif entry.sub_category == FailureCategory.ENV_BROWSER:
            params["fix_type"] = "restart_browser"

    return params


# 修复执行器

class RepairExecutor:
    """修复执行器 — 根据决策执行修复动作"""

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self.results: List[RepairResult] = []

    def execute(self, decision: RepairDecision, entry: FailureEntry) -> RepairResult:
        start = time.time()
        strategy = decision.strategy
        params = decision.params

        try:
            if strategy == RepairStrategy.PATCH_SCRIPT:
                result = self._execute_patch(params, entry)
            elif strategy == RepairStrategy.REPLAY_VERIFY:
                result = self._execute_replay(params, entry)
            elif strategy == RepairStrategy.RE_RECORD:
                result = self._execute_re_record(params, entry)
            elif strategy == RepairStrategy.ENV_FIX:
                result = self._execute_env_fix(params, entry)
            elif strategy == RepairStrategy.SKIP:
                result = RepairResult(
                    strategy=strategy, success=True,
                    message="策略为跳过，不执行修复",
                )
            else:
                result = RepairResult(
                    strategy=strategy, success=False,
                    message=f"未知策略: {strategy}",
                )
        except Exception as e:
            result = RepairResult(
                strategy=strategy, success=False,
                message=f"执行异常: {e}",
            )

        result.duration_ms = int((time.time() - start) * 1000)
        self.results.append(result)
        return result

    # 失败自动降级
    def execute_with_fallback(
        self, decision: RepairDecision, entry: FailureEntry,
        max_attempts: int = 3,
    ) -> RepairResult:

        all_strategies = [decision.strategy] + decision.fallback_chain

        for i, strategy in enumerate(all_strategies[:max_attempts]):
            logger.info("尝试策略 %d/%d: %s", i + 1, max_attempts, strategy.value)

            # 回退时为新策略重新构建 params（不同策略需要不同参数）
            if i == 0:
                params = decision.params
            else:
                params = self._build_params_for_strategy(entry, strategy)

            current_decision = RepairDecision(
                strategy=strategy,
                priority=decision.priority,
                score=decision.score * (0.8 ** i),  # 每次降级降低评估分数
                reasoning=f"{'回退到' if i > 0 else '使用'}策略: {strategy.value}",
                params=params,
            )

            result = self.execute(current_decision, entry)

            if result.success:
                if i > 0:
                    logger.info("回退策略成功: %s (第 %d 次尝试)", strategy.value, i + 1)
                return result

            logger.warning("策略 %s 失败: %s", strategy.value, result.message)

        return RepairResult(
            strategy=all_strategies[-1] if all_strategies else RepairStrategy.SKIP,
            success=False,
            message=f"所有策略均失败，已尝试: {[s.value for s in all_strategies[:max_attempts]]}",
        )

    def _build_params_for_strategy(self, entry: FailureEntry, strategy: RepairStrategy) -> Dict[str, Any]:
        return _build_strategy_params(entry, strategy)

    def _execute_patch(self, params: Dict, entry: FailureEntry) -> RepairResult:
        """执行脚本修复"""
        patch_type = params.get("patch_type", "manual")

        if patch_type == "healer":
            return self._patch_via_healer(params, entry)
        elif patch_type == "ai_analysis":
            return self._patch_via_ai(params, entry)
        else:
            return RepairResult(
                strategy=RepairStrategy.PATCH_SCRIPT, success=False,
                message="需要人工修改脚本",
            )

    def _patch_via_five_tier_engine(self, params: Dict, entry: FailureEntry) -> RepairResult:
        """通过五层自愈引擎修复选择器"""
        selector = params.get("selector", "")
        page_url = params.get("page_url", "")
        file_path = params.get("file", "")
        action = params.get("action", "")
        error_message = params.get("error_message", "")

        if not selector:
            return RepairResult(
                strategy=RepairStrategy.PATCH_SCRIPT, success=False,
                message="选择器为空，无法调用自愈引擎",
            )

        try:
            from self_healing.pipeline import HealingPipeline
            from playwright.sync_api import sync_playwright

            # 复用登录守卫，确保登录态有效
            try:
                from login.refresh_login_state import ensure_valid_login_state
                login_ok = ensure_valid_login_state()
                if not login_ok:
                    logger.warning("登录态刷新失败，自愈引擎可能在未登录状态下执行")
            except Exception as e:
                logger.warning("登录守卫调用失败: %s，继续尝试使用现有登录态", e)

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
                storage_state_path = str(self.project_root / "login_state" / "storage_state.json")
                context_args = {"viewport": {"width": 1366, "height": 768}, "ignore_https_errors": True}
                if os.path.exists(storage_state_path):
                    context_args["storage_state"] = storage_state_path
                context = browser.new_context(**context_args)
                page = context.new_page()

                if page_url and page_url != "about:blank":
                    try:
                        page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_timeout(3000)
                    except Exception as e:
                        logger.warning("导航失败: %s", e)

                cache_dir = str(self.project_root / "output" / "heal_cache")
                pipeline = HealingPipeline(page, cache_dir=cache_dir)
                result = pipeline.heal(selector, action=action, page_url=page_url, error_message=error_message)

                browser.close()

            if result.success:
                from self_healing.source_patcher import SourcePatcher
                if file_path and os.path.exists(file_path):
                    success = SourcePatcher.patch_file(file_path, selector, result.healed_selector)
                    return RepairResult(
                        strategy=RepairStrategy.PATCH_SCRIPT,
                        success=success,
                        old_value=selector,
                        new_value=result.healed_selector,
                        file_patched=file_path,
                        message=f"五层引擎修复({result.strategy_name}): {selector!r} → {result.healed_selector!r}" if success else "回写失败",
                    )
                return RepairResult(
                    strategy=RepairStrategy.PATCH_SCRIPT, success=False,
                    old_value=selector, new_value=result.healed_selector,
                    message="引擎修复成功但源文件不可达",
                )
            else:
                fail_reason = (
                    f"置信度不足({result.confidence:.2f})"
                    if result.confidence > 0
                    else "所有策略均未找到有效候选"
                )
                return RepairResult(
                    strategy=RepairStrategy.PATCH_SCRIPT, success=False,
                    old_value=selector,
                    message=f"五层引擎未能修复: {fail_reason}",
                )
        except Exception as e:
            return RepairResult(
                strategy=RepairStrategy.PATCH_SCRIPT, success=False,
                message=f"五层引擎调用异常: {e}",
            )

    _patch_via_healer = _patch_via_five_tier_engine

    def _patch_via_ai(self, params: Dict, entry: FailureEntry) -> RepairResult:
        """通过 AI 分析修复断言逻辑

        当前实现：生成修复建议，不自动修改（断言逻辑需要人工确认）
        todo: 可扩展为 AI 自动修改断言代码
        """
        file_path = params.get("file", "")
        error_msg = params.get("error_message", "")
        line = params.get("line", 0)

        suggestion = {
            "type": "assertion_fix",
            "file": file_path,
            "line": line,
            "error": error_msg[:500],
            "recommendations": [],
        }

        if "expected" in error_msg.lower() and "but got" in error_msg.lower():
            suggestion["recommendations"].append(
                "断言预期值不匹配 — 检查是否是业务数据变更导致预期值需要更新"
            )
            suggestion["recommendations"].append(
                "如果预期值是动态的，考虑改为范围断言或包含断言"
            )
        elif "not found" in error_msg.lower() or "not visible" in error_msg.lower():
            suggestion["recommendations"].append(
                "断言目标不存在 — 可能是页面流程变化导致，建议回放确认"
            )
        else:
            suggestion["recommendations"].append(
                "建议人工审查断言逻辑，或使用回放复现收集更多信息"
            )

        suggestion_path = self.project_root / "output" / "repair_suggestions.json"
        suggestion_path.parent.mkdir(parents=True, exist_ok=True)

        suggestions = []
        if suggestion_path.exists():
            try:
                suggestions = json.loads(suggestion_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        suggestions.append({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "test_name": entry.test_name,
            **suggestion,
        })
        suggestion_path.write_text(
            json.dumps(suggestions, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return RepairResult(
            strategy=RepairStrategy.PATCH_SCRIPT, success=False,
            message=f"断言修复需人工介入，建议已写入 {suggestion_path}",
        )

    def _execute_replay(self, params: Dict, entry: FailureEntry) -> RepairResult:
        script_path = params.get("script_path", "")
        headless = params.get("headless", True)

        if not script_path or not os.path.exists(script_path):
            return RepairResult(
                strategy=RepairStrategy.REPLAY_VERIFY, success=False,
                message=f"脚本不存在: {script_path}",
            )

        cmd = [
            sys.executable, "-m", "pytest",
            script_path,
            "-x", "-v", "--tb=short",
        ]


        try:
            # 传环境变量防止子进程递归
            env = os.environ.copy()
            env["STRATEGY_REPAIR_RUNNING"] = "1"

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120,
                cwd=str(self.project_root), env=env,
            )

            if result.returncode == 0:
                return RepairResult(
                    strategy=RepairStrategy.REPLAY_VERIFY, success=True,
                    verification_passed=True,
                    message="回放通过 — 问题未复现，可能是间歇性故障",
                )
            else:
                # 提取失败信息
                stderr_tail = "\n".join(result.stderr.split("\n")[-10:])
                return RepairResult(
                    strategy=RepairStrategy.REPLAY_VERIFY, success=False,
                    verification_passed=False,
                    message=f"回放确认可复现（需继续修复）:\n{stderr_tail}",
                )
        except subprocess.TimeoutExpired:
            return RepairResult(
                strategy=RepairStrategy.REPLAY_VERIFY, success=False,
                message="回放超时（120s）",
            )

    def _execute_re_record(self, params: Dict, entry: FailureEntry) -> RepairResult:
        """触发重新录制 — 输出指令，由用户执行（录制需要人工操作页面）"""
        module_name = params.get("module_name", "unknown")
        page_url = params.get("page_url", "")

        cmd = f'{sys.executable} cli.py record {module_name}'
        if page_url:
            cmd += f' --url "{page_url}"'

        return RepairResult(
            strategy=RepairStrategy.RE_RECORD, success=False,
            message=f"需要重新录制模块 [{module_name}]，执行命令:\n  {cmd}",
        )

    def _execute_env_fix(self, params: Dict, entry: FailureEntry) -> RepairResult:
        fix_type = params.get("fix_type", "")

        if fix_type == "refresh_login":
            return self._fix_login(params, entry)
        elif fix_type == "retry_with_backoff":
            return self._fix_network_retry(params, entry)
        elif fix_type == "restart_browser":
            # 浏览器崩溃 — 当前 session 里没法重启，标记失败让下次跑自动重建
            return RepairResult(
                strategy=RepairStrategy.ENV_FIX, success=False,
                message="浏览器崩了 — 当前 session 无法重启，下次运行会自动重建浏览器",
            )
        else:
            return RepairResult(
                strategy=RepairStrategy.ENV_FIX, success=False,
                message=f"未知环境修复类型: {fix_type}",
            )

    def _fix_login(self, params: Dict, entry: FailureEntry = None) -> RepairResult:
        storage_state = params.get("storage_state", "login_state/storage_state.json")
        login_script = self.project_root / "login" / "auto_login.py"

        if not login_script.exists():
            return RepairResult(
                strategy=RepairStrategy.ENV_FIX, success=False,
                message=f"自动登录脚本不存在: {login_script}，请手动执行: python3 login/auto_login.py",
            )

        try:
            result = subprocess.run(
                [sys.executable, str(login_script)],
                capture_output=True, text=True, timeout=120,
                cwd=str(self.project_root),
            )
            if result.returncode != 0:
                return RepairResult(
                    strategy=RepairStrategy.ENV_FIX, success=False,
                    message=f"自动登录失败: {result.stderr[:300]}",
                )
        except Exception as e:
            return RepairResult(
                strategy=RepairStrategy.ENV_FIX, success=False,
                message=f"登录脚本执行异常: {e}",
            )

        # 登录刷新成功后，重跑一次测试验证是否修复
        script_path = entry.file if entry else ""
        # 没有脚本路径可验证，默认成功
        if not script_path or not os.path.exists(script_path):
            return RepairResult(
                strategy=RepairStrategy.ENV_FIX, success=True,
                message="登录态已自动刷新（无法自动验证，请手动确认）",
            )

        env = os.environ.copy()
        env["STRATEGY_REPAIR_RUNNING"] = "1"

        try:
            verify = subprocess.run(
                [sys.executable, "-m", "pytest", script_path, "-x", "--tb=short"],
                capture_output=True, text=True, timeout=120,
                cwd=str(self.project_root), env=env,
            )
            if verify.returncode == 0:
                return RepairResult(
                    strategy=RepairStrategy.ENV_FIX, success=True,
                    message="登录态刷新成功，重跑测试通过",
                )
            else:
                return RepairResult(
                    strategy=RepairStrategy.ENV_FIX, success=False,
                    message="登录态刷新后测试仍然失败，可能不是登录态问题",
                )
        except subprocess.TimeoutExpired:
            return RepairResult(
                strategy=RepairStrategy.ENV_FIX, success=False,
                message="登录态刷新后验证超时",
            )

    def _fix_network_retry(self, params: Dict, entry: FailureEntry) -> RepairResult:
        max_retries = params.get("max_retries", 3)
        script_path = entry.file

        if not script_path or not os.path.exists(script_path):
            return RepairResult(
                strategy=RepairStrategy.ENV_FIX, success=False,
                message=f"网络问题但脚本不可达: {script_path}",
            )

        # 实际执行重试，传环境变量防止子进程重复触发
        env = os.environ.copy()
        env["STRATEGY_REPAIR_RUNNING"] = "1"

        for attempt in range(1, max_retries + 1):
            logger.info("网络重试 %d/%d", attempt, max_retries)
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pytest", script_path, "-x", "--tb=short"],
                    capture_output=True, text=True, timeout=120,
                    cwd=str(self.project_root), env=env,
                )
                if result.returncode == 0:
                    return RepairResult(
                        strategy=RepairStrategy.ENV_FIX, success=True,
                        message=f"网络重试成功（第 {attempt} 次）",
                    )
            except subprocess.TimeoutExpired:
                logger.warning("重试 %d 超时", attempt)

            if attempt < max_retries:
                time.sleep(2 * attempt)

        return RepairResult(
            strategy=RepairStrategy.ENV_FIX, success=False,
            message=f"网络重试 {max_retries} 次均失败",
        )

    def _load_dom_schema(self, entry: FailureEntry) -> Optional[Dict[str, Any]]:
        """加载 DOM Schema 供自愈引擎使用

        优先从 entry.metadata 中读取，其次从输出目录查找对应页面的 DOM 快照。
        """
        if entry.metadata and "dom_schema" in entry.metadata:
            return entry.metadata["dom_schema"]

        dom_dir = self.project_root / "output" / "dom_snapshots"
        if dom_dir.exists():
            import hashlib
            url_hash = hashlib.md5(entry.page_url.encode()).hexdigest() if entry.page_url else ""
            if url_hash:
                dom_file = dom_dir / f"{url_hash}.json"
                if dom_file.exists():
                    try:
                        return json.loads(dom_file.read_text(encoding="utf-8"))
                    except Exception as e:
                        logger.warning("DOM Schema 加载失败: %s", e)

        return None

    @staticmethod
    def _patch_file(file_path: str, old_text: str, new_text: str) -> bool:
        """替换文件内容"""
        try:
            content = Path(file_path).read_text(encoding="utf-8")
            if old_text not in content:
                return False

            # 备份
            backup = file_path + ".bak"
            if not os.path.exists(backup):
                Path(backup).write_text(content, encoding="utf-8")

            new_content = content.replace(old_text, new_text)
            Path(file_path).write_text(new_content, encoding="utf-8")
            return True
        except Exception as e:
            logger.error("文件修改失败: %s", e)
            return False




class FailureRepairOrchestrator:
    """失败修复编排器 — 完整流程入口

    流程:
      1. 读取 heal_report.json
      2. 对每个失败条目进行分类 + 决策
      3. 按优先级排序执行修复
      4. 生成修复报告
    """

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self.engine = StrategyDecisionEngine()
        self.executor = RepairExecutor(project_root)

    def run(self, report_path: Optional[str] = None) -> Dict[str, Any]:
        """运行完整修复流程

        Args:
            report_path: heal_report.json 路径，默认 output/heal_report.json

        Returns:
            dict: 修复报告
        """
        if report_path is None:
            report_path = str(self.project_root / "output" / "heal_report.json")

        # 1. 读取失败报告
        failures = self._load_failures(report_path)
        if not failures:
            return {"total": 0, "message": "无失败记录"}

        print(f"\n{'='*60}")
        print(f"🧠 回退优先级策略层 — 分析 {len(failures)} 个失败")
        print(f"{'='*60}")

        entries = [FailureEntry.from_dict(f) for f in failures]
        pairs = self.engine.decide_batch(entries)

        self._print_decision_plan(pairs)

        results = []
        for entry, decision in pairs:
            if decision.strategy == RepairStrategy.SKIP:
                results.append({
                    "test_name": entry.test_name,
                    "strategy": "skip",
                    "result": {"success": False, "message": "跳过，等待人工确认"},
                })
                print(f"\n  ⏭️ [{entry.test_name}] 跳过，等待人工确认")
                continue

            print(f"\n  ▶ [{entry.test_name}] → {decision.strategy.value}")
            result = self.executor.execute_with_fallback(decision, entry)

            icon = "✅" if result.success else "❌"
            print(f"    {icon} {result.message[:200]}")

            results.append({
                "test_name": entry.test_name,
                "strategy": decision.strategy.value,
                "result": result.to_dict(),
            })

        report = self._build_report(pairs, results)
        self._save_report(report)

        return report

    def _load_failures(self, report_path: str) -> List[Dict]:
        if not os.path.exists(report_path):
            print(f"⚠️ 报告文件不存在: {report_path}")
            return []

        try:
            with open(report_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("failures", [])
        except Exception as e:
            print(f"⚠️ 读取报告失败: {e}")
            return []

    def _print_decision_plan(self, pairs: List[tuple]):
        print(f"\n📋 修复计划:")
        print(f"{'─'*60}")

        for entry, decision in pairs:
            icon = {
                RepairStrategy.PATCH_SCRIPT: "🔧",
                RepairStrategy.REPLAY_VERIFY: "🔄",
                RepairStrategy.RE_RECORD: "🎬",
                RepairStrategy.ENV_FIX: "🌐",
                RepairStrategy.SKIP: "⏭️",
            }.get(decision.strategy, "❓")

            print(f"  {icon} [{entry.test_name}]")
            print(f"     分类: {entry.sub_category.value}")
            print(f"     策略: {decision.strategy.value} (优先级: {decision.priority.name})")
            print(f"     评估分数: {decision.score:.0%}")
            print(f"     理由: {decision.reasoning}")
            if decision.fallback_chain:
                print(f"     回退链: {' → '.join(s.value for s in decision.fallback_chain)}")
            print()

    def _build_report(
        self,
        pairs: List[tuple],
        results: List[Dict],
    ) -> Dict[str, Any]:
        # result 统一是 dict 格式，含 success 字段
        success_count = sum(
            1 for r in results
            if isinstance(r.get("result"), dict) and r["result"].get("success", False)
        )

        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total_failures": len(pairs),
            "repaired": success_count,
            "failed": len(pairs) - success_count,
            "summary": self.engine.get_decision_summary(),
            "details": results,
        }

    def _save_report(self, report: Dict):
        report_path = self.project_root / "output" / "strategy_repair_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\n📊 修复报告: {report_path.resolve()}")
