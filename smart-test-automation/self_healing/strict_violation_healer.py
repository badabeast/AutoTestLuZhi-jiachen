"""L0: Strict Violation 快速修复层

独创性：针对 Playwright strict mode violation（选择器匹配到多个元素），
解析 Playwright 报错信息中的精确选择器建议，快速收窄选择器，
无需走五层引擎的"找替代选择器"逻辑。

Playwright 在 strict violation 错误中会给出每个匹配元素的更精确选择器，
如 `aka locator("form").get_by_text("展开")` 或 `aka get_by_text("展开").nth(1)`。
本模块解析这些提示，生成收窄后的选择器候选。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from self_healing.selector_parser import parse_selector, SelectorExpr
from self_healing.candidate_evaluator import HealingCandidate

logger = logging.getLogger(__name__)


@dataclass
class StrictViolationHint:
    """从 Playwright strict violation 错误信息中解析出的精确选择器提示"""
    index: int                    # 匹配元素序号（从1开始）
    selector: str                 # Playwright 建议的精确选择器字符串
    selector_expr: SelectorExpr   # 解析后的结构


class StrictViolationHealer:
    """L0: Strict Violation 快速修复器

    解析 Playwright strict violation 错误文本，提取其中的精确选择器建议，
    生成收窄后的候选选择器。
    """

    # 匹配 Playwright strict violation 错误中的 "aka" 提示行
    # 格式: "    1) <a class="doraemon-search-toggle-btn">…</a> aka locator("form").get_by_text("展开")"
    #  或: "    2) <a class="doraemon-search-toggle-btn">…</a> aka get_by_text("展开").nth(1)"
    # 注意：HTML 片段可能包含闭合标签如 </a>，所以用 <.+?> 匹配
    _AKA_PATTERN = re.compile(
        r'\s*(\d+)\)\s*<.+?>\s+aka\s+(.+?)$',
        re.MULTILINE,
    )

    # 检测 strict violation 错误关键词
    _STRICT_KEYWORDS = [
        "strict mode violation",
        "resolved to",
        "strict mode violation:",
    ]

    @classmethod
    def is_strict_violation(cls, error_message: str) -> bool:
        """判断异常信息是否为 Playwright strict mode violation"""
        msg_lower = error_message.lower()
        return any(kw in msg_lower for kw in cls._STRICT_KEYWORDS)

    @classmethod
    def parse_hints(cls, error_message: str) -> list[StrictViolationHint]:
        """从 Playwright 错误信息中解析精确选择器提示

        Args:
            error_message: Playwright 的完整错误字符串

        Returns:
            解析出的 StrictViolationHint 列表（按序号排列）
        """
        hints = []
        for match in cls._AKA_PATTERN.finditer(error_message):
            index = int(match.group(1))
            selector_str = match.group(2).strip()
            try:
                expr = parse_selector(selector_str)
                hints.append(StrictViolationHint(
                    index=index,
                    selector=selector_str,
                    selector_expr=expr,
                ))
            except Exception as e:
                logger.debug(f"解析 aka 选择器失败: {selector_str!r}, {e}")
        return hints

    def heal(
        self,
        original_selector: str,
        error_message: str,
        page_url: str = "",
    ) -> list[HealingCandidate]:
        """执行 L0 Strict Violation 快速修复

        策略：
        1. 如果原选择器本身没有 .nth()/.first/.last 后缀，
           且 Playwright 提示了更精确的选择器，取第一个提示作为首选候选
        2. 如果原选择器已有 .nth()/.first/.last 但仍然 strict violation，
           说明需要更精细的上下文定位，取 Playwright 提示的有上下文的选择器
        3. 如果有多个提示，生成".first"作为兜底候选

        Args:
            original_selector: 原始失效选择器
            error_message: Playwright 完整错误信息
            page_url: 页面 URL

        Returns:
            修复候选列表
        """
        if not self.is_strict_violation(error_message):
            return []

        hints = self.parse_hints(error_message)
        if not hints:
            # 解析失败，生成 .first 兜底
            return self._fallback_first(original_selector, page_url)

        candidates = []
        original_expr = parse_selector(original_selector)
        has_narrowing = any(
            c.method in ("nth", "first", "last", "filter")
            for c in original_expr.calls
        )

        for hint in hints:
            hint_selector = hint.selector

            # 跳过与原选择器相同或仅仅是原选择器加 .nth(N) 的提示
            # （因为加 .nth(1) 就是原始问题的另一面）
            if hint_selector == original_selector:
                continue

            # 如果 hint 是 "原选择器.nth(N)"，且原选择器没有 narrowing，
            # 这是有用的但不是最优的
            is_trivial_nth = (
                hint_selector.startswith(original_selector + ".nth(")
                or hint_selector.startswith(original_selector + ".first")
                or hint_selector.startswith(original_selector + ".last")
            )

            if is_trivial_nth and not has_narrowing:
                # trivial nth — 置信度中等
                candidates.append(HealingCandidate(
                    selector=hint_selector,
                    confidence=0.0,  # 将被 evaluator 评估
                    source_level=0,
                    strategy_name="strict_narrow",
                    base_score=0.80,
                    strategy_weight=1.05,  # L0 权重高于 cache
                    page_url=page_url,
                ))
            elif not is_trivial_nth:
                # 有上下文约束的选择器 — 如 locator("form").get_by_text("展开")
                # 这是最佳候选
                candidates.append(HealingCandidate(
                    selector=hint_selector,
                    confidence=0.0,
                    source_level=0,
                    strategy_name="strict_narrow",
                    base_score=0.90,
                    strategy_weight=1.15,  # L0 最高权重
                    page_url=page_url,
                ))

        # 如果没有候选（所有 hint 都是 same 或 trivial），兜底 .first
        if not candidates or (has_narrowing and not any(not c.selector.startswith(original_selector) for c in candidates)):
            candidates.extend(self._fallback_first(original_selector, page_url))

        return candidates

    def _fallback_first(
        self, original_selector: str, page_url: str
    ) -> list[HealingCandidate]:
        """兜底策略：给原选择器加上 .first 后缀"""
        # 避免重复加 .first
        if original_selector.endswith(".first"):
            return []

        fallback_sel = f"{original_selector}.first"
        return [HealingCandidate(
            selector=fallback_sel,
            confidence=0.0,
            source_level=0,
            strategy_name="strict_narrow",
            base_score=0.70,
            strategy_weight=1.00,
            page_url=page_url,
        )]
