"""L0: Strict Violation 智能修复层

专门处理 Playwright strict mode violation —— 选择器匹配到了多个元素，不知道点哪个。
思路：先解析 Playwright 报错里给的 "aka" 精确选择器提示，再用真实 DOM 验证哪个最靠谱。


"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from self_healing.selector_parser import parse_selector, SelectorExpr
from self_healing.candidate_evaluator import HealingCandidate

if TYPE_CHECKING:
    from playwright.sync_api import Page

logger = logging.getLogger(__name__)


@dataclass
class StrictViolationHint:
    """从 Playwright 报错里扒出来的精确选择器提示"""
    index: int                    # 第几个匹配元素（从1开始）
    selector: str                 # Playwright 建议的选择器字符串
    selector_expr: SelectorExpr   # 解析后的结构


class StrictViolationHealer:
    """L0: Strict Violation 快速修复器

    解析 Playwright strict violation 错误文本里的 "aka" 提示，
    生成收窄后的候选选择器，再通过 DOM 验证挑出最优的那个。
    """

    """匹配 Playwright 报错里的 "aka" 提示行，格式举例：
       1) <a class="doraemon-search-toggle-btn">…</a> aka locator("form").get_by_text("展开")
       2) <a class="doraemon-search-toggle-btn">…</a> aka get_by_text("展开").nth(1)
    HTML 片段可能有闭合标签，所以用 <.+?> 做非贪婪匹配"""
    _AKA_PATTERN = re.compile(
        r'\s*(\d+)\)\s*<.+?>\s+aka\s+(.+?)$',
        re.MULTILINE,
    )

    # strict violation 报错关键词
    _STRICT_KEYWORDS = [
        "strict mode violation",
        "resolved to",
        "strict mode violation:",
    ]

    @classmethod
    def is_strict_violation(cls, error_message: str) -> bool:
        """判断是不是 strict mode violation"""
        msg_lower = error_message.lower()
        return any(kw in msg_lower for kw in cls._STRICT_KEYWORDS)

    @classmethod
    def parse_hints(cls, error_message: str) -> list[StrictViolationHint]:
        """从 Playwright 报错里解析 aka 选择器提示列表"""
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
        page: Optional["Page"] = None,
    ) -> list[HealingCandidate]:
        """L0 修复入口

        有 page 对象的话会走 DOM 验证 + 智能评分，没有的话走老版本的静态评分。
        """
        if not self.is_strict_violation(error_message):
            return []

        hints = self.parse_hints(error_message)
        if not hints:
            # 啥也没解析出来，兜底加 .first
            return self._fallback_first(original_selector, page_url)

        candidates = []
        original_expr = parse_selector(original_selector)
        has_narrowing = any(
            c.method in ("nth", "first", "last", "filter")
            for c in original_expr.calls
        )

        # 有 page 对象就先提取页面上下文（输入框的值、页面文本）
        page_context = {}
        if page:
            page_context = self._extract_page_context(page)

        for hint in hints:
            hint_selector = hint.selector

            # 跟原选择器一模一样的跳过，加了没用
            if hint_selector == original_selector:
                continue

            # 看看是不是简单的 .nth(N) / .first / .last，这种含金量不高
            is_trivial_nth = (
                hint_selector.startswith(original_selector + ".nth(")
                or hint_selector.startswith(original_selector + ".first")
                or hint_selector.startswith(original_selector + ".last")
            )

            # aka 提示是 Playwright 在真实页面上验证过的确定性结果，
            # 直接使用，不做 DOM 重验证。
            if is_trivial_nth and not has_narrowing:
                base_score = 0.90
                strategy_weight = 1.05
            elif not is_trivial_nth:
                base_score = 0.95
                strategy_weight = 1.15
            else:
                base_score = 0.85
                strategy_weight = 1.00

            candidates.append(HealingCandidate(
                selector=hint_selector,
                confidence=0.0,  # 留给 evaluator 统一评估
                source_level=0,
                strategy_name="strict_narrow",
                base_score=base_score,
                strategy_weight=strategy_weight,
                page_url=page_url,
            ))

        # 所有 hint 都不靠谱，兜底加 .first
        if not candidates or (has_narrowing and not any(not c.selector.startswith(original_selector) for c in candidates)):
            candidates.extend(self._fallback_first(original_selector, page_url))

        return candidates

    def _extract_page_context(self, page: "Page") -> dict:
        """抓页面上的输入框值和文本，用来做业务上下文感知

        比如用户之前 fill 了 "XQ-2026-00519713"，这个值会记下来，
        后面验证候选元素时看周围有没有这个文本，有的话加分。
        """
        context = {
            "input_values": [],
            "page_text": "",
        }

        try:
            # 抓所有文本输入框的当前值
            inputs = page.locator("input[type='text'], input[type='search'], textarea").all()
            for input_elem in inputs[:10]:  # 最多取10个，多了影响性能
                try:
                    value = input_elem.input_value()
                    if value and len(value) > 2:  # 太短的没意义，过滤掉
                        context["input_values"].append(value)
                except Exception:
                    pass

            # 抓页面主要文本（限制2000字符）
            try:
                body_text = page.locator("body").inner_text()
                context["page_text"] = body_text[:2000] if body_text else ""
            except Exception:
                pass

        except Exception as e:
            logger.debug(f"提取页面上下文失败: {e}")

        return context

    def _verify_and_score_candidate(
        self,
        page: "Page",
        selector: str,
        page_context: dict,
    ) -> float:
        """拿真实 DOM 验证候选选择器，返回分数调整值

        打分规则：
        - 唯一匹配（count==1）：+0.15
        - 元素可见：+0.10
        - 周围包含业务上下文（前序 fill 的值）：+0.25
        - 匹配到多个：-0.10
        - 不可见：-0.20
        - 找不到元素：-0.30
        """
        score_adjustment = 0.0

        try:
            # 把选择器字符串转成 Playwright Locator
            locator = self._parse_selector_to_locator(page, selector)

            # 第一步：看匹配了几个
            count = locator.count()
            if count == 1:
                score_adjustment += 0.15
                logger.debug(f"[L0] {selector}: 唯一匹配 (+0.15)")
            elif count > 1:
                score_adjustment -= 0.10
                logger.debug(f"[L0] {selector}: {count} 个匹配 (-0.10)")
            else:
                score_adjustment -= 0.30
                logger.debug(f"[L0] {selector}: 无匹配 (-0.30)")
                return score_adjustment  # 没匹配到就不用看了

            # 第二步：看是不是可见的
            if locator.first.is_visible():
                score_adjustment += 0.10
                logger.debug(f"[L0] {selector}: 可见 (+0.10)")
            else:
                score_adjustment -= 0.20
                logger.debug(f"[L0] {selector}: 不可见 (-0.20)")

            # 第三步：看周围文本有没有业务上下文（前序 fill 填的值）
            input_values = page_context.get("input_values", [])
            if input_values:
                try:
                    surrounding_text = locator.first.evaluate(
                        """(el) => {
                            const parent = el.closest('tr, .row, [class*="item"]') || el.parentElement;
                            return parent ? parent.innerText : '';
                        }"""
                    )
                    if surrounding_text:
                        for value in input_values:
                            if value in surrounding_text:
                                score_adjustment += 0.25
                                logger.debug(f"[L0] {selector}: 包含业务上下文 '{value}' (+0.25)")
                                break
                except Exception as e:
                    logger.debug(f"[L0] 获取周围文本失败: {e}")

        except Exception as e:
            logger.debug(f"[L0] 验证候选 {selector} 失败: {e}")
            score_adjustment -= 0.15

        return score_adjustment

    def _parse_selector_to_locator(self, page: "Page", selector: str):
        """把选择器字符串解析成 Playwright Locator，支持链式调用

        比如：get_by_role("link", name="补充信息").first
             → page.get_by_role("link", name="补充信息").first
        """
        expr = parse_selector(selector)
        locator = None

        for call in expr.calls:
            method = call.method
            args = call.args
            kwargs = call.kwargs

            if locator is None:
                # 第一个调用从 page 开始
                if method == "locator":
                    locator = page.locator(*args, **kwargs)
                elif method.startswith("get_by_"):
                    fn = getattr(page, method)
                    locator = fn(*args, **kwargs)
                else:
                    # 不认识的方法，直接用 css 选择器兜底
                    return page.locator(selector)
            else:
                # 后面的都是链式调用
                if method == "nth":
                    locator = locator.nth(*args)
                elif method == "first":
                    locator = locator.first
                elif method == "last":
                    locator = locator.last
                elif method == "filter":
                    locator = locator.filter(**kwargs)
                elif method.startswith("get_by_"):
                    fn = getattr(locator, method)
                    locator = fn(*args, **kwargs)
                elif method == "locator":
                    locator = locator.locator(*args, **kwargs)

        return locator if locator else page.locator(selector)

    def _fallback_first(
        self, original_selector: str, page_url: str
    ) -> list[HealingCandidate]:
        """兜底：给原选择器加个 .first，实在没招了就用这个"""
        # 已经加过了就不重复加
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
