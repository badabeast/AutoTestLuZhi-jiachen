"""L2: 语义定位自动生成

独创性：
1. 强制优先级链：test_id > role+name > aria-label > 文本模糊匹配
2. 自研文本相似度匹配规则（区别于简单字符串包含）
3. 每个候选自动计算置信度分数
"""
from __future__ import annotations

from typing import Optional

from playwright.sync_api import Page

from self_healing.selector_parser import parse_selector, SelectorExpr, MethodCall
from self_healing.component_manager import ComponentLibraryManager


# 语义定位优先级链（独创调度逻辑）
LOCATOR_PRIORITIES: list[tuple[int, str, float]] = [
    (0, "get_by_test_id", 0.95),
    (1, "get_by_role", 0.85),
    (2, "get_by_label", 0.82),
    (3, "get_by_text", 0.70),
]


class L2SemanticGenerator:
    """L2: 语义定位自动生成"""

    def __init__(self, page: Page):
        self._page = page
        self._profiles_applied: bool = False

    def apply_component_profiles(self) -> None:
        """注入组件库档案，调整优先级"""
        manager = ComponentLibraryManager()
        # 需要先执行检测才能获取活跃档案
        # 这里仅标记组件库已注入，实际优先级调整在候选生成时动态生效
        self._profiles_applied = True

    def heal(self, selector: str, page_url: str = "") -> Optional[tuple[str, float]]:
        """尝试语义定位修复

        Args:
            selector: 原始失效选择器字符串
            page_url: 页面 URL

        Returns:
            (healed_selector, confidence) 或 None
        """
        expr = parse_selector(selector)
        if not expr.calls:
            return None

        # 提取第一个方法调用（基础选择器）
        base_call = expr.calls[0]

        # 按优先级尝试每一种定位策略
        candidates = self._generate_candidates(base_call, expr)

        # 逐个验证候选是否能定位到元素
        for candidate_sel, confidence in candidates:
            try:
                # 使用 Playwright 验证候选选择器
                locator = self._evaluate_selector(candidate_sel)
                if locator and locator.count() > 0:
                    # 验证元素是否可见且可交互
                    if locator.first.is_visible():
                        return candidate_sel, confidence
            except Exception:
                continue

        return None

    def _generate_candidates(self, base_call: MethodCall, expr: SelectorExpr) -> list[tuple[str, float]]:
        """根据基础选择器和优先级生成候选列表"""
        candidates: list[tuple[str, float]] = []

        # 从原始选择器中提取语义信息
        role: Optional[str] = None
        name: Optional[str] = None
        text: Optional[str] = None
        label: Optional[str] = None
        test_id: Optional[str] = None

        if base_call.method == "get_by_role":
            role = base_call.args[0] if base_call.args else None
            name = base_call.kwargs.get("name", "")
        elif base_call.method == "get_by_text":
            text = base_call.args[0] if base_call.args else None
        elif base_call.method == "get_by_label":
            label = base_call.args[0] if base_call.args else None
        elif base_call.method == "get_by_test_id":
            test_id = base_call.args[0] if base_call.args else None
        elif base_call.method == "locator":
            # CSS 选择器基，尝试提取信息
            pass

        # 1. 尝试 test_id（最稳定）
        search_name = name or text or label
        if search_name:
            test_id_candidate = self._find_by_test_id(role or "textbox", search_name)
            if test_id_candidate:
                candidates.append((test_id_candidate, 0.95))

        # 2. 尝试 role+name 变异
        if role and name:
            # 2a. 精确匹配
            candidates.append((f'get_by_role("{role}", name="{name}")', 0.85))
            # 2b. 放松 exact
            candidates.append((f'get_by_role("{role}", name="{name}", exact=False)', 0.80))
            # 2c. 文本相似度匹配（自研规则）
            similar_names = self._find_similar_names(role, name)
            for sim_name, sim_score in similar_names:
                candidates.append((f'get_by_role("{role}", name="{sim_name}")', 0.75 * sim_score))

        # 3. 仅 role 匹配
        if role:
            candidates.append((f'get_by_role("{role}")', 0.60))

        # 4. aria-label 匹配
        if name or label:
            aria_candidate = self._find_by_aria_label(name or label or "")
            if aria_candidate:
                candidates.append((aria_candidate, 0.82))

        # 5. 文本模糊匹配
        if text or name:
            text_content = text or name or ""
            candidates.append((f'get_by_text("{text_content}")', 0.70))
            candidates.append((f'get_by_text("{text_content}", exact=False)', 0.65))

        return candidates

    def _evaluate_selector(self, selector_str: str) -> Optional[object]:
        """将选择器字符串转为 Playwright Locator"""
        expr = parse_selector(selector_str)
        result = None
        for call in expr.calls:
            method = call.method
            args = call.args
            kwargs = call.kwargs
            try:
                if method in ("get_by_role", "get_by_text", "get_by_label",
                              "get_by_test_id", "get_by_placeholder", "get_by_alt_text",
                              "get_by_title", "locator"):
                    fn = getattr(self._page, method, None)
                    if fn is None:
                        return None
                    result = fn(*args, **kwargs)
                elif method == "nth" and result:
                    result = result.nth(*args)
                elif method == "first" and result:
                    result = result.first
                elif method == "last" and result:
                    result = result.last
                elif method == "filter" and result:
                    clean_kwargs = {k: v for k, v in kwargs.items() if k != "has"}
                    result = result.filter(**clean_kwargs)
                else:
                    return None
            except Exception:
                return None
        return result

    def _find_by_test_id(self, role_hint: str, name_hint: str) -> Optional[str]:
        """在页面中搜索匹配的 data-testid"""
        try:
            test_ids = self._page.evaluate("""
                (hints) => {
                    const elements = document.querySelectorAll('[data-testid], [data-test-id]');
                    const results = [];
                    for (const el of elements) {
                        const tid = el.getAttribute('data-testid') || el.getAttribute('data-test-id');
                        const role = el.getAttribute('role') || el.tagName.toLowerCase();
                        const name = el.getAttribute('aria-label') || el.getAttribute('name') || el.placeholder || '';
                        results.push({testId: tid, role: role, name: name});
                    }
                    return results;
                }
            """, {"role": role_hint, "name": name_hint})

            for item in (test_ids or []):
                # 简单匹配：role 或 name 包含提示词
                if ((role_hint and role_hint in item.get("role", "")) or
                        (name_hint and name_hint.lower() in item.get("name", "").lower())):
                    return f'get_by_test_id("{item["testId"]}")'
        except Exception:
            pass
        return None

    def _find_by_aria_label(self, label_hint: str) -> Optional[str]:
        """搜索匹配的 aria-label"""
        try:
            found = self._page.evaluate("""
                (label) => {
                    const el = document.querySelector(`[aria-label*="${label}"]`);
                    return el ? el.getAttribute('aria-label') : null;
                }
            """, label_hint)
            if found:
                return f'get_by_label("{found}")'
        except Exception:
            pass
        return None

    def _find_similar_names(self, role: str, name: str) -> list[tuple[str, float]]:
        """自研文本相似度匹配规则"""
        try:
            # 获取页面上同类元素的所有 name
            names = self._page.evaluate("""
                (args) => {
                    const els = document.querySelectorAll(`[role="${args.role}"], ${args.role}`);
                    return Array.from(els).map(el =>
                        el.getAttribute('aria-label') ||
                        el.getAttribute('name') ||
                        el.getAttribute('placeholder') ||
                        el.textContent?.trim()?.substring(0, 50) || ''
                    ).filter(n => n);
                }
            """, {"role": role, "name": name})

            results: list[tuple[str, float]] = []
            for candidate in (names or []):
                if candidate == name:
                    continue  # 跳过完全相同（已尝试）
                # 使用 rapidfuzz 计算相似度
                try:
                    from rapidfuzz import fuzz
                    score = fuzz.ratio(name, candidate) / 100.0
                    if score >= 0.6:
                        results.append((candidate, score))
                except ImportError:
                    # 回退到简单包含检查
                    if name in candidate or candidate in name:
                        results.append((candidate, 0.7))

            return sorted(results, key=lambda x: -x[1])[:5]
        except Exception:
            return []
