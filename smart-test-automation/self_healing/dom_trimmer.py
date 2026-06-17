"""局部 DOM 裁剪 AI 优化机制

独创性：
1. 公共祖先定位：找到包含目标元素的最近唯一祖先
2. N 层裁剪：默认3层，可配置
3. 属性清洗：移除 style、动态 class、hash 属性
4. Token 控制：目标 < 4000 tokens，超大时自动缩小范围
"""
from __future__ import annotations

import re
from typing import Optional

from playwright.sync_api import Page

from self_healing.selector_parser import parse_selector


# 清洗后保留的属性白名单
PRESERVED_ATTRS: frozenset[str] = frozenset({
    "role", "aria-label", "aria-labelledby", "aria-describedby",
    "aria-role", "aria-expanded", "aria-selected", "aria-checked",
    "data-testid", "data-test-id", "data-field", "data-component",
    "name", "placeholder", "title", "type", "href", "src",
    "id", "for", "value", "alt",
})

# 需要移除的属性模式
REMOVE_ATTR_PATTERNS: list[re.Pattern] = [
    re.compile(r'^style$'),
    re.compile(r'^class$'),
    re.compile(r'^data-v-[a-f0-9]{8}$'),       # Vue scoped
    re.compile(r'^_ngcontent-'),              # Angular
    re.compile(r'^_nghost-'),                 # Angular
    re.compile(r'^ng-'),                      # Angular (except ng-model etc)
    re.compile(r'^data-reactid$'),            # React
    re.compile(r'^data-react-checksum$'),     # React
]


def should_remove_attr(attr_name: str) -> bool:
    """判断属性是否应该被移除

    属性在白名单中则保留，匹配移除模式则移除。

    Args:
        attr_name: 属性名

    Returns:
        True 表示应该移除，False 表示保留
    """
    if attr_name in PRESERVED_ATTRS:
        return False
    for pattern in REMOVE_ATTR_PATTERNS:
        if pattern.match(attr_name):
            return True
    return False


