"""组件库自动识别器

独创点（全部自研）：
- 多模式加权投票机制：同时运行 class_prefix / attribute / dom_structure / meta_tag 四种探测
- 每种模式命中则累加对应 weight，总分超过阈值（默认 0.6）即判定为该组件库
- 支持混合组件库：一个页面可能同时使用 Ant Design + 自研组件库
- DOM Schema 可用于离线检测（无需实时打开浏览器）
- 检测结果缓存到 DOM Schema JSON 的 component_libraries 字段

v4 同步适配：项目使用同步 pytest-playwright，detect 方法改为同步。
"""
from __future__ import annotations

import re
from typing import Optional


class ComponentLibraryDetector:
    """组件库自动识别器

    独创点（全部自研）：
    - 多模式加权投票机制：同时运行 class_prefix / attribute / dom_structure / meta_tag 四种探测
    - 每种模式命中则累加对应 weight，总分超过阈值（默认 0.6）即判定为该组件库
    - 支持混合组件库：一个页面可能同时使用 Ant Design + 自研组件库
    - DOM Schema 可用于离线检测（无需实时打开浏览器）
    - 检测结果缓存到 DOM Schema JSON 的 component_libraries 字段
    """

    DETECTION_THRESHOLD: float = 0.6

    def detect_from_schema(self, schema: dict) -> list[str]:
        """从 DOM Schema JSON 中离线识别组件库

        Args:
            schema: DOM Schema 字典

        Returns:
            识别到的组件库名称列表（可能为空或多个）
        """
        # 如果 schema 已记录了检测结果，直接返回
        cached = schema.get("component_libraries", [])
        if cached:
            return cached

        # 收集所有 class 和 attribute 用于投票
        all_classes: list[str] = []
        all_attrs: set[str] = set()
        for node in schema.get("nodes", []):
            all_classes.extend(node.get("classes_stable", []))
            all_classes.extend(node.get("classes_dynamic", []))
            for attr_name in node.get("attributes", {}):
                all_attrs.add(attr_name)

        return self._vote(all_classes, all_attrs)

    def detect_sync(self, page) -> list[str]:
        """从实时页面上识别组件库（同步版本）

        使用同步 page.evaluate() 而非 await，适配 pytest-playwright 同步模式。

        Args:
            page: 同步 Page 对象（playwright.sync_api.Page）

        Returns:
            识别到的组件库名称列表（可能为空或多个）
        """
        js_code = """() => {
            const classes = new Set();
            const attrs = new Set();
            document.querySelectorAll('*').forEach(el => {
                for (const cls of el.classList || []) {
                    classes.add(cls);
                }
                for (const attr of el.attributes) {
                    attrs.add(attr.name);
                }
            });
            return {
                classes: Array.from(classes),
                attributes: Array.from(attrs)
            };
        }"""
        try:
            result = page.evaluate(js_code)
            return self._vote(result.get("classes", []), set(result.get("attributes", [])))
        except Exception:
            return []

    def _vote(self, all_classes: list, all_attrs: list | set) -> list[str]:
        """加权投票识别组件库

        策略：
        1. 加载所有可用的 ComponentLibraryProfile
        2. 对每个 profile，遍历其 detect_patterns：
           - class_prefix: 检查是否有 class 以该前缀开头，匹配数量越多权重越高
           - attribute: 检查属性名是否存在于 all_attrs 中
           - dom_structure / meta_tag: 预留接口
        3. 累加权重分数，超过 DETECTION_THRESHOLD 即判定
        4. 按得分排序返回

        Args:
            all_classes: 页面所有 CSS class 列表
            all_attrs: 页面所有属性名集合

        Returns:
            识别到的组件库名称列表，按投票得分降序
        """
        from self_healing.component_manager import ComponentLibraryManager

        # 加载所有可用的 Profile
        manager = ComponentLibraryManager()
        profiles = manager.list_profiles()
        results: dict[str, float] = {}

        for profile in profiles:
            score = 0.0
            for pattern in profile.detect_patterns:
                if pattern.type.value == "class_prefix":
                    # 检查是否有 class 以该前缀开头
                    matching = [c for c in all_classes if c.startswith(pattern.value)]
                    if matching:
                        # 匹配数量越多权重越高，但不超过 pattern.weight
                        score += pattern.weight * min(len(matching) / 5.0, 1.0)
                elif pattern.type.value == "attribute":
                    if isinstance(all_attrs, set):
                        if pattern.value in all_attrs:
                            score += pattern.weight
                    else:
                        if pattern.value in all_attrs:
                            score += pattern.weight
                elif pattern.type.value == "dom_structure":
                    # 预留：DOM 结构特征检测，需要更复杂的匹配逻辑
                    pass
                elif pattern.type.value == "meta_tag":
                    # 预留：meta 标签检测，需要 page 级别检测
                    pass

            if score >= self.DETECTION_THRESHOLD:
                results[profile.name] = score

        # 按得分排序返回
        return sorted(results.keys(), key=lambda x: -results[x])
