#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 依赖分析器

功能: 使用 AI 分析 API 请求序列中的数据依赖关系
增强: 集成前端知识文档作为 AI 上下文，提升推断准确率
"""

import os
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

from .provider import OpenAICompatibleProvider, create_ai_provider, MODEL_REGISTRY


class AIDependencyAnalyzer:
    """AI 依赖分析器

    分析 API 请求序列中的数据依赖关系，例如:
    - 前一个接口返回的 ID 被后一个接口使用
    - 请求之间的字段映射关系

    增强模式: 如果 knowledge/frontend_docs/ 中有前端沉淀文档，
    会自动注入到 AI prompt 中，大幅提升推断准确率。

    用法::

        analyzer = AIDependencyAnalyzer()  # 默认 GLM-5.1
        deps = analyzer.analyze_dependencies(recordings)
    """

    def __init__(
        self,
        ai_provider: str = "glm-5.1",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.model_id = ai_provider
        self.provider = create_ai_provider(
            provider_type=ai_provider,
            model_id=model,
            api_key=api_key,
        )
        # 延迟加载前端知识（避免循环导入）
        self._frontend_context: Optional[str] = None

    def analyze_dependencies(self, recordings: List[Dict]) -> List[Dict]:
        """使用 AI 分析数据依赖关系"""
        if not recordings:
            return []

        prompt = self._build_analysis_prompt(recordings)

        try:
            print(f"   调用 {self.model_id} API 分析依赖...")
            response = self.provider._call_api(prompt)
            return self._parse_ai_response(response, recordings)
        except Exception as e:
            print(f"⚠️ AI分析失败: {e}")
            print("   使用规则推导作为备选方案")
            return self._rule_based_analysis(recordings)

    def _get_frontend_context(self) -> str:
        """获取前端知识上下文（延迟加载）"""
        if self._frontend_context is None:
            try:
                from knowledge.frontend_loader import FrontendKnowledgeLoader
                loader = FrontendKnowledgeLoader()
                self._frontend_context = loader.build_ai_context(max_chars=6000)
                if self._frontend_context:
                    print(f"   📚 已加载前端知识文档作为分析上下文")
            except Exception as e:
                print(f"   ⚠️ 加载前端知识失败: {e}")
                self._frontend_context = ""
        return self._frontend_context

    def _build_analysis_prompt(self, recordings: List[Dict]) -> str:
        """构建分析提示词（含前端知识增强）"""
        prompt = "分析以下API请求序列，找出数据依赖关系。\n\n"
        prompt += "前一个接口返回的ID被后一个接口使用即为依赖关系。\n\n"

        # 注入前端知识上下文（如果有）
        frontend_ctx = self._get_frontend_context()
        if frontend_ctx:
            prompt += "---\n"
            prompt += "以下是前端开发团队提供的接口依赖和业务逻辑文档，请优先参考：\n\n"
            prompt += frontend_ctx
            prompt += "\n---\n\n"

        for req in recordings:
            prompt += f"S{req['sequence']}: {req['method']} {req['path']}\n"
            if req.get("request_body"):
                body_str = json.dumps(req["request_body"], ensure_ascii=False)[:200]
                prompt += f"  请求: {body_str}\n"
            if req.get("response_body"):
                resp_str = json.dumps(req["response_body"], ensure_ascii=False)[:200]
                prompt += f"  响应: {resp_str}\n"
            prompt += "\n"

        prompt += (
            '返回JSON数组：\n'
            '[{"from_seq":1,"from_field":"id","to_seq":3,'
            '"to_field":"parentId","confidence":0.95}]\n'
            "直接返回JSON："
        )
        return prompt

    def _parse_ai_response(
        self, response: str, recordings: List[Dict]
    ) -> List[Dict]:
        """解析 AI 响应"""
        try:
            json_match = re.search(r"\[.*\]", response, re.DOTALL)
            if json_match:
                deps = json.loads(json_match.group())
                validated: List[Dict] = []
                for dep in deps:
                    from_seq = dep.get("from_seq") or dep.get("from_sequence")
                    to_seq = dep.get("to_seq") or dep.get("to_sequence")
                    if from_seq and to_seq:
                        validated.append({
                            "from_sequence": from_seq,
                            "from_field": dep.get("from_field"),
                            "to_sequence": to_seq,
                            "to_field": dep.get("to_field"),
                            "confidence": dep.get("confidence", 0.9),
                            "reasoning": dep.get("reasoning", ""),
                        })
                return validated
        except Exception as e:
            print(f"   解析失败: {e}")
        return self._rule_based_analysis(recordings)

    def _rule_based_analysis(self, recordings: List[Dict]) -> List[Dict]:
        """基于规则的依赖分析（回退方案）"""
        dependencies: List[Dict] = []
        id_patterns: List[str] = ["id", "Id", "uuid"]

        for i, current_req in enumerate(recordings):
            if current_req["method"] not in ["POST", "PUT"]:
                continue

            response_body = current_req.get("response_body", {})
            if not isinstance(response_body, dict):
                continue

            extracted_ids: Dict[str, Any] = {}
            for key, value in response_body.items():
                if any(p in key for p in id_patterns):
                    if isinstance(value, (int, str)) and value:
                        extracted_ids[key] = value

            if not extracted_ids:
                continue

            for next_req in recordings[i + 1:]:
                request_body = next_req.get("request_body", {})
                if not isinstance(request_body, dict):
                    continue
                for field_name, field_value in request_body.items():
                    if isinstance(field_value, str) and field_value:
                        for id_key, id_value in extracted_ids.items():
                            if str(field_value) == str(id_value):
                                dependencies.append({
                                    "from_sequence": current_req["sequence"],
                                    "from_field": id_key,
                                    "from_example": id_value,
                                    "to_sequence": next_req["sequence"],
                                    "to_field": field_name,
                                    "confidence": 0.85,
                                    "reasoning": (
                                        f"S{current_req['sequence']}.{id_key} → "
                                        f"S{next_req['sequence']}.{field_name}"
                                    ),
                                })

        return dependencies
