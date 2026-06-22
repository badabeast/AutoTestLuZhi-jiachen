# -*- coding: utf-8 -*-
"""增量维护机制 - 对比新旧API调用，增量更新测试脚本"""

import re
from typing import List, Tuple

from recorder.har_parser import APICall
from .models import ParamChain, IncrementalDiff


class IncrementalMaintainer:
    """增量维护：再录制同一模块时，diff变化，只更新差异部分"""

    def compare_api_calls(
        self,
        old_calls: List[APICall],
        new_calls: List[APICall],
    ) -> IncrementalDiff:
        """对比新旧API调用序列

        用 method + path 做匹配：
        - 新有旧无 → added
        - 旧有新无 → removed
        - 都有但内容不同 → modified

        Args:
            old_calls: 旧的API调用列表
            new_calls: 新的API调用列表

        Returns:
            IncrementalDiff
        """
        old_index = {}
        for call in old_calls:
            key = f"{call.method} {call.path}"
            old_index[key] = call

        new_index = {}
        for call in new_calls:
            key = f"{call.method} {call.path}"
            new_index[key] = call

        old_keys = set(old_index.keys())
        new_keys = set(new_index.keys())

        added = [new_index[k] for k in (new_keys - old_keys)]
        removed = [old_index[k] for k in (old_keys - new_keys)]

        modified: List[Tuple[APICall, APICall]] = []
        for k in (old_keys & new_keys):
            old_call = old_index[k]
            new_call = new_index[k]
            if self._calls_differ(old_call, new_call):
                modified.append((old_call, new_call))

        return IncrementalDiff(
            added_apis=added,
            removed_apis=removed,
            modified_apis=modified,
            updated_chains=[],
        )

    def update_test_script(
        self,
        old_script: str,
        diff: IncrementalDiff,
    ) -> str:
        """在旧脚本基础上追加/删除步骤

        对于新增的API调用，在脚本末尾追加新的测试步骤。
        对于删除的API调用，注释掉对应的测试步骤。

        Args:
            old_script: 旧的测试脚本内容
            diff: 增量差异

        Returns:
            str: 更新后的脚本
        """
        if not diff.added_apis and not diff.removed_apis:
            return old_script

        lines = old_script.split('\n')

        # 处理删除：找到对应的测试步骤并注释掉
        for removed in diff.removed_apis:
            pattern = f"{removed.method} {removed.path}"
            lines = self._comment_out_step(lines, pattern)

        # 处理追加：在脚本末尾（最后一个 assert 之后）插入新步骤
        if diff.added_apis:
            insert_idx = self._find_insert_point(lines)
            new_lines = self._render_new_steps(diff.added_apis, len(lines))
            lines = lines[:insert_idx] + new_lines + lines[insert_idx:]

        return '\n'.join(lines)

    def update_chains(
        self,
        old_chains: List[ParamChain],
        new_chains: List[ParamChain],
    ) -> List[ParamChain]:
        """合并新旧参数传递链

        - 旧有新无 → 保留但降低置信度
        - 新有旧无 → 追加
        - 都有 → 取置信度更高的

        Args:
            old_chains: 旧的参数传递链
            new_chains: 新的参数传递链

        Returns:
            List[ParamChain]: 合并后的参数传递链
        """
        old_index = {}
        for chain in old_chains:
            key = f"{chain.target_api}#{chain.target_field}"
            old_index[key] = chain

        new_index = {}
        for chain in new_chains:
            key = f"{chain.target_api}#{chain.target_field}"
            new_index[key] = chain

        merged: List[ParamChain] = []

        for key, old_chain in old_index.items():
            if key in new_index:
                new_chain = new_index[key]
                # 取置信度更高的
                merged.append(new_chain if new_chain.confidence >= old_chain.confidence else old_chain)
            else:
                # 旧有新无，降低置信度保留
                old_chain.confidence = max(old_chain.confidence * 0.5, 0.1)
                merged.append(old_chain)

        for key, new_chain in new_index.items():
            if key not in old_index:
                merged.append(new_chain)

        merged.sort(key=lambda c: c.confidence, reverse=True)
        return merged

    def _calls_differ(self, old: APICall, new: APICall) -> bool:
        """判断两个API调用是否不同"""
        # 状态码不同
        if old.status != new.status:
            return True
        # 请求体不同
        if old.request_body != new.request_body:
            return True
        return False

    def _comment_out_step(self, lines: List[str], pattern: str) -> List[str]:
        """注释掉包含指定pattern的测试步骤"""
        result = []
        in_step = False
        for line in lines:
            if pattern in line and line.strip().startswith('#'):
                in_step = True
                result.append('    # [REMOVED] ' + line.strip())
                continue
            if in_step:
                if line.strip() and not line.startswith('    '):
                    in_step = False
                    result.append(line)
                else:
                    result.append('    # ' + line.strip() if line.strip() else line)
            else:
                result.append(line)
        return result

    def _find_insert_point(self, lines: List[str]) -> int:
        """找到插入新步骤的位置（最后一个assert行之后）"""
        last_assert_idx = len(lines) - 1
        for i in range(len(lines) - 1, -1, -1):
            if 'assert' in lines[i] and 'status_code' in lines[i]:
                last_assert_idx = i + 1
                break
        return last_assert_idx

    def _render_new_steps(self, new_apis: List[APICall], start_index: int) -> List[str]:
        """渲染新增的测试步骤"""
        lines = ['', '    # === 新增步骤（增量更新） ===', '']

        for i, api in enumerate(new_apis):
            step_num = start_index + i
            lines.append(f'    # Step {step_num}: {api.method} {api.path}')
            var = f"resp_new_{i}"

            if api.method == "GET":
                lines.append(f'    {var} = api.get(f"{{BASE_URL}}{api.path}")')
            elif api.method == "POST":
                lines.append(f'    {var} = api.post(f"{{BASE_URL}}{api.path}")')
            elif api.method == "PUT":
                lines.append(f'    {var} = api.put(f"{{BASE_URL}}{api.path}")')
            elif api.method == "DELETE":
                lines.append(f'    {var} = api.delete(f"{{BASE_URL}}{api.path}")')
            else:
                lines.append(f'    {var} = api.request("{api.method}", f"{{BASE_URL}}{api.path}")')

            lines.append(f'    assert {var}.status_code == {api.status}')
            lines.append('')

        return lines
