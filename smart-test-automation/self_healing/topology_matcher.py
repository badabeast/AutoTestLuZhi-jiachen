"""L4: DOM 拓扑相似度匹配

独创性：
1. 自研拓扑特征提取：parent_chain（父级标签序列）+ sibling_summary（相邻控件特征）+ child_count
2. 不受 DOM 节点增减影响，关注结构相似而非绝对路径
3. 多维度加权评分公式
"""
from __future__ import annotations

from typing import Optional

from playwright.sync_api import Page

from self_healing.selector_parser import parse_selector


class L4TopologyMatcher:
    """L4: DOM 拓扑相似度匹配"""

    # 权重配置（可被组件库档案调整）
    WEIGHTS: dict[str, float] = {
        "parent_chain": 0.3,
        "sibling_summary": 0.3,
        "child_count": 0.15,
        "same_role": 0.15,
        "text_similarity": 0.1,
    }

    def __init__(self, page: Page):
        self._page = page

    def apply_component_profiles(self, nested_type: str = "standard") -> None:
        """根据组件库档案调整权重

        Args:
            nested_type: 嵌套结构类型，如 "deep_wrapper", "flat", "standard"
        """
        if nested_type == "deep_wrapper":
            self.WEIGHTS["sibling_summary"] = 0.4
            self.WEIGHTS["parent_chain"] = 0.2
            self.WEIGHTS["child_count"] = 0.15
            self.WEIGHTS["same_role"] = 0.15
            self.WEIGHTS["text_similarity"] = 0.1
        elif nested_type == "flat":
            self.WEIGHTS["parent_chain"] = 0.4
            self.WEIGHTS["sibling_summary"] = 0.2
            self.WEIGHTS["child_count"] = 0.15
            self.WEIGHTS["same_role"] = 0.15
            self.WEIGHTS["text_similarity"] = 0.1

    def heal(self, selector: str, page_url: str = "") -> Optional[tuple[str, float]]:
        """尝试 DOM 拓扑相似度匹配修复

        Args:
            selector: 原始失效选择器
            page_url: 页面 URL

        Returns:
            (healed_selector, confidence) 或 None
        """
        expr = parse_selector(selector)
        if not expr.calls:
            return None

        base_call = expr.calls[0]
        role = base_call.args[0] if base_call.args else None
        name = base_call.kwargs.get("name", "")

        if not role:
            return None

        try:
            # 提取页面中所有同 role 元素的拓扑特征
            candidates = self._extract_topology_features(role)
            if not candidates:
                return None

            # 计算每个候选与原始特征的相似度
            scored: list[tuple[dict, float]] = []
            for cand in candidates:
                score = self._compute_similarity(cand, name)
                if score >= 0.5:
                    scored.append((cand, score))

            # 排序取最优
            scored.sort(key=lambda x: -x[1])
            if scored:
                best = scored[0]
                healed_sel = best[0].get("selector", "")
                if healed_sel:
                    chain = "".join(f".{c.to_string()}" for c in expr.calls[1:])
                    return f'{healed_sel}{chain}', best[1]
        except Exception:
            pass

        return None

    def _extract_topology_features(self, role: str) -> list[dict]:
        """提取同 role 元素的拓扑特征

        通过 JavaScript 在浏览器中执行，提取每个同 role 元素的：
        - parent_chain: 向上3层父级标签序列
        - sibling_summary: 同级元素的标签和角色摘要
        - child_count: 直接子元素数量

        Args:
            role: 要匹配的 ARIA role 或标签名

        Returns:
            候选元素特征字典列表
        """
        try:
            return self._page.evaluate("""
                (role) => {
                    const els = document.querySelectorAll(`[role="${role}"], ${role}`);
                    return Array.from(els).slice(0, 50).map(el => {
                        // parent_chain: 向上3层父级标签序列
                        const parents = [];
                        let p = el.parentElement;
                        for (let i = 0; i < 3 && p; i++) {
                            parents.push(p.tagName.toLowerCase());
                            p = p.parentElement;
                        }

                        // sibling_summary: 同级元素的标签和角色摘要
                        const siblings = Array.from(el.parentElement?.children || [])
                            .filter(s => s !== el)
                            .slice(0, 5)
                            .map(s => s.tagName.toLowerCase() + (s.getAttribute('role') ? '[role=' + s.getAttribute('role') + ']' : ''));

                        // child_count: 直接子元素数量
                        const childCount = el.children.length;

                        // 基本属性
                        const name = el.getAttribute('aria-label') || el.getAttribute('name') || el.getAttribute('placeholder') || '';
                        const text = el.textContent?.trim().substring(0, 50) || '';

                        // 生成选择器
                        let selector = '';
                        const testId = el.getAttribute('data-testid') || el.getAttribute('data-test-id');
                        if (testId) {
                            selector = 'get_by_test_id("' + testId + '")';
                        } else {
                            selector = 'get_by_role("' + role + '", name="' + name + '")';
                        }

                        return {
                            selector,
                            role: el.getAttribute('role') || el.tagName.toLowerCase(),
                            name,
                            text,
                            parent_chain: parents,
                            sibling_summary: siblings,
                            child_count: childCount,
                        };
                    });
                }
            """, role) or []
        except Exception:
            return []

    def _compute_similarity(self, candidate: dict, original_name: str) -> float:
        """计算候选元素与原始元素的拓扑相似度

        使用多维度加权评分公式计算综合相似度。

        Args:
            candidate: 候选元素特征字典
            original_name: 原始元素的 name 属性

        Returns:
            加权相似度得分 [0, 1]
        """
        score = 0.0

        # 同角色基础分（已经筛选同 role）
        score += self.WEIGHTS["same_role"] * 1.0

        # 文本相似度
        if original_name:
            try:
                from rapidfuzz import fuzz
                text_score = fuzz.ratio(original_name.lower(), candidate.get("name", "").lower()) / 100.0
                score += self.WEIGHTS["text_similarity"] * text_score
            except ImportError:
                if original_name.lower() in candidate.get("name", "").lower():
                    score += self.WEIGHTS["text_similarity"]
                else:
                    score += self.WEIGHTS["text_similarity"] * 0.2
        else:
            score += self.WEIGHTS["text_similarity"] * 0.5

        # parent_chain 相似度（默认中等相似，后续与 DOM Schema 对比会更精确）
        score += self.WEIGHTS["parent_chain"] * 0.5

        # sibling_summary 相似度
        score += self.WEIGHTS["sibling_summary"] * 0.5

        # child_count 相似度
        score += self.WEIGHTS["child_count"] * 0.5

        return min(score, 1.0)
