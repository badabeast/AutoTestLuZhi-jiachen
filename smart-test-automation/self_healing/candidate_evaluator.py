"""多候选竞争评估器

独创性：
1. 自研置信度打分公式：confidence = base_score × strategy_weight × context_bonus × profile_modifier
2. 只有得分 ≥ 阈值（默认0.75）的候选才允许回写到源码
3. 区分「临时自愈」（≥0.6 可运行）和「源码固化」（≥0.75 才回写）
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class HealingCandidate:
    """修复候选"""
    selector: str                # 修复后的选择器
    confidence: float            # 置信度得分 [0, 1]
    source_level: int            # 来源层级 (1-5 = L1-L5, 6 = AI)
    strategy_name: str           # 策略名称
    verified: bool = False       # 是否已验证可用
    page_url: str = ""           # 来源页面

    # 评估辅助字段
    base_score: float = 0.0      # 基础分（来自引擎）
    strategy_weight: float = 1.0 # 策略权重
    context_bonus: float = 1.0   # 上下文加成
    profile_modifier: float = 1.0 # 组件库档案修正


class CandidateEvaluator:
    """多候选竞争评估器

    使用自研置信度打分公式对多个修复候选进行排序和筛选。
    """

    # 策略权重配置
    STRATEGY_WEIGHTS: dict[str, float] = {
        "strict_narrow": 1.15,  # L0 Strict Violation 收窄 — 最精确
        "cache": 1.10,          # 历史缓存最可信
        "semantic": 1.00,       # 语义定位标准权重
        "dynamic_filter": 0.95, # 动态过滤略低
        "topology": 0.90,       # 拓扑匹配更低
        "iframe_shadow": 0.85,  # iframe穿透有风险
        "ai": 0.80,             # AI兜底最低
    }

    def __init__(self, threshold: float = 0.75):
        self._threshold = threshold

        # 从环境变量读取
        env_threshold = os.environ.get("HEAL_CONFIDENCE_THRESHOLD")
        if env_threshold:
            try:
                self._threshold = float(env_threshold)
            except ValueError:
                pass

    @property
    def threshold(self) -> float:
        """获取当前置信度阈值"""
        return self._threshold

    def evaluate(self, candidate: HealingCandidate) -> HealingCandidate:
        """计算最终置信度

        公式：confidence = base_score × strategy_weight × context_bonus × profile_modifier
        结果钳制到 [0, 1] 范围。

        Args:
            candidate: 待评估的修复候选

        Returns:
            评估后的候选（confidence 已更新）
        """
        weight = self.STRATEGY_WEIGHTS.get(candidate.strategy_name, 0.90)
        final_score = (
            candidate.base_score
            * weight
            * candidate.context_bonus
            * candidate.profile_modifier
        )
        # 钳制到 [0, 1]
        candidate.confidence = max(0.0, min(1.0, final_score))
        return candidate

    def is_acceptable_for_permanent(self, candidate: HealingCandidate) -> bool:
        """是否达到源码永久固化标准

        只有置信度 ≥ 阈值（默认0.75）的候选才允许回写到源码文件。

        Args:
            candidate: 已评估的修复候选

        Returns:
            True 表示达到永久固化标准
        """
        return candidate.confidence >= self._threshold

    def is_acceptable_for_runtime(self, candidate: HealingCandidate) -> bool:
        """是否达到运行时临时自愈标准

        置信度 ≥ 0.6 的候选可以在运行时临时使用（但不回写源码）。

        Args:
            candidate: 已评估的修复候选

        Returns:
            True 表示达到运行时自愈标准
        """
        return candidate.confidence >= 0.6

    def rank_candidates(self, candidates: list[HealingCandidate]) -> list[HealingCandidate]:
        """排序候选列表

        对所有候选执行评估并按置信度降序排列。

        Args:
            candidates: 待排序的候选列表

        Returns:
            评估后按置信度降序排列的候选列表
        """
        evaluated = [self.evaluate(c) for c in candidates]
        return sorted(evaluated, key=lambda c: -c.confidence)

    def best_candidate(self, candidates: list[HealingCandidate]) -> Optional[HealingCandidate]:
        """返回最优候选

        Args:
            candidates: 候选列表

        Returns:
            置信度最高的候选，列表为空则返回 None
        """
        ranked = self.rank_candidates(candidates)
        return ranked[0] if ranked else None
