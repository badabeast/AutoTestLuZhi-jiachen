"""组件库配置档案数据结构

独创性（全部自研）：
- 定义推荐定位策略优先级链（覆盖通用默认值）
- 定义识别特征模式（支持多模式加权投票检测）
- 定义特殊属性映射和数据属性语义
- 定义稳定/动态 class 的正则规则（覆盖通用规则）
- 定义嵌套结构特征（影响拓扑匹配权重）
- 支持 Shadow DOM 开关
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DetectPatternType(str, Enum):
    """组件库识别模式类型"""
    CLASS_PREFIX = "class_prefix"       # CSS class 前缀匹配
    ATTRIBUTE = "attribute"             # 属性存在性检测
    DOM_STRUCTURE = "dom_structure"     # 特定 DOM 结构特征
    META_TAG = "meta_tag"              # <meta> 标签检测


@dataclass
class DetectPattern:
    """组件库识别模式"""
    type: DetectPatternType
    value: str                           # 匹配值
    weight: float = 1.0                  # 权重（多模式投票制）
    description: str = ""


@dataclass
class AttributeMapping:
    """属性映射：自定义属性 → 语义说明"""
    attribute: str                       # 属性名，如 "data-field"
    semantic: str                        # 语义说明，如 "业务字段名"
    priority_boost: float = 0.0          # 使用该属性时的优先级提升


@dataclass
class ComponentLibraryProfile:
    """组件库配置档案

    独创点（全部自研）：
    - 定义推荐定位策略优先级链（覆盖通用默认值）
    - 定义识别特征模式（支持多模式加权投票检测）
    - 定义特殊属性映射和数据属性语义
    - 定义稳定/动态 class 的正则规则（覆盖通用规则）
    - 定义嵌套结构特征（影响拓扑匹配权重）
    - 支持 Shadow DOM 开关
    """
    name: str                                    # 档案名，如 "ant_design", "custom_lib_xxx"
    display_name: str = ""                       # 显示名
    version: str = ""                            # 适用的组件库版本

    # ── 识别特征 ──
    detect_patterns: list[DetectPattern] = field(default_factory=list)

    # ── 推荐定位策略优先级链 ──
    # 覆盖二级语义定位生成器的默认 PRIORITY_WEIGHTS
    locator_priorities: list[str] = field(default_factory=lambda: [
        "data-testid", "aria-label", "role+name", "css_stable", "text"
    ])

    # ── 特殊属性映射 ──
    attribute_mappings: list[AttributeMapping] = field(default_factory=list)

    # ── 稳定 class 正则（优先匹配，不会被过滤）──
    stable_class_regex: list[str] = field(default_factory=list)

    # ── 动态 class 正则（会被三级过滤掉）──
    # 覆盖三级 DynamicAttrFilterMatcher 的通用 DYNAMIC_PATTERNS
    ignore_class_regex: list[str] = field(default_factory=list)

    # ── DOM 嵌套特征 ──
    # 影响四级 DOMTopologyMatcher 的权重系数
    shadow_dom: bool = False               # 是否常见 Shadow DOM
    nested_structure: str = "standard"     # standard / deep_wrapper / flat

    # ── 自定义置信度系数 ──
    confidence_modifier: float = 1.0       # 全局置信度修正系数

    @staticmethod
    def from_dict(d: dict) -> "ComponentLibraryProfile":
        """从 JSON dict 构建 Profile"""
        detect_patterns = [
            DetectPattern(
                type=DetectPatternType(p.get("type", "class_prefix")),
                value=p.get("value", ""),
                weight=p.get("weight", 1.0),
                description=p.get("description", ""),
            )
            for p in d.get("detect_patterns", [])
        ]
        attribute_mappings = [
            AttributeMapping(
                attribute=m.get("attribute", ""),
                semantic=m.get("semantic", ""),
                priority_boost=m.get("priority_boost", 0.0),
            )
            for m in d.get("attribute_mappings", [])
        ]
        return ComponentLibraryProfile(
            name=d.get("name", ""),
            display_name=d.get("display_name", ""),
            version=d.get("version", ""),
            detect_patterns=detect_patterns,
            locator_priorities=d.get("locator_priorities", [
                "data-testid", "aria-label", "role+name", "css_stable", "text"
            ]),
            attribute_mappings=attribute_mappings,
            stable_class_regex=d.get("stable_class_regex", []),
            ignore_class_regex=d.get("ignore_class_regex", []),
            shadow_dom=d.get("shadow_dom", False),
            nested_structure=d.get("nested_structure", "standard"),
            confidence_modifier=d.get("confidence_modifier", 1.0),
        )
