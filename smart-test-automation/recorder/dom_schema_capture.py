"""DOM Schema 自动抓取模块

独创性：在录制过程中自动捕获页面 DOM 快照，
为 AST 预扫描和自愈引擎提供无需实时浏览器的结构化 DOM 信息。

设计要点：
- capture_dom_schema(): 一次性捕获当前页面的 DOM Schema
- DomSchemaCapture: 可附加到录制流程的录制器，自动在页面加载时捕获
- 注入浏览器的 JS 脚本递归遍历 DOM，提取语义属性
- 支持组件库检测（Ant Design / Element Plus / Material UI 等）
- 输出 JSON 文件供后续自愈流程使用
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from playwright.sync_api import Page


# 注入到浏览器中的 DOM 递归快照脚本
_DOM_SNAPSHOT_JS = """
() => {
    function snapshotNode(el) {
        const attrs = {};
        for (const attr of el.attributes || []) {
            // 保留语义相关属性，丢弃样式和动态属性
            if (['style', 'class'].includes(attr.name)) continue;
            if (attr.name.startsWith('data-v-')) continue;  // Vue scoped
            if (attr.name.startsWith('ng-') && attr.name !== 'ng-model') continue; // Angular 动态
            attrs[attr.name] = attr.value;
        }

        const result = {
            tag: el.tagName?.toLowerCase() || el.nodeName?.toLowerCase(),
            attrs: attrs,
        };

        // 提取语义属性
        if (el.getAttribute('role')) result.role = el.getAttribute('role');
        if (el.getAttribute('aria-label')) result.ariaLabel = el.getAttribute('aria-label');
        if (el.getAttribute('aria-labelledby')) result.ariaLabelledby = el.getAttribute('aria-labelledby');
        if (el.getAttribute('data-testid') || el.getAttribute('data-test-id')) {
            result.testId = el.getAttribute('data-testid') || el.getAttribute('data-test-id');
        }
        if (el.getAttribute('placeholder')) result.placeholder = el.getAttribute('placeholder');
        if (el.getAttribute('name')) result.name = el.getAttribute('name');
        if (el.getAttribute('title')) result.title = el.getAttribute('title');
        if (el.getAttribute('href')) result.href = el.getAttribute('href');

        // 文本内容（只取直接文本，不递归子元素）
        const directText = Array.from(el.childNodes)
            .filter(n => n.nodeType === 3)
            .map(n => n.textContent.trim())
            .filter(t => t)
            .join(' ');
        if (directText) result.text = directText.substring(0, 200);

        // 子元素
        const children = Array.from(el.children || el.childNodes || []);
        if (children.length > 0) {
            result.children = children.slice(0, 50).map(snapshotNode);  // 最多50个子元素
            if (children.length > 50) result.truncated = true;
        }

        // Shadow DOM
        if (el.shadowRoot) {
            result.shadowChildren = Array.from(el.shadowRoot.children)
                .slice(0, 20).map(snapshotNode);
        }

        // iframe 信息
        if (el.tagName?.toLowerCase() === 'iframe' || el.tagName?.toLowerCase() === 'frame') {
            result.iframeSrc = el.getAttribute('src') || '';
        }

        return result;
    }

    return snapshotNode(document.documentElement);
}
"""

# 组件库检测脚本
_COMPONENT_DETECT_JS = """
() => {
    const indicators = {};

    // Ant Design
    const antEls = document.querySelectorAll('[class*="ant-"]');
    indicators.ant_design = {
        count: antEls.length,
        samples: Array.from(antEls).slice(0, 5).map(e => e.className.substring(0, 50))
    };

    // Element UI / Element Plus
    const elEls = document.querySelectorAll('[class*="el-"]');
    indicators.element_ui = {
        count: elEls.length,
        samples: Array.from(elEls).slice(0, 5).map(e => e.className.substring(0, 50))
    };

    // Material UI
    const muiEls = document.querySelectorAll('[class*="Mui"]');
    indicators.material_ui = {
        count: muiEls.length,
        samples: Array.from(muiEls).slice(0, 5).map(e => e.className.substring(0, 50))
    };

    // Vant
    const vantEls = document.querySelectorAll('[class*="van-"]');
    indicators.vant = {
        count: vantEls.length,
        samples: Array.from(vantEls).slice(0, 5).map(e => e.className.substring(0, 50))
    };

    // Naive UI
    const naiveEls = document.querySelectorAll('[class*="n-"]');
    indicators.naive_ui = {
        count: naiveEls.length,
        samples: Array.from(naiveEls).slice(0, 5).map(e => e.className.substring(0, 50))
    };

    // data-testid
    const testIdEls = document.querySelectorAll('[data-testid], [data-test-id]');
    indicators.data_testid = { count: testIdEls.length };

    // Custom data-* attributes（取前20个独特的）
    const allEls = document.querySelectorAll('*');
    const customAttrs = new Set();
    for (const el of allEls) {
        for (const attr of el.attributes) {
            if (attr.name.startsWith('data-')
                && !attr.name.startsWith('data-v-')
                && !attr.name.startsWith('data-testid')
                && !attr.name.startsWith('data-test-id')) {
                customAttrs.add(attr.name);
            }
        }
        if (customAttrs.size >= 20) break;
    }
    indicators.custom_data_attrs = Array.from(customAttrs);

    return indicators;
}
"""


def url_to_hash(url: str) -> str:
    """将 URL 转为安全的文件名哈希

    Args:
        url: 页面 URL 字符串

    Returns:
        12 字符的 MD5 哈希前缀
    """
    return hashlib.md5(url.encode()).hexdigest()[:12]


def capture_dom_schema(
    page: Page,
    module_name: str,
    output_base: str = "output/modules",
) -> str:
    """捕获当前页面的 DOM Schema

    通过注入 JavaScript 脚本递归遍历 DOM 树，
    提取标签、语义属性、文本内容等信息，
    同时检测页面使用的组件库类型。

    Args:
        page: Playwright Page 实例
        module_name: 模块名称（用于组织输出目录）
        output_base: 输出基础路径

    Returns:
        保存的 JSON 文件路径，空白页时返回空字符串
    """
    url = page.url
    if not url or url == "about:blank":
        return ""

    # 捕获 DOM 快照
    dom_snapshot = page.evaluate(_DOM_SNAPSHOT_JS)

    # 捕获组件库信息
    component_info = page.evaluate(_COMPONENT_DETECT_JS)

    # 组装结构
    schema: dict[str, Any] = {
        "url": url,
        "title": page.title(),
        "dom": dom_snapshot,
        "component_libraries": component_info,
        "custom_attributes": component_info.get("custom_data_attrs", []),
    }

    # 保存到文件
    schema_dir = Path(output_base) / module_name / "dom_schema"
    schema_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{url_to_hash(url)}.json"
    filepath = schema_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)

    return str(filepath)


class DomSchemaCapture:
    """DOM Schema 录制器 — 可附加到录制过程中

    自动在每次页面加载完成时捕获 DOM Schema，
    避免重复捕获同一 URL。

    用法:
        capture = DomSchemaCapture(page, module_name="demand")
        # ... 执行录制操作 ...
        capture.capture_now()  # 手动触发
        capture.stop()         # 停止自动捕获
    """

    def __init__(
        self,
        page: Page,
        module_name: str,
        output_base: str = "output/modules",
    ):
        self._page = page
        self._module_name = module_name
        self._output_base = output_base
        self._captured_urls: set[str] = set()
        self._stopped = False
        # 注册页面加载事件监听
        self._page.on("load", self._on_page_load)

    def _on_page_load(self, page: Page = None) -> None:
        """页面加载完成时自动捕获

        同一 URL 只捕获一次，避免重复写入。
        静默失败，不影响录制流程。
        """
        if self._stopped:
            return
        try:
            url = self._page.url
            if url and url not in self._captured_urls and url != "about:blank":
                capture_dom_schema(self._page, self._module_name, self._output_base)
                self._captured_urls.add(url)
        except Exception:
            pass  # 静默失败，不影响录制

    def capture_now(self) -> str:
        """手动触发当前页面捕获

        即使该 URL 已被自动捕获过，也强制重新捕获。

        Returns:
            保存的 JSON 文件路径，空白页时返回空字符串
        """
        url = self._page.url
        if url and url != "about:blank":
            filepath = capture_dom_schema(self._page, self._module_name, self._output_base)
            self._captured_urls.add(url)
            return filepath
        return ""

    @property
    def captured_urls(self) -> set[str]:
        """已捕获的 URL 集合"""
        return set(self._captured_urls)

    def stop(self) -> None:
        """停止自动捕获

        移除页面加载事件监听器，防止后续页面切换继续触发捕获。
        """
        if not self._stopped:
            self._stopped = True
            try:
                self._page.remove_listener("load", self._on_page_load)
            except Exception:
                pass
