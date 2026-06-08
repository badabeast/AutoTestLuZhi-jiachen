#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
断言报告生成器

汇总三层断言结果，生成结构化报告。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

from .assertion_rule import AssertionResult


def generate_report(results: List[AssertionResult]) -> Dict[str, Any]:
    """生成断言报告

    Args:
        results: 断言结果列表

    Returns:
        Dict: 包含 summary 和 details 的报告
    """
    summary = {
        "total": len(results),
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "error": 0,
        "by_layer": {
            "ui": {"passed": 0, "failed": 0, "skipped": 0},
            "api": {"passed": 0, "failed": 0, "skipped": 0},
            "db": {"passed": 0, "failed": 0, "skipped": 0},
        },
    }

    details = []
    for r in results:
        summary[r.status] = summary.get(r.status, 0) + 1
        if r.layer in summary["by_layer"]:
            summary["by_layer"][r.layer][r.status] = \
                summary["by_layer"][r.layer].get(r.status, 0) + 1
        details.append({
            "layer": r.layer,
            "description": r.description,
            "status": r.status,
            "expected": r.expected,
            "actual": r.actual,
            "error_message": r.error_message,
        })

    return {
        "summary": summary,
        "details": details,
        "success": summary["failed"] == 0 and summary["error"] == 0,
        "timestamp": datetime.now().isoformat(),
    }


def save_report(results: List[AssertionResult], output_path: str) -> Path:
    """保存断言报告到 JSON 文件

    Args:
        results: 断言结果列表
        output_path: 输出文件路径

    Returns:
        Path: 保存的文件路径
    """
    report = generate_report(results)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    return path


def print_report(results: List[AssertionResult]):
    """打印断言报告摘要"""
    report = generate_report(results)
    s = report["summary"]

    print(f"\n{'='*50}")
    print(f"  断言报告")
    print(f"{'='*50}")
    print(f"  总计: {s['total']}  通过: {s['passed']}  失败: {s['failed']}  跳过: {s['skipped']}  错误: {s['error']}")

    for layer, counts in s["by_layer"].items():
        print(f"  {layer.upper()}: ✅{counts['passed']} ❌{counts['failed']} ⏭️{counts['skipped']}")

    for d in report["details"]:
        icon = {"passed": "✅", "failed": "❌", "skipped": "⏭️", "error": "⚠️"}.get(d["status"], "?")
        print(f"  {icon} [{d['layer'].upper()}] {d['description']}")
        if d.get("error_message"):
            print(f"       {d['error_message']}")

    print(f"{'='*50}")
    return report
