"""五层递进规则引擎 + AI兜底。L1缓存→L2语义→L3动态过滤→L4拓扑→L5穿透，规则优先省token，全挂了再调AI。"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from playwright.sync_api import Page, Browser, BrowserContext

from self_healing.cache_matcher import L1CacheMatcher, SelectorCache
from self_healing.semantic_generator import L2SemanticGenerator
from self_healing.dynamic_filter_matcher import L3DynamicFilterMatcher
from self_healing.topology_matcher import L4TopologyMatcher
from self_healing.iframe_shadow_patcher import L5IframeShadowPatcher
from self_healing.ai_healer import AIHealer
from self_healing.candidate_evaluator import CandidateEvaluator, HealingCandidate
from self_healing.selector_parser import parse_selector

logger = logging.getLogger(__name__)


@dataclass
class HealingResult:
    """自愈结果

    Attributes:
        success: 是否成功修复
        original_selector: 原始失效选择器
        healed_selector: 修复后的选择器
        confidence: 置信度得分 [0, 1]
        source_level: 修复来源层级 (1-6, 6=AI)
        strategy_name: 策略名称
        page_url: 页面 URL
        verified: 是否已验证可用
        all_candidates: 所有候选列表
    """
    success: bool = False
    original_selector: str = ""
    healed_selector: str = ""
    confidence: float = 0.0
    source_level: int = 0
    strategy_name: str = ""
    page_url: str = ""
    verified: bool = False
    all_candidates: list[HealingCandidate] = field(default_factory=list)


class HealingPipeline:
    """五层递进式自愈管线

    调度逻辑：
    L1 历史缓存 → L2 语义定位 → L3 动态过滤 → L4 拓扑匹配 → L5 iframe穿透
    全部失败 → AI 兜底

    每层结果经过 CandidateEvaluator 评分，取最优候选。
    """

    def __init__(self, page: Page, cache_dir: Optional[str] = None):
        self._page = page
        cache_dir = cache_dir or os.environ.get("HEAL_CACHE_DIR", "output/heal_cache")
        self._cache = SelectorCache(cache_dir)
        self._evaluator = CandidateEvaluator()

        self._l1 = L1CacheMatcher(self._cache)
        self._l2 = L2SemanticGenerator(page)
        self._l3 = L3DynamicFilterMatcher(page)
        self._l4 = L4TopologyMatcher(page)
        self._l5 = L5IframeShadowPatcher(page)
        self._ai = AIHealer(page)

        self._apply_component_profiles()

    def _apply_component_profiles(self) -> None:
        # 延迟导入，避免循环依赖
        try:
            self._l2.apply_component_profiles()
            self._l3.apply_component_profiles()
            # L4 根据组件库类型调整权重
            from self_healing.component_manager import ComponentLibraryManager
            manager = ComponentLibraryManager()
            all_profiles = manager.list_profiles()
            if all_profiles:
                # 使用第一个档案的 nested_structure 调整 L4 权重
                nested = all_profiles[0].nested_structure
                self._l4.apply_component_profiles(nested)
        except Exception as e:
            logger.warning(f"组件库档案注入失败: {e}")

    def heal(self, selector: str, action: str = "click", page_url: str = "", error_message: str = "") -> HealingResult:
        """执行五层递进式自愈

        依次尝试 L1→L2→L3→L4→L5，每层产生候选，
        全部候选经评估器排序后取最优。
        若最优达到运行时标准（≥0.6）则返回；
        否则触发 AI 兜底。

        Args:
            selector: 原始失效选择器
            action: 失败的操作类型
            page_url: 页面 URL

        Returns:
            HealingResult
        """
        result = HealingResult(
            original_selector=selector,
            page_url=page_url,
        )

        candidates: list[HealingCandidate] = []

        # L0: Strict Violation 修复路径
        if error_message:
            from self_healing.strict_violation_healer import StrictViolationHealer
            l0 = StrictViolationHealer()
            if l0.is_strict_violation(error_message):
                logger.info(f"[L0] 检测到 strict mode violation，启动智能修复（DOM 验证 + 业务上下文感知）")
                # 传递 page 对象，启用 DOM 验证和智能评分
                l0_candidates = l0.heal(selector, error_message, page_url, page=self._page)
                if l0_candidates:
                    candidates.extend(l0_candidates)
                    # L0 候选直接进入评估，不走后续五层
                    result.all_candidates = self._evaluator.rank_candidates(candidates)
                    best = result.all_candidates[0]
                    if self._evaluator.is_acceptable_for_runtime(best):
                        result.success = True
                        result.healed_selector = best.selector
                        result.confidence = best.confidence
                        result.source_level = best.source_level
                        result.strategy_name = best.strategy_name
                        result.verified = best.verified
                        if self._evaluator.is_acceptable_for_permanent(best):
                            self._cache.store(selector, best.selector, page_url, best.confidence)
                            logger.info(f"[L0固化] strict violation 修复已缓存: {selector} → {best.selector}")
                        return result
                    # L0 候选置信度不足，继续走五层
                    logger.info(f"[L0] 候选置信度不足，继续执行五层引擎")

        # L1: 历史缓存优先匹配
        logger.info(f"[L1] 尝试历史缓存匹配: {selector}")
        l1_result = self._l1.heal(selector, page_url)
        if l1_result:
            healed_sel, confidence = l1_result
            candidates.append(HealingCandidate(
                selector=healed_sel,
                confidence=confidence,
                source_level=1,
                strategy_name="cache",
                base_score=confidence,
                strategy_weight=1.10,
            ))

        # L2: 语义定位自动生成
        logger.info(f"[L2] 尝试语义定位生成: {selector}")
        l2_result = self._l2.heal(selector, page_url)
        if l2_result:
            healed_sel, confidence = l2_result
            candidates.append(HealingCandidate(
                selector=healed_sel,
                confidence=confidence,
                source_level=2,
                strategy_name="semantic",
                base_score=confidence,
            ))

        # L3: 动态属性过滤模糊匹配
        logger.info(f"[L3] 尝试动态属性过滤: {selector}")
        l3_result = self._l3.heal(selector, page_url)
        if l3_result:
            healed_sel, confidence = l3_result
            candidates.append(HealingCandidate(
                selector=healed_sel,
                confidence=confidence,
                source_level=3,
                strategy_name="dynamic_filter",
                base_score=confidence,
            ))

        # L4: DOM 拓扑相似度匹配
        logger.info(f"[L4] 尝试DOM拓扑匹配: {selector}")
        l4_result = self._l4.heal(selector, page_url)
        if l4_result:
            healed_sel, confidence = l4_result
            candidates.append(HealingCandidate(
                selector=healed_sel,
                confidence=confidence,
                source_level=4,
                strategy_name="topology",
                base_score=confidence,
            ))

        # L5: iframe/ShadowDOM 自动穿透修复
        logger.info(f"[L5] 尝试iframe/Shadow穿透: {selector}")
        l5_result = self._l5.heal(selector, page_url)
        if l5_result:
            healed_sel, confidence = l5_result
            candidates.append(HealingCandidate(
                selector=healed_sel,
                confidence=confidence,
                source_level=5,
                strategy_name="iframe_shadow",
                base_score=confidence,
            ))

        if candidates:
            result.all_candidates = self._evaluator.rank_candidates(candidates)
            best = result.all_candidates[0]

            # 检查是否达到运行时临时自愈标准（≥0.6）
            if self._evaluator.is_acceptable_for_runtime(best):
                result.success = True
                result.healed_selector = best.selector
                result.confidence = best.confidence
                result.source_level = best.source_level
                result.strategy_name = best.strategy_name
                result.verified = best.verified

                # 如果达标永久固化（≥0.75），记录到缓存
                if self._evaluator.is_acceptable_for_permanent(best):
                    self._cache.store(selector, best.selector, page_url, best.confidence)
                    logger.info(
                        f"[固化] 修复方案已缓存: {selector} → {best.selector} "
                        f"(置信度: {best.confidence:.2f})"
                    )

                return result

        # 五层全部失败，触发 AI 兜底
        logger.info("[AI] 规则引擎全挂，上AI")
        ai_candidate = self._ai.heal(selector, action, page_url)
        if ai_candidate:
            evaluated = self._evaluator.evaluate(ai_candidate)
            if self._evaluator.is_acceptable_for_runtime(evaluated):
                result.success = True
                result.healed_selector = evaluated.selector
                result.confidence = evaluated.confidence
                result.source_level = 6
                result.strategy_name = "ai"
                result.verified = evaluated.verified
                result.all_candidates = candidates + [evaluated]

                if self._evaluator.is_acceptable_for_permanent(evaluated):
                    self._cache.store(selector, evaluated.selector, page_url, evaluated.confidence)

                return result
            else:
                # AI 返回结果置信度不足，标记缓存失败
                self._cache.mark_failed(selector, page_url)

        # 全部失败
        logger.warning(f"[失败] 所有自愈策略均未成功: {selector}")
        result.all_candidates = candidates
        return result


def create_pipeline_from_browser(
    browser: Browser,
    page_url: str,
    cache_dir: Optional[str] = None,
) -> tuple[HealingPipeline, Page]:
    """从浏览器实例创建管线和页面，导航到指定URL"""
    context: BrowserContext = browser.new_context()
    page: Page = context.new_page()
    if page_url:
        page.goto(page_url, wait_until="domcontentloaded", timeout=15000)
    pipeline = HealingPipeline(page, cache_dir)
    return pipeline, page
