#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多模型适配层，统一OpenAI兼容协议对接各供应商。模型配置从文件加载，API Key从环境变量读取。"""

import os
import json
import re
import logging
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Dict, Any


from dataclasses import dataclass, field as dc_field

logger = logging.getLogger(__name__)


@dataclass
class UIOperation:
    """UI 操作记录"""
    step_index: int = 0
    action: str = ""
    selector_type: str = ""
    selector_value: str = ""
    selector_name: Optional[str] = None
    value: Optional[str] = None
    raw_line: str = ""
    # 兼容旧代码中 op.type / op.selector 的属性访问
    type: str = ""
    selector: str = ""


@dataclass
class APICall:
    """API 调用记录"""
    step_index: int = 0
    method: str = ""
    url: str = ""
    path: str = ""
    request_body: Optional[Any] = None
    status: int = 0
    response_body: Optional[Any] = None


@dataclass
class OperationIntent:
    """操作意图"""
    action: str = ""
    business_purpose: str = ""
    target_entity: str = ""
    expected_outcome: str = ""
    natural_language: str = ""


@dataclass
class SelectorOptimization:
    """选择器优化结果"""
    original: str = ""
    optimized: str = ""
    strategy: str = ""
    confidence: float = 0.9
    reasoning: str = ""


@dataclass
class OptimizedScript:
    """优化后的脚本"""
    code: str = ""
    module_name: str = ""


_CONFIG_PATH = Path(__file__).parent / "models_config.json"


def _load_model_registry() -> Dict[str, Dict[str, Any]]:
    """从 models_config.json 加载模型配置

    配置文件中的 url 和 vendor_urls 值为空时，
    从同名环境变量读取（如 vendor_urls.tencent_token_plan → env TENCENT_TOKEN_PLAN_URL）。
    """
    if not _CONFIG_PATH.exists():
        logger.warning("模型配置文件不存在: %s", _CONFIG_PATH)
        return {}

    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    registry: Dict[str, Dict[str, Any]] = {}
    vendor_urls = config.get("vendor_urls", {})

    # vendor_urls 中的值直接从配置文件读取（配置文件不推送到远程仓库）
    resolved_vendor_urls: Dict[str, str] = {}
    for vendor, url in vendor_urls.items():
        resolved_vendor_urls[vendor] = url

    for model_id, model_info in config.get("models", {}).items():
        entry = dict(model_info)

        # url 为空时，用 vendor_urls 中对应 vendor 的 URL
        if not entry.get("url"):
            vendor = entry.get("vendor", "")
            entry["url"] = resolved_vendor_urls.get(vendor, "")

        # env_key 为 null 时转为 None
        if entry.get("env_key") is None:
            entry["env_key"] = None

        registry[model_id] = entry

    return registry


MODEL_REGISTRY: Dict[str, Dict[str, Any]] = _load_model_registry()
DEFAULT_MODEL: str = (
    os.environ.get("AI_MODEL", "")
    or os.environ.get("AI_DEFAULT_MODEL", "")
    or "glm-5.1"
)


