# -*- coding: utf-8 -*-
"""操作↔API 时间线映射

核心挑战：HAR 录制的是整个会话的网络流量，没有"哪个操作触发哪个API"的标记。
时间戳也不可靠（浏览器并发请求，所有API可能挤在几秒内）。

解决方案：操作类型 + HAR 顺序的混合策略
1. 把 UI 操作分为"触发类"（navigate/click）和"输入类"（fill/press/check）
2. 触发类操作按顺序从 HAR 中"切"出一批 API
3. 输入类操作不切 API，归入它后面的触发操作
4. 切分比例参考时间戳间隔（有大间隔的位置优先切分）
"""

from datetime import datetime
from typing import List, Optional

from recorder.har_parser import APICall
from .models import UIOperation, TimelineMapping


class TimelineMapper:
    """把 UI 操作和 API 调用关联起来"""

    # 触发类操作（可能产生 API 调用）
    TRIGGER_ACTIONS = {"navigate", "click", "select", "goto", "submit", "reload"}
    # 输入类操作（通常不产生 API 调用）
    INPUT_ACTIONS = {"fill", "press", "check", "uncheck", "type", "clear", "hover"}

    def map_operations_to_apis(
        self,
        operations: List[UIOperation],
        api_calls: List[APICall],
    ) -> List[TimelineMapping]:
        """把 UI 操作和 API 调用关联起来

        策略：
        1. 找出所有触发类操作的索引
        2. 用时间戳间隔在 HAR 中找"切分点"
        3. 按切分点把 API 分配给触发操作
        4. 输入类操作归入它后面的触发操作

        Args:
            operations: UI 操作列表
            api_calls: API 调用列表（按时间顺序）

        Returns:
            List[TimelineMapping]
        """
        if not operations:
            return []
        if not api_calls:
            return [
                TimelineMapping(ui_operation=op, api_calls=[], confidence=0.3)
                for op in operations
            ]

        # 1. 找出触发操作
        trigger_indices = [
            i for i, op in enumerate(operations)
            if op.action.lower() in self.TRIGGER_ACTIONS
        ]

        if not trigger_indices:
            # 没有触发操作，所有 API 分给第一个操作
            return self._fallback_single(operations, api_calls)

        # 2. 用时间戳间隔找切分点
        split_points = self._find_split_points(api_calls, len(trigger_indices))

        # 3. 按切分点分配 API
        api_bursts = self._split_apis(api_calls, split_points)

        # 4. 构建映射
        return self._build_mappings(operations, trigger_indices, api_bursts)

    def _find_split_points(
        self,
        api_calls: List[APICall],
        num_triggers: int,
    ) -> List[int]:
        """在 HAR 中找切分点

        找时间戳间隔最大的 N-1 个位置作为切分点。
        如果时间戳不可用，用均匀分配。

        Args:
            api_calls: API 调用列表
            num_triggers: 触发操作数量

        Returns:
            List[int]: 切分点索引列表（不含首尾）
        """
        if num_triggers <= 1:
            return []

        # 计算相邻 API 的时间间隔
        gaps = []
        for i in range(1, len(api_calls)):
            prev_ts = self._parse_timestamp(api_calls[i - 1].timestamp)
            curr_ts = self._parse_timestamp(api_calls[i].timestamp)
            if prev_ts and curr_ts:
                gap = (curr_ts - prev_ts).total_seconds()
            else:
                gap = 0
            gaps.append((i, gap))

        if not gaps:
            # 没有时间戳，均匀分配
            step = len(api_calls) // num_triggers
            return [step * i for i in range(1, num_triggers)]

        # 找间隔最大的 N-1 个位置
        sorted_gaps = sorted(gaps, key=lambda x: x[1], reverse=True)
        split_points = sorted([idx for idx, _ in sorted_gaps[:num_triggers - 1]])

        return split_points

    def _split_apis(
        self,
        api_calls: List[APICall],
        split_points: List[int],
    ) -> List[List[APICall]]:
        """按切分点把 API 分成多组"""
        if not split_points:
            return [api_calls]

        bursts = []
        start = 0
        for point in split_points:
            bursts.append(api_calls[start:point])
            start = point
        bursts.append(api_calls[start:])

        return bursts

    def _build_mappings(
        self,
        operations: List[UIOperation],
        trigger_indices: List[int],
        api_bursts: List[List[APICall]],
    ) -> List[TimelineMapping]:
        """构建最终的映射结果"""
        mappings = []

        for i, op in enumerate(operations):
            if i in trigger_indices:
                # 触发操作：分配对应的 API burst
                burst_idx = trigger_indices.index(i)
                if burst_idx < len(api_bursts):
                    apis = api_bursts[burst_idx]
                else:
                    apis = []
                mappings.append(TimelineMapping(
                    ui_operation=op,
                    api_calls=apis,
                    confidence=0.9 if apis else 0.3,
                ))
            elif op.action.lower() in self.INPUT_ACTIONS:
                # 输入操作：不分配 API
                mappings.append(TimelineMapping(
                    ui_operation=op,
                    api_calls=[],
                    confidence=0.7,
                ))
            else:
                # 其他操作：不分配 API
                mappings.append(TimelineMapping(
                    ui_operation=op,
                    api_calls=[],
                    confidence=0.3,
                ))

        return mappings

    def _fallback_single(
        self,
        operations: List[UIOperation],
        api_calls: List[APICall],
    ) -> List[TimelineMapping]:
        """没有触发操作时的回退方案：所有 API 分给第一个操作"""
        mappings = []
        for i, op in enumerate(operations):
            if i == 0:
                mappings.append(TimelineMapping(
                    ui_operation=op,
                    api_calls=api_calls,
                    confidence=0.5,
                ))
            else:
                mappings.append(TimelineMapping(
                    ui_operation=op,
                    api_calls=[],
                    confidence=0.3,
                ))
        return mappings

    def _parse_timestamp(self, timestamp: str) -> Optional[datetime]:
        """解析 ISO 格式时间戳"""
        if not timestamp:
            return None
        try:
            ts = timestamp.replace("Z", "+00:00")
            return datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            return None