class DOMTrimmer:
    """DOM 裁剪器

    用于将页面 DOM 裁剪为一个精简的 HTML 片段，供 AI 修复引擎使用。
    通过公共祖先定位 → N 层裁剪 → 属性清洗 → Token 控制 四步完成。
    """

    DEFAULT_LAYERS: int = 3
    MAX_TOKENS: int = 4000

    def __init__(self, page: Page, layers: int = DEFAULT_LAYERS):
        self._page = page
        self._layers = layers

    def trim(self, selector: str, page_url: str = "") -> str:
        """裁剪 DOM，返回精简后的 HTML 片段

        步骤：
        1. 在页面中定位目标元素
        2. 找到最近的唯一祖先节点
        3. 从祖先向下裁剪 N 层
        4. 清洗不需要的属性
        5. 控制 Token 在目标范围内

        Args:
            selector: 目标选择器字符串
            page_url: 页面 URL

        Returns:
            精简后的 DOM 字符串，失败返回空字符串
        """
        try:
            result = self._page.evaluate("""
                (args) => {
                    const {selector, layers} = args;

                    // Step 1: 尝试找到目标元素
                    let target = null;

                    // 提取 role 和 name 信息
                    const roleMatch = selector.match(/get_by_role\\(["']([\\w]+)["'](?:,\\s*name=["']([\\w\\s]+)["'])?/);
                    if (roleMatch) {
                        const role = roleMatch[1];
                        const name = roleMatch[2] || '';
                        const candidates = document.querySelectorAll(`[role="${role}"], ${role}`);
                        for (const el of candidates) {
                            const elName = el.getAttribute('aria-label') || el.getAttribute('name') || el.getAttribute('placeholder') || '';
                            if (!name || elName.includes(name)) {
                                target = el;
                                break;
                            }
                        }
                    }

                    // CSS 选择器
                    const cssMatch = selector.match(/locator\\(["']([^"']+)["']\\)/);
                    if (!target && cssMatch) {
                        try { target = document.querySelector(cssMatch[1]); } catch(e) {}
                    }

                    // text 匹配
                    const textMatch = selector.match(/get_by_text\\(["']([^"']+)["']\\)/);
                    if (!target && textMatch) {
                        const text = textMatch[1];
                        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                        while (walker.nextNode()) {
                            if (walker.currentNode.textContent.includes(text)) {
                                target = walker.currentNode.parentElement;
                                break;
                            }
                        }
                    }

                    // label 匹配
                    const labelMatch = selector.match(/get_by_label\\(["']([^"']+)["']\\)/);
                    if (!target && labelMatch) {
                        const label = labelMatch[1];
                        const el = document.querySelector(`[aria-label*="${label}"], [name*="${label}"]`);
                        if (el) target = el;
                    }

                    // test_id 匹配
                    const tidMatch = selector.match(/get_by_test_id\\(["']([^"']+)["']\\)/);
                    if (!target && tidMatch) {
                        const el = document.querySelector(`[data-testid="${tidMatch[1]}"], [data-test-id="${tidMatch[1]}"]`);
                        if (el) target = el;
                    }

                    if (!target) return '';

                    // Step 2: 找到最近唯一祖先
                    let ancestor = target;
                    for (let i = 0; i < 5; i++) {
                        const parent = ancestor.parentElement;
                        if (!parent) break;
                        // 检查唯一性：有 id 或唯一的代表性 class
                        if (parent.id ||
                            (parent.className &&
                             typeof parent.className === 'string' &&
                             parent.className.split(' ')[0] &&
                             document.querySelectorAll('.' + parent.className.split(' ')[0]).length === 1)) {
                            ancestor = parent;
                            break;
                        }
                        ancestor = parent;
                    }

                    // Step 3: 从祖先向下裁剪 N 层
                    function trimElement(el, depth) {
                        if (depth > layers) {
                            return '<' + el.tagName.toLowerCase() + ' .../>';
                        }

                        // 属性清洗
                        let attrs = '';
                        if (el.attributes) {
                            for (const attr of el.attributes) {
                                if (attr.name === 'style') continue;
                                if (attr.name.startsWith('data-v-')) continue;
                                if (attr.name.startsWith('_ngcontent-')) continue;
                                if (attr.name.startsWith('_nghost-')) continue;
                                if (attr.name === 'class') {
                                    // 只保留非动态 class 名
                                    const stableClasses = attr.value.split(/\\s+/)
                                        .filter(c => !/[a-f0-9]{6,}/.test(c) && !c.startsWith('sc-'))
                                        .slice(0, 5);
                                    if (stableClasses.length > 0) {
                                        attrs += ' class="' + stableClasses.join(' ') + '"';
                                    }
                                    continue;
                                }
                                // 截断过长的属性值
                                let val = attr.value;
                                if (val.length > 200) val = val.substring(0, 200) + '...';
                                attrs += ' ' + attr.name + '="' + val + '"';
                            }
                        }

                        const tag = el.tagName.toLowerCase();
                        // 收集直接文本节点
                        const directText = Array.from(el.childNodes)
                            .filter(n => n.nodeType === 3)
                            .map(n => n.textContent.trim())
                            .filter(t => t)
                            .join(' ')
                            .substring(0, 100);

                        const children = Array.from(el.children).slice(0, 20);
                        if (children.length === 0 && !directText) {
                            return '<' + tag + attrs + '/>';
                        }

                        let inner = directText;
                        for (const child of children) {
                            inner += '\\n' + trimElement(child, depth + 1);
                        }

                        return '<' + tag + attrs + '>' + inner + '</' + tag + '>';
                    }

                    return trimElement(ancestor, 0);
                }
            """, {"selector": selector, "layers": self._layers})

            if not result:
                return ""

            # Step 4: Token 控制
            estimated_tokens = len(result) / 3  # 粗估：约3字符/token
            if estimated_tokens > self.MAX_TOKENS:
                result = self._shrink_result(result)

            return result
        except Exception:
            return ""

    def _shrink_result(self, html: str) -> str:
        """缩小 DOM 片段到 token 控制范围内

        采用简单截断策略，保留前面部分并标注截断。

        Args:
            html: 原始 HTML 字符串

        Returns:
            缩小后的 HTML 字符串
        """
        max_chars = self.MAX_TOKENS * 3
        if len(html) > max_chars:
            return html[:max_chars] + "\n<!-- truncated -->"
        return html
