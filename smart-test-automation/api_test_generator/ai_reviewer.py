# -*- coding: utf-8 -*-
"""AI 兜底审查器

规则引擎初步分析完参数传递链后，把 UI 操作序列 + API 调用 + 初步链发给 AI，
让 AI 做一次二次校验：
1. 去掉误报（值碰巧相同但实际无关）
2. 补漏（规则没匹配到但语义上有关联的）
3. 校验链路合理性（参数传递方向是否正确）
"""

import json
import logging
from typing import List, Optional

from .models import UIOperation, ParamChain

logger = logging.getLogger(__name__)


class ParamChainReviewer:
    """用 AI 对规则引擎产出的参数传递链做二次校验"""

    def __init__(self):
        self._provider = None

    def _get_provider(self):
        """延迟加载 AI provider"""
        if self._provider is None:
            try:
                import os
                from config.env_loader import load_env
                load_env()  # 确保 .env 已加载
                from ai.provider import OpenAICompatibleProvider
                model = os.environ.get("AI_MODEL", "glm-5.1")
                self._provider = OpenAICompatibleProvider(model_id=model)
            except Exception as e:
                logger.warning("AI provider 加载失败: %s，跳过 AI 审查", e)
                return None
        return self._provider

    def review(
        self,
        operations: List[UIOperation],
        api_calls: list,
        initial_chains: List[ParamChain],
    ) -> List[ParamChain]:
        """AI 审查参数传递链

        Args:
            operations: UI 操作列表
            api_calls: API 调用列表（APICall 对象）
            initial_chains: 规则引擎初步分析的参数传递链

        Returns:
            List[ParamChain]: AI 审查后的参数传递链
        """
        provider = self._get_provider()
        if not provider:
            logger.info("AI 不可用，返回规则引擎结果")
            return initial_chains

        try:
            prompt = self._build_review_prompt(operations, api_calls, initial_chains)
            response = provider._call_api(prompt, temperature=0.1)
            reviewed_chains = self._parse_ai_response(response, initial_chains)
            logger.info("AI 审查完成: %d → %d 条链", len(initial_chains), len(reviewed_chains))
            return reviewed_chains
        except Exception as e:
            logger.warning("AI 审查失败: %s，返回规则引擎结果", e)
            return initial_chains

    def _build_review_prompt(
        self,
        operations: List[UIOperation],
        api_calls: list,
        initial_chains: List[ParamChain],
    ) -> str:
        """构建审查提示词"""
        prompt = """你是一个接口自动化测试专家。请审查以下 UI 操作→API 调用的参数传递链分析结果。

## 任务
1. 去掉误报：如果参数传递链的源和目标实际上没有业务关联（只是值碰巧相同），标记为 `remove`
2. 补漏：如果有遗漏的参数传递关系（规则引擎没检测到），标记为 `add`
3. 校验方向：确保参数传递方向是 响应→请求（而不是反向）

## 输出格式（JSON）
```json
{
  "remove": [
    {"source_api": "...", "source_field": "...", "target_api": "...", "target_field": "...", "reason": "为什么去掉"}
  ],
  "add": [
    {"source_api": "...", "source_field": "...", "target_api": "...", "target_field": "...", "confidence": 0.8, "reason": "为什么加上"}
  ],
  "keep": [
    {"source_api": "...", "source_field": "...", "target_api": "...", "target_field": "...", "reason": "为什么保留"}
  ]
}
```

## UI 操作序列
"""
        for i, op in enumerate(operations[:30]):  # 限制数量避免 prompt 过长
            name = op.selector_name or op.selector_value or ""
            value = f" = {op.value[:30]}" if op.value else ""
            prompt += f"{i+1}. [{op.action}] {name}{value}\n"

        prompt += "\n## API 调用序列\n"
        for i, api in enumerate(api_calls[:50]):
            has_resp = "有响应" if api.response_body else "无响应"
            has_req = "有请求体" if api.request_body else "无请求体"
            prompt += f"{i+1}. {api.method} {api.path} (status={api.status}, {has_resp}, {has_req})\n"

        prompt += "\n## 规则引擎初步分析的参数传递链\n"
        if not initial_chains:
            prompt += "(无传递链)\n"
        else:
            for i, chain in enumerate(initial_chains[:30]):
                prompt += (
                    f"{i+1}. {chain.source_api}#{chain.source_field} "
                    f"→ {chain.target_api}#{chain.target_field} "
                    f"(confidence={chain.confidence}, type={chain.chain_type})\n"
                )

        prompt += "\n请只输出 JSON，不要其他文字。"
        return prompt

    def _parse_ai_response(
        self,
        response: str,
        initial_chains: List[ParamChain],
    ) -> List[ParamChain]:
        """解析 AI 响应，生成最终的参数传递链"""
        # 尝试提取 JSON
        response = response.strip()
        # 去掉可能的 markdown 代码块标记
        if response.startswith("```"):
            lines = response.split("\n")
            response = "\n".join(lines[1:-1])
        if response.startswith("```json"):
            response = response[7:]
        if response.endswith("```"):
            response = response[:-3]

        try:
            result = json.loads(response.strip())
        except json.JSONDecodeError:
            logger.warning("AI 响应 JSON 解析失败，返回原始链")
            return initial_chains

        # 建立初始链的索引
        chain_index = {}
        for chain in initial_chains:
            key = f"{chain.source_api}#{chain.source_field}→{chain.target_api}#{chain.target_field}"
            chain_index[key] = chain

        # 处理 remove
        removed_keys = set()
        for item in result.get("remove", []):
            key = f"{item['source_api']}#{item['source_field']}→{item['target_api']}#{item['target_field']}"
            removed_keys.add(key)
            logger.info("AI 去除: %s (原因: %s)", key, item.get("reason", ""))

        # 处理 keep（提高置信度）
        kept_keys = set()
        for item in result.get("keep", []):
            key = f"{item['source_api']}#{item['source_field']}→{item['target_api']}#{item['target_field']}"
            kept_keys.add(key)
            if key in chain_index:
                chain_index[key].confidence = min(chain_index[key].confidence + 0.1, 1.0)

        # 处理 add
        added_chains = []
        for item in result.get("add", []):
            chain = ParamChain(
                source_api=item["source_api"],
                source_field=item["source_field"],
                source_example="",
                target_api=item["target_api"],
                target_field=item["target_field"],
                chain_type="ai_inferred",
                confidence=item.get("confidence", 0.7),
            )
            added_chains.append(chain)
            logger.info("AI 补充: %s#%s → %s#%s",
                       chain.source_api, chain.source_field,
                       chain.target_api, chain.target_field)

        # 合并结果
        final_chains = [
            chain for key, chain in chain_index.items()
            if key not in removed_keys
        ]
        final_chains.extend(added_chains)
        final_chains.sort(key=lambda c: c.confidence, reverse=True)

        return final_chains