class AIProvider(ABC):
    """AI Provider 抽象基类"""

    @abstractmethod
    def analyze_intent(
        self,
        operations: List[UIOperation],
        api_calls: Optional[List[APICall]] = None,
    ) -> List[OperationIntent]:
        """分析操作意图"""
        pass

    @abstractmethod
    def optimize_selectors(
        self,
        operations: List[UIOperation],
        dom_snapshot: Optional[str] = None,
    ) -> List[SelectorOptimization]:
        """优化选择器"""
        pass

    @abstractmethod
    def generate_test_code(
        self,
        session_name: str,
        operations: List[UIOperation],
        intents: List[OperationIntent],
        selectors: List[SelectorOptimization],
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """生成 Playwright Python 测试代码"""
        pass


class OpenAICompatibleProvider(AIProvider):
    """OpenAI 兼容接口 Provider（统一实现）

    支持所有遵循 OpenAI Chat Completions 协议的 API：
    - 腾讯云 TokenPlan (GLM-5.1, MiniMax 2.7)
    - 百炼 (Qwen, DeepSeek)
    - 智谱
    - OpenAI
    """

    def __init__(
        self,
        model_id: str = "deepseek-v4-pro",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        # 从注册表获取模型配置
        model_info = MODEL_REGISTRY.get(model_id)
        if not model_info:
            raise ValueError(
                f"未注册的模型: {model_id}，"
                f"可用模型: {list(MODEL_REGISTRY.keys())}"
            )

        self.model_id = model_id
        self.model_name = model_info["name"]
        self.vendor = model_info["vendor"]

        # API 地址
        self.base_url = base_url or model_info["url"]

        # API Key：优先传入 > 环境变量
        env_key = model_info.get("env_key")
        self.api_key = api_key or (os.getenv(env_key, "") if env_key else "")
        if env_key and not self.api_key:
            raise ValueError(
                f"请设置环境变量 {env_key} 或在构造时传入 api_key"
            )

        logger.info("AI Provider: %s / %s", self.model_name, self.base_url)

    def analyze_intent(
        self,
        operations: List[UIOperation],
        api_calls: Optional[List[APICall]] = None,
    ) -> List[OperationIntent]:
        """分析操作意图"""
        prompt = self._build_intent_prompt(operations, api_calls)
        try:
            response = self._call_api(prompt)
            return self._parse_intent_response(response, operations)
        except Exception as e:
            logger.warning("AI意图分析失败: %s", e)
            return self._fallback_intents(operations)

    def optimize_selectors(
        self,
        operations: List[UIOperation],
        dom_snapshot: Optional[str] = None,
    ) -> List[SelectorOptimization]:
        """优化选择器"""
        prompt = self._build_selector_prompt(operations, dom_snapshot)
        try:
            response = self._call_api(prompt)
            return self._parse_selector_response(response, operations)
        except Exception as e:
            logger.warning("选择器优化失败: %s", e)
            return self._fallback_selectors(operations)

    def generate_test_code(
        self,
        session_name: str,
        operations: List[UIOperation],
        intents: List[OperationIntent],
        selectors: List[SelectorOptimization],
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """生成 Playwright Python 测试代码"""
        prompt = self._build_test_code_prompt(
            session_name, operations, intents, selectors, config
        )
        try:
            response = self._call_api(prompt)
            return self._extract_code(response)
        except Exception as e:
            logger.warning("代码生成失败: %s", e)
            return self._fallback_test_code(session_name, operations)

    # OpenAI Chat Completions 协议

    def _call_api(self, prompt: str, temperature: float = 0.3) -> str:
        """调用 OpenAI 兼容 Chat Completions API

        OpenAI 兼容协议：
          POST {base_url}/chat/completions
          Header: Authorization: Bearer + Content-Type
          Body: { model, messages, max_tokens, temperature }
          Response: { choices: [{message: {content: "..."}}] }
        """
        # 统一读取 AI 配置，支持新旧变量名
        ai_key = (
            os.environ.get("AI_API_KEY", "")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
            or getattr(self, "api_key", "")
        )
        ai_base = (
            os.environ.get("AI_BASE_URL", "")
            or os.environ.get("OPENAI_COMPAT_BASE_URL", "")
            or "https://ai-platform.cai-inc.com/api/biz-ai/ai-model/api/11/compatible-mode/v1"
        )

        url = f"{ai_base.rstrip('/')}/chat/completions"

        data = {
            "model": self.model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4096,
            "temperature": temperature,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ai_key}",
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
            choices = result.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return str(result)

    def _build_intent_prompt(
        self,
        operations: List[UIOperation],
        api_calls: Optional[List[APICall]] = None,
    ) -> str:
        """构建意图分析提示词"""
        prompt = "分析以下UI操作序列，理解每个操作的业务意图。\n\n操作序列：\n"
        for i, op in enumerate(operations):
            op_type = op.type.value if hasattr(op.type, "value") else op.type
            prompt += f"{i+1}. [{op_type}] {op.selector or ''} {op.value or ''}\n"
        if api_calls:
            prompt += "\n关联API调用：\n"
            for api in api_calls:
                prompt += f"- {api.method} {api.path}\n"
        prompt += (
            "\n请为每个操作生成意图描述，返回JSON数组格式：\n"
            '[{"action": "动作描述", "businessPurpose": "业务目的", '
            '"targetEntity": "目标实体", "expectedOutcome": "预期结果", '
            '"naturalLanguage": "自然语言描述"}]\n\n直接返回JSON数组：'
        )
        return prompt

    def _build_selector_prompt(
        self,
        operations: List[UIOperation],
        dom_snapshot: Optional[str] = None,
    ) -> str:
        """构建选择器优化提示词"""
        prompt = "优化以下UI操作的选择器，使其更稳定可靠。\n\n原始操作：\n"
        for i, op in enumerate(operations):
            op_action = op.action or (op.type if isinstance(op.type, str) else str(op.type))
            op_sel = op.selector or op.selector_value or "unknown"
            prompt += f"{i+1}. [{op_action}] selector: {op_sel}\n"
        if dom_snapshot:
            prompt += f"\nDOM 快照片段：\n{dom_snapshot[:2000]}\n"
        prompt += (
            "\n优化要求：\n1. 优先使用 getByTestId, getByRole, getByLabel\n"
            "2. 避免使用索引选择器\n3. 减少XPath使用\n\n"
            '返回JSON数组：[{"original": "原始", "optimized": "优化后", '
            '"strategy": "策略", "confidence": 0.95, "reasoning": "理由"}]\n\n'
            "直接返回JSON数组："
        )
        return prompt

    def _build_test_code_prompt(
        self,
        session_name: str,
        operations: List[UIOperation],
        intents: List[OperationIntent],
        selectors: List[SelectorOptimization],
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """构建测试代码生成提示词"""
        prompt = f"根据以下录制数据，生成 Playwright Python 测试代码。\n\n场景名称：{session_name}\n\n操作序列：\n"
        for i, (op, intent) in enumerate(zip(operations, intents)):
            description = intent.natural_language if i < len(intents) else op.type.value
            selector = selectors[i].optimized if i < len(selectors) else (op.selector or "")
            prompt += f"{i+1}. {description}\n   selector: {selector}\n"
        prompt += (
            "\n要求：\n1. 使用 playwright.sync_api\n2. 优先使用 getByTestId, getByRole\n"
            "3. 添加适当等待\n4. 包含断言\n5. 可直接 python3 运行\n\n"
            "直接输出 Python 代码："
        )
        return prompt

    def _parse_intent_response(
        self, response: str, operations: List[UIOperation]
    ) -> List[OperationIntent]:
        """解析意图分析响应"""
        try:
            json_match = re.search(r"\[.*\]", response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return [
                    OperationIntent(
                        action=item.get("action", ""),
                        business_purpose=item.get("businessPurpose", ""),
                        target_entity=item.get("targetEntity", ""),
                        expected_outcome=item.get("expectedOutcome", ""),
                        natural_language=item.get("naturalLanguage", ""),
                    )
                    for item in data
                ]
        except Exception as e:
            logger.warning("意图解析失败: %s", e)
        return self._fallback_intents(operations)

    def _parse_selector_response(
        self, response: str, operations: List[UIOperation]
    ) -> List[SelectorOptimization]:
        """解析选择器优化响应"""
        try:
            json_match = re.search(r"\[.*\]", response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return [
                    SelectorOptimization(
                        original=item.get("original", ""),
                        optimized=item.get("optimized", ""),
                        strategy=item.get("strategy", ""),
                        confidence=item.get("confidence", 0.9),
                        reasoning=item.get("reasoning", ""),
                    )
                    for item in data
                ]
        except Exception as e:
            logger.warning("意图解析失败: %s", e)
        return self._fallback_selectors(operations)

    def _extract_code(self, response: str) -> str:
        """提取代码"""
        code_match = re.search(r"```(?:python)?\n(.*?)```", response, re.DOTALL)
        if code_match:
            return code_match.group(1).strip()
        return response.strip()

    # 回退策略

    @staticmethod
    def _fallback_intents(operations: List[UIOperation]) -> List[OperationIntent]:
        """回退：生成基本意图"""
        return [
            OperationIntent(
                action=f"执行 {op.type.value if hasattr(op.type, 'value') else op.type}",
                business_purpose="用户操作",
                target_entity="UI元素",
                expected_outcome="操作成功",
                natural_language=f"{op.type.value} on {op.selector or 'element'}",
            )
            for op in operations
        ]

    @staticmethod
    def _fallback_selectors(operations: List[UIOperation]) -> List[SelectorOptimization]:
        """回退：保留原始选择器"""
        return [
            SelectorOptimization(
                original=op.selector or "",
                optimized=op.selector or "",
                strategy="fallback",
                confidence=0.5,
                reasoning="优化失败，使用原始选择器",
            )
            for op in operations
        ]

    def _fallback_test_code(self, session_name: str, operations: List[UIOperation]) -> str:
        """回退：生成基本测试代码"""
        lines = [
            "from playwright.sync_api import sync_playwright",
            "",
            f"def test_{session_name}():",
            '    with sync_playwright() as p:',
            "        browser = p.chromium.launch(headless=False)",
            "        page = browser.new_page()",
        ]
        for op in operations:
            op_action = op.action or (op.type if isinstance(op.type, str) else str(op.type))
            selector = op.selector or op.selector_value or ""
            if op_action == "navigate":
                lines.append(f"        page.goto('{selector}')")
            elif op_action == "click":
                lines.append(f"        page.locator('{selector}').click()")
            elif op_action in ("type", "fill"):
                lines.append(f"        page.locator('{selector}').fill('{op.value or ''}')")
            else:
                lines.append(f"        # TODO: {op_action} - {selector}")
        lines.extend(["        browser.close()", ""])
        return "\n".join(lines)


class MinimaxProvider(OpenAICompatibleProvider):
    """MiniMax Provider（向后兼容）"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "MiniMax-M2.7-highspeed",
        base_url: Optional[str] = None,
    ):
        super().__init__(
            model_id="minimax",
            api_key=api_key,
            base_url=base_url,
        )


class OpenAIProvider(OpenAICompatibleProvider):
    """OpenAI Provider（向后兼容）"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
    ):
        super().__init__(
            model_id="openai",
            api_key=api_key,
        )


def create_ai_provider(
    provider_type: str = DEFAULT_MODEL,
    model_id: Optional[str] = None,
    api_key: Optional[str] = None,
    **kwargs: Any,
) -> AIProvider:
    """创建 AI Provider

    Args:
        provider_type: Provider 类型或模型 ID
            - "deepseek-v4-pro"（默认）: 百炼 DeepSeek-V4-Pro
            - "minimax-2.7": 腾讯云 TokenPlan MiniMax 2.7
            - "qwen3.7-max": 百炼 Qwen3.7-Max
            - "qwen3.6-plus": 百炼 Qwen3.6-Plus
            - "dashscope-glm-5.1": 百炼 GLM-5.1
            - "deepseek-v4-pro": 百炼 DeepSeek-V4-Pro
            - "minimax": 独立 MiniMax API
            - "zhipu": 智谱 API
            - "openai": OpenAI API
            - "ollama": 本地 Ollama
        model_id: 覆盖模型标识（发送给 API 的实际 model 字段）
        api_key: 覆盖 API Key
        **kwargs: 额外参数

    Returns:
        AIProvider 实例
    """
    # 向后兼容：旧的 provider_type 值
    legacy_map = {
        "minimax": "minimax",
        "zhipu": "zhipu",
        "dashscope": "qwen3.7-max",
        "openai": "openai",
        "ollama": "ollama",
    }

    if provider_type in legacy_map and provider_type not in MODEL_REGISTRY:
        provider_type = legacy_map[provider_type]

    provider = OpenAICompatibleProvider(
        model_id=provider_type,
        api_key=api_key,
        base_url=kwargs.get("base_url"),
    )

    # 如果需要覆盖实际发送的 model 字段
    if model_id:
        provider.model_id = model_id

    return provider


def list_available_models() -> Dict[str, Dict[str, Any]]:
    """列出所有可用模型"""
    return MODEL_REGISTRY.copy()
