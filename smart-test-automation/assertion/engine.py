#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三层断言引擎 — 统一入口

委托给各层断言子模块:
  - ui_assertion.py: UI 层断言
  - api_assertion.py: API 层断言
  - db_assertion.py: DB 层断言
  - report.py: 报告生成

用法::

    engine = ThreeLayerAssertionEngine()
    results = engine.run_assertions(assertions, context={"page": page, "api_calls": calls})
    report = engine.generate_report(results)
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any

# 从拆分后的子模块导入
from .assertion_rule import AssertionResult, AssertionLayer, AssertionStatus
from .ui_assertion import assert_ui
from .api_assertion import assert_api
from .db_assertion import assert_db
from .report import generate_report, save_report as _save_report


class ThreeLayerAssertionEngine:
    """三层断言引擎（统一入口）"""

    def run_assertions(
        self,
        assertions: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> List[AssertionResult]:
        """批量执行断言

        Args:
            assertions: 断言列表，每条包含 layer, type, description, expected 等字段
            context: 执行上下文，包含 page, api_calls, variables 等

        Returns:
            List[AssertionResult]: 断言结果列表
        """
        results = []
        for assertion in assertions:
            layer = assertion.get("layer", "ui")
            if layer == "ui":
                results.append(assert_ui(assertion, context))
            elif layer == "api":
                results.append(assert_api(assertion, context))
            elif layer == "db":
                results.append(assert_db(assertion, context))
            else:
                results.append(AssertionResult(
                    layer=layer,
                    description=assertion.get("description", ""),
                    status=AssertionStatus.ERROR,
                    error_message=f"未知断言层: {layer}",
                ))
        return results

    def generate_report(self, results: List[AssertionResult]) -> Dict[str, Any]:
        """生成断言报告"""
        return generate_report(results)

    def save_report(self, results: List[AssertionResult], output_path: str) -> Path:
        """保存断言报告到文件"""
        return _save_report(results, output_path)
