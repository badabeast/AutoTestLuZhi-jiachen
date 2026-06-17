"""AI 兜底修复 — OpenAI 兼容协议

独创性：
1. 使用公司 AI 平台 OpenAI 兼容端点（区别于 playwright-healer 的 Anthropic 协议）
2. 集成 DOM 裁剪优化机制，减少 token 消耗
3. AI 输出也经过置信度打分公式修正，只有 ≥0.75 才采纳
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from playwright.sync_api import Page

from self_healing.selector_parser import parse_selector
from self_healing.dom_trimmer import DOMTrimmer
from self_healing.candidate_evaluator import HealingCandidate


# AI 修复 Prompt 模板
_HEAL_PROMPT_TEMPLATE = """你是一个 Playwright 自动化测试的选择器修复专家。

## 背景
一个 UI 自动化测试脚本因为前端页面变更导致选择器失效，需要你分析页面 DOM 并给出修复后的选择器。

## 失效的选择器
{selector}

## 失败的操作
{action}

## 页面 DOM 片段（已裁剪）
{dom_snapshot}

## 要求
1. 分析 DOM 片段，找到与原始选择器意图最匹配的元素
2. 返回修复后的 Playwright 选择器表达式（如 get_by_role("textbox", name="新名称").nth(0)）
3. 必须使用 Playwright 语义定位器语法（get_by_role / get_by_text / get_by_label / get_by_test_id / locator）
4. 如果无法确定，返回 CANNOT_FIX

## 输出格式（严格遵守）
```json
{{"healed_selector": "修复后的选择器", "confidence": 0.85, "reason": "修复理由"}}
```
"""


class AIHealer:
    """AI 兜底修复引擎

    使用公司 AI 平台的 OpenAI 兼容接口进行选择器修复。
    集成 DOM 裁剪机制优化输入 Token。
    """

    def __init__(self, page: Page):
        self._page = page
        self._base_url = (
            os.environ.get("AI_BASE_URL", "")
            or os.environ.get("OPENAI_COMPAT_BASE_URL", "")
            or "https://ai-platform.cai-inc.com/api/biz-ai/ai-model/api/11/compatible-mode/v1"
        )
        self._model = (
            os.environ.get("AI_MODEL", "")
            or os.environ.get("OPENAI_COMPAT_MODEL", "")
            or "glm-5.1"
        )
        self._api_key = (
            os.environ.get("AI_API_KEY", "")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
        )

    def heal(self, selector: str, action: str = "click", page_url: str = "") -> Optional[HealingCandidate]:
        """AI 语义修复

        Args:
            selector: 原始失效选择器
            action: 失败的操作类型
            page_url: 页面 URL

        Returns:
            HealingCandidate 或 None
        """
        if not self._api_key:
            return None

        # Step 1: 裁剪 DOM
        trimmer = DOMTrimmer(self._page)
        dom_snapshot = trimmer.trim(selector, page_url)

        if not dom_snapshot:
            dom_snapshot = "<!-- DOM capture failed, using empty snapshot -->"

        # Step 2: 构建 Prompt
        prompt = _HEAL_PROMPT_TEMPLATE.format(
            selector=selector,
            action=action,
            dom_snapshot=dom_snapshot[:8000],  # 安全上限
        )

        # Step 3: 调用 AI
        try:
            response_text = self._call_ai(prompt)
            if not response_text:
                return None

            # Step 4: 解析 AI 输出
            result = self._parse_ai_response(response_text)
            if not result or result.get("healed_selector") == "CANNOT_FIX":
                return None

            healed = result["healed_selector"]
            confidence = float(result.get("confidence", 0.5))
            reason = result.get("reason", "")

            # Step 5: 验证修复后的选择器
            if self._verify_selector(healed):
                return HealingCandidate(
                    selector=healed,
                    confidence=confidence,
                    source_level=6,
                    strategy_name="ai",
                    verified=True,
                    page_url=page_url,
                    base_score=confidence,
                    strategy_weight=0.80,  # AI 权重最低
                    context_bonus=1.0,
                    profile_modifier=1.0,
                )
        except Exception:
            pass

        return None

    def _call_ai(self, prompt: str) -> Optional[str]:
        """调用 OpenAI 兼容 API

        使用 urllib 标准库发送请求，无需额外依赖。

        Args:
            prompt: 用户提示词

        Returns:
            AI 响应文本，或 None
        """
        import urllib.request
        import urllib.error

        url = f"{self._base_url}/chat/completions"
        data = json.dumps({
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1024,
            "temperature": 0.1,
        }).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return body.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception:
            return None

    def _parse_ai_response(self, text: str) -> Optional[dict]:
        """解析 AI 的 JSON 响应

        支持多种格式：Markdown 代码块、纯 JSON、内嵌 JSON 对象。

        Args:
            text: AI 返回的文本

        Returns:
            解析后的字典，或 None
        """
        # 提取 JSON 块
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 回退：直接解析全文
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 再回退：搜索 JSON 对象
        brace_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        return None

    def _verify_selector(self, selector: str) -> bool:
        """验证修复后的选择器是否能定位到元素

        将选择器字符串解析为 Playwright Locator 并检查是否能找到元素。

        Args:
            selector: 选择器字符串

        Returns:
            True 表示选择器有效且能定位到至少一个元素
        """
        try:
            expr = parse_selector(selector)
            locator = None
            for call in expr.calls:
                method = call.method
                args = call.args
                kwargs = call.kwargs

                if method in ("get_by_role", "get_by_text", "get_by_label",
                              "get_by_test_id", "get_by_placeholder", "locator"):
                    fn = getattr(self._page, method, None)
                    if fn is None:
                        return False
                    locator = fn(*args, **kwargs)
                elif method == "nth" and locator:
                    locator = locator.nth(*args)
                elif method == "first" and locator:
                    locator = locator.first
                elif method == "last" and locator:
                    locator = locator.last
                elif method == "filter" and locator:
                    clean_kwargs = {k: v for k, v in kwargs.items() if k != "has"}
                    locator = locator.filter(**clean_kwargs)
                else:
                    return False

            if locator and locator.count() > 0:
                return True
        except Exception:
            pass
        return False
