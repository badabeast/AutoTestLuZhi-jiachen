"""L3: 动态属性过滤模糊匹配算法

独创性：
1. 自研正则规则库，自动识别和剔除 6 种常见动态属性模式
2. 生成 [class*=固定前缀] 模糊 CSS 选择器
3. 与组件库档案联动，使用组件库特定的 ignore/stable 规则
"""
from __future__ import annotations

import re
from typing import Optional

from playwright.sync_api import Page

from self_healing.selector_parser import parse_selector
from self_healing.component_manager import ComponentLibraryManager


# 自研正则规则库 — 6 种动态属性模式
DYNAMIC_PATTERNS: list[re.Pattern] = [
    # 1. CSS Modules hash: .button_abc123
    re.compile(r'^(\.[a-zA-Z_-]+)_[a-f0-9]{5,}$'),
    # 2. Tailwind/TiDash hash: .text-3xl/abcdef
    re.compile(r'^(\.[a-zA-Z]+-[a-zA-Z0-9]+)/[a-f0-9]{4,}$'),
    # 3. Styled-components: .sc-abc123
    re.compile(r'^(\.sc-)[a-f0-9]+$', re.IGNORECASE),
    # 4. Ember: .ember123
    re.compile(r'^\.ember\d+$'),
    # 5. Angular _ngcontent: [_ngcontent-xxx-c12]
    re.compile(r'^_ngcontent-[a-z]+-c\d+$'),
    # 6. Vue scoped: data-v-abc123
    re.compile(r'^data-v-[a-f0-9]{8}$'),
]

# 随机 ID 模式
RANDOM_ID_PATTERNS: list[re.Pattern] = [
    re.compile(r'^:r[a-z0-9]+:$'),          # React auto-id
    re.compile(r'^[a-f0-9]{8,}$'),           # 纯 hash
    re.compile(r'^roni-\d+$'),               # Ember
]


def filter_dynamic_classes(class_str: str, extra_ignore: list[str] | None = None) -> list[str]:
    """过滤动态 class，只保留稳定的

    Args:
        class_str: 空格分隔的 class 字符串（可带或不带点前缀）
        extra_ignore: 组件库特定的忽略正则列表

    Returns:
        稳定的 class 名称列表
    """
    classes = class_str.split()
    stable: list[str] = []
    for cls in classes:
        is_dynamic = False
        # 去掉可能的点前缀用于模式匹配
        cls_stripped = cls.lstrip(".")
        for pattern in DYNAMIC_PATTERNS:
            if pattern.match(cls) or pattern.match(f".{cls_stripped}"):
                is_dynamic = True
                break
        # 额外的组件库特定忽略规则
        if extra_ignore:
            for ip in extra_ignore:
                try:
                    if re.search(ip, cls_stripped):
                        is_dynamic = True
                        break
                except re.error:
                    continue
        if not is_dynamic:
            stable.append(cls_stripped)
    return stable


def is_random_id(id_str: str) -> bool:
    """判断 ID 是否是随机生成的"""
    for pattern in RANDOM_ID_PATTERNS:
        if pattern.match(id_str):
            return True
    return False


def generate_fuzzy_css(tag: str, stable_classes: list[str], attrs: dict) -> str:
    """生成模糊 CSS 选择器

    Args:
        tag: HTML 标签名
        stable_classes: 稳定的 class 列表
        attrs: 需要保留的属性字典

    Returns:
        模糊 CSS 选择器字符串
    """
    parts = [tag] if tag else []
    for cls in stable_classes[:3]:  # 最多用3个稳定class
        parts.append(f'[class*="{cls}"]')
    for key, val in attrs.items():
        if key.startswith("data-") and not any(p.match(key) for p in DYNAMIC_PATTERNS):
            parts.append(f'[{key}="{val}"]')
    return "".join(parts)


