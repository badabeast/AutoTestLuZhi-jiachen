"""L5: iframe/ShadowDOM 自动穿透修复

独创性：
1. 自动检测元素是否在 iframe 或 Shadow DOM 中
2. 动态生成 frame_locator 前缀
3. 自动开启 >>> Shadow DOM 穿透选择器
4. playwright-healer 完全不支持此场景
"""
from __future__ import annotations

from typing import Optional

from playwright.sync_api import Page

from self_healing.selector_parser import parse_selector


class L5IframeShadowPatcher:
    """L5: iframe/ShadowDOM 自动穿透修复"""

    def __init__(self, page: Page):
        self._page = page

    def heal(self, selector: str, page_url: str = "") -> Optional[tuple[str, float]]:
        """尝试 iframe/ShadowDOM 穿透修复

        检测元素是否在嵌套文档中，如果是，生成穿透选择器。

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
            # Step 1: 检测元素是否在 iframe 中
            iframe_info = self._detect_iframe(role, name)
            if iframe_info:
                healed = self._generate_iframe_selector(iframe_info, expr)
                if healed:
                    return healed, 0.80

            # Step 2: 检测元素是否在 Shadow DOM 中
            shadow_info = self._detect_shadow(role, name)
            if shadow_info:
                healed = self._generate_shadow_selector(shadow_info, expr)
                if healed:
                    return healed, 0.75

            # Step 3: 尝试混沌策略 — 同时加 iframe + shadow
            brute_force = self._brute_force_pierce(expr)
            if brute_force:
                return brute_force, 0.60

        except Exception:
            pass

        return None

    def _detect_iframe(self, role: str, name: str) -> Optional[dict]:
        """检测目标元素是否在 iframe 中

        Args:
            role: 目标元素的 ARIA role
            name: 目标元素的 name 属性

        Returns:
            包含 iframe 信息的字典，或 None
        """
        try:
            result = self._page.evaluate("""
                (args) => {
                    const target = document.querySelector(
                        `[role="${args.role}"][aria-label*="${args.name}"], ` +
                        `[role="${args.role}"][name*="${args.name}"], ` +
                        `${args.role}[name*="${args.name}"]`
                    );
                    if (!target) return null;

                    // 检查是否在 iframe 中
                    const ownerDoc = target.getRootNode();
                    if (ownerDoc !== document) {
                        // 找到对应的 iframe
                        const iframes = document.querySelectorAll('iframe, frame');
                        for (const iframe of iframes) {
                            try {
                                if (iframe.contentDocument === ownerDoc ||
                                    iframe.contentWindow?.document === ownerDoc) {
                                    return {
                                        inIframe: true,
                                        iframeSrc: iframe.getAttribute('src') || '',
                                        iframeName: iframe.getAttribute('name') || '',
                                        iframeId: iframe.id || '',
                                    };
                                }
                            } catch(e) { /* cross-origin */ }
                        }
                    }
                    return { inIframe: false };
                }
            """, {"role": role, "name": name})

            if result and result.get("inIframe"):
                return result
        except Exception:
            pass
        return None

    def _detect_shadow(self, role: str, name: str) -> Optional[dict]:
        """检测目标元素是否在 Shadow DOM 中

        Args:
            role: 目标元素的 ARIA role
            name: 目标元素的 name 属性

        Returns:
            包含 Shadow DOM 信息的字典，或 None
        """
        try:
            result = self._page.evaluate("""
                (args) => {
                    const allEls = document.querySelectorAll(`[role="${args.role}"], ${args.role}`);
                    for (const el of allEls) {
                        const nameAttr = el.getAttribute('aria-label') || el.getAttribute('name') || '';
                        if (nameAttr.includes(args.name)) {
                            // 检查是否在 Shadow DOM 中
                            const root = el.getRootNode();
                            if (root instanceof ShadowRoot) {
                                return {
                                    inShadow: true,
                                    hostTag: root.host.tagName.toLowerCase(),
                                    hostId: root.host.id || '',
                                    hostClass: root.host.className || '',
                                };
                            }
                        }
                    }
                    return { inShadow: false };
                }
            """, {"role": role, "name": name})

            if result and result.get("inShadow"):
                return result
        except Exception:
            pass
        return None

    def _generate_iframe_selector(self, iframe_info: dict, expr) -> Optional[str]:
        """生成穿透 iframe 的选择器

        Args:
            iframe_info: iframe 检测结果字典
            expr: 解析后的选择器表达式

        Returns:
            完整的穿透选择器字符串，或 None
        """
        base = expr.calls[0].to_string() if expr.calls else ""
        chain = "".join(f".{c.to_string()}" for c in expr.calls[1:])

        # 选择 iframe 定位方式
        iframe_name = iframe_info.get("iframeName", "")
        iframe_id = iframe_info.get("iframeId", "")
        iframe_src = iframe_info.get("iframeSrc", "")

        if iframe_name:
            frame_sel = f'frame_locator("iframe[name=\\"{iframe_name}\\"]")'
        elif iframe_id:
            frame_sel = f'frame_locator("#{iframe_id}")'
        elif iframe_src:
            frame_sel = f'frame_locator("iframe[src*=\\"{iframe_src}\\"]")'
        else:
            frame_sel = 'frame_locator("iframe")'

        return f"{frame_sel}.{base}{chain}"

    def _generate_shadow_selector(self, shadow_info: dict, expr) -> Optional[str]:
        """生成穿透 Shadow DOM 的选择器（使用 >>> 穿透符）

        Args:
            shadow_info: Shadow DOM 检测结果字典
            expr: 解析后的选择器表达式

        Returns:
            完整的穿透选择器字符串，或 None
        """
        base_sel = expr.calls[0].to_string() if expr.calls else ""
        chain = "".join(f".{c.to_string()}" for c in expr.calls[1:])

        # 使用 CSS >>> 穿透
        host = shadow_info.get("hostTag", "div")
        host_id = shadow_info.get("hostId", "")
        host_sel = f"#{host_id}" if host_id else host

        # 将 get_by_role 转换为 CSS + >>>
        # 这是简化处理，实际可能需要更精确的转换
        return f'locator("{host_sel} >>> {base_sel}"){chain}'

    def _brute_force_pierce(self, expr) -> Optional[str]:
        """混沌策略：尝试常见的 iframe 和 shadow 穿透组合

        Args:
            expr: 解析后的选择器表达式

        Returns:
            可能的穿透选择器字符串，或 None
        """
        base = expr.calls[0].to_string() if expr.calls else ""
        chain = "".join(f".{c.to_string()}" for c in expr.calls[1:])

        # 尝试最常见的 iframe 穿透
        candidates = [
            f'frame_locator("iframe").{base}{chain}',
            f'frame_locator("iframe").locator("body >>> {base}"){chain}',
        ]

        for candidate in candidates:
            try:
                # 尝试编译为 Locator 看是否语法正确
                parsed = parse_selector(candidate)
                if parsed.calls:
                    return candidate
            except Exception:
                continue

        return None
