"""自愈机制模块

v4 导出清单:
  - healer_config: healer 配置加载
  - selector_parser: 链式选择器解析器
  - component_profile: 组件库配置档案数据结构
  - component_detector: 组件库自动识别器
  - component_manager: 组件库档案管理器
  - cache_matcher: L1 历史缓存优先匹配
  - semantic_generator: L2 语义定位自动生成
  - dynamic_filter_matcher: L3 动态属性过滤模糊匹配
  - topology_matcher: L4 DOM 拓扑相似度匹配
  - iframe_shadow_patcher: L5 iframe/ShadowDOM 自动穿透修复
  - dom_trimmer: 局部 DOM 裁剪 AI 优化模块
  - candidate_evaluator: 多候选竞争评估
  - ai_healer: AI 兜底修复引擎
  - pipeline: 五层递进式自愈管线
"""
from __future__ import annotations

from .healer_config import get_healer_config, get_healer_env_vars, load_env
from .selector_parser import parse_selector, SelectorExpr, MethodCall
from .component_profile import (
    ComponentLibraryProfile,
    DetectPattern,
    DetectPatternType,
    AttributeMapping,
)
from .component_detector import ComponentLibraryDetector
from .component_manager import ComponentLibraryManager
from .cache_matcher import L1CacheMatcher, SelectorCache, CacheEntry
from .semantic_generator import L2SemanticGenerator
from .dynamic_filter_matcher import L3DynamicFilterMatcher
from .topology_matcher import L4TopologyMatcher
from .iframe_shadow_patcher import L5IframeShadowPatcher
from .dom_trimmer import DOMTrimmer
from .candidate_evaluator import CandidateEvaluator, HealingCandidate
from .ai_healer import AIHealer
from .pipeline import HealingPipeline, HealingResult, create_pipeline_from_browser
from .source_patcher import SourcePatcher
from .strict_violation_healer import StrictViolationHealer

__all__ = [
    "get_healer_config",
    "get_healer_env_vars",
    "load_env",
    "parse_selector",
    "SelectorExpr",
    "MethodCall",
    "ComponentLibraryProfile",
    "DetectPattern",
    "DetectPatternType",
    "AttributeMapping",
    "ComponentLibraryDetector",
    "ComponentLibraryManager",
    "L1CacheMatcher",
    "SelectorCache",
    "CacheEntry",
    "L2SemanticGenerator",
    "L3DynamicFilterMatcher",
    "L4TopologyMatcher",
    "L5IframeShadowPatcher",
    "DOMTrimmer",
    "CandidateEvaluator",
    "HealingCandidate",
    "AIHealer",
    "HealingPipeline",
    "HealingResult",
    "create_pipeline_from_browser",
    "SourcePatcher",
    "StrictViolationHealer",
]