class L3DynamicFilterMatcher:
    """L3: 动态属性过滤模糊匹配"""

    def __init__(self, page: Page):
        self._page = page
        self._extra_ignore: list[str] = []
        self._stable_regex: list[str] = []

    def apply_component_profiles(self) -> None:
        """注入组件库档案规则"""
        manager = ComponentLibraryManager()
        # 组件库检测需要先执行，这里获取已加载的档案
        all_profiles = manager.list_profiles()
        if all_profiles:
            for profile in all_profiles:
                self._extra_ignore.extend(profile.ignore_class_regex)
                self._stable_regex.extend(profile.stable_class_regex)

    def heal(self, selector: str, page_url: str = "") -> Optional[tuple[str, float]]:
        """尝试动态属性过滤模糊匹配修复

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

        # 只对 CSS locator 或需要 DOM 扫描的情况有效
        if base_call.method == "locator":
            css = base_call.args[0] if base_call.args else ""
            healed_css = self._try_filter_css(css)
            if healed_css and healed_css != css:
                chain = self._build_chain(expr, start=1)
                return f'locator("{healed_css}"){chain}', 0.75

        # 对 role/text 选择器，尝试找同 role 的元素中 class 可匹配的
        if base_call.method in ("get_by_role", "get_by_text"):
            candidate = self._scan_similar_elements(base_call)
            if candidate:
                chain = self._build_chain(expr, start=1)
                return f'{candidate}{chain}', 0.70

        return None

    def _build_chain(self, expr, start: int = 1) -> str:
        """构建链式后缀字符串"""
        return "".join(f".{c.to_string()}" for c in expr.calls[start:])

    def _try_filter_css(self, css: str) -> Optional[str]:
        """尝试过滤 CSS 选择器中的动态属性"""
        # 简单处理：按空格和 > 拆分，过滤每个部分
        parts = re.split(r'(\s+|>)', css)
        result: list[str] = []
        for part in parts:
            if part in (' ', '>', '  ', ''):
                result.append(part)
                continue

            # 检查 class 选择器
            if '.' in part:
                classes = re.findall(r'\.([a-zA-Z_-][a-zA-Z0-9_-]*)', part)
                if classes:
                    stable = filter_dynamic_classes(" ".join(classes), self._extra_ignore)
                    if stable:
                        tag = re.match(r'^([a-zA-Z]+)', part)
                        tag_str = tag.group(1) if tag else ""
                        fuzzy = generate_fuzzy_css(tag_str, stable, {})
                        result.append(fuzzy)
                    else:
                        # 全部是动态的，保留原样
                        result.append(part)
                else:
                    result.append(part)
            else:
                result.append(part)

        return "".join(result).strip() or None

    def _scan_similar_elements(self, base_call) -> Optional[str]:
        """扫描页面中同角色的元素，找到可匹配的模糊选择器"""
        try:
            role = base_call.args[0] if base_call.args else None
            name = base_call.kwargs.get("name", "")

            if not role:
                return None

            # 搜索同 role 的元素
            elements = self._page.evaluate("""
                (args) => {
                    const els = document.querySelectorAll(`[role="${args.role}"], ${args.role}`);
                    return Array.from(els).slice(0, 50).map(el => ({
                        tag: el.tagName.toLowerCase(),
                        role: el.getAttribute('role') || el.tagName.toLowerCase(),
                        name: el.getAttribute('aria-label') || el.getAttribute('name') || '',
                        classes: el.className,
                        testId: el.getAttribute('data-testid') || '',
                    }));
                }
            """, {"role": role, "name": name})

            # 寻找稳定的匹配
            for el in (elements or []):
                stable = filter_dynamic_classes(el.get("classes", ""), self._extra_ignore)
                if stable or el.get("testId"):
                    if el.get("testId"):
                        return f'get_by_test_id("{el["testId"]}")'
                    if el.get("name") and name and name.lower() in el["name"].lower():
                        return f'get_by_role("{role}", name="{el["name"]}")'
        except Exception:
            pass

        return None
