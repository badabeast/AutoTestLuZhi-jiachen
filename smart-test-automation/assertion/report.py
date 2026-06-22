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
    """保存断言报告（JSON + HTML 双格式）

    Args:
        results: 断言结果列表
        output_path: 输出 JSON 文件路径

    Returns:
        Path: 保存的 JSON 文件路径
    """
    report = generate_report(results)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    # 同时生成 HTML 报告
    html_path = path.with_suffix('.html')
    html_path.write_text(_render_html(report), encoding='utf-8')
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


def save_html_report(results: List[AssertionResult], output_path: str) -> Path:
    """生成 HTML 格式的断言报告（单文件，无外部依赖）

    Args:
        results: 断言结果列表
        output_path: 输出文件路径

    Returns:
        Path: 保存的文件路径
    """
    report = generate_report(results)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    html = _render_html(report)
    path.write_text(html, encoding='utf-8')
    return path


def _render_html(report: Dict[str, Any]) -> str:
    """渲染 HTML 报告页面"""
    s = report["summary"]
    details = report["details"]
    timestamp = report.get("timestamp", "")
    success = report.get("success", False)

    status_icon = "PASS" if success else "FAIL"
    status_class = "status-pass" if success else "status-fail"

    # 计算通过率
    total = s["total"]
    passed = s["passed"]
    pass_rate = f"{passed / total * 100:.1f}%" if total > 0 else "0%"

    # 生成详情行 HTML
    detail_rows = []
    for i, d in enumerate(details, 1):
        layer = d["layer"].upper()
        status = d["status"]
        icon = {"passed": "&#10004;", "failed": "&#10008;", "skipped": "&#9654;", "error": "&#9888;"}.get(status, "?")
        row_class = f"row-{status}"
        desc = d.get("description", "")
        expected = d.get("expected", "")
        actual = d.get("actual", "")
        error_msg = d.get("error_message", "")

        error_cell = f'<div class="error-msg">{error_msg}</div>' if error_msg else ""
        detail_rows.append(f"""
            <tr class="{row_class}">
                <td class="col-idx">{i}</td>
                <td><span class="badge badge-{layer.lower()}">{layer}</span></td>
                <td class="col-desc">{desc}{error_cell}</td>
                <td class="col-expected">{expected}</td>
                <td class="col-actual">{actual}</td>
                <td><span class="status-icon icon-{status}">{icon} {status}</span></td>
            </tr>""")

    rows_html = "\n".join(detail_rows)

    # 层统计卡片
    layer_cards = []
    for layer_name in ["ui", "api", "db"]:
        lc = s["by_layer"].get(layer_name, {})
        lp = lc.get("passed", 0)
        lf = lc.get("failed", 0)
        ls = lc.get("skipped", 0)
        lt = lp + lf + ls
        layer_cards.append(f"""
            <div class="layer-card layer-{layer_name}">
                <div class="layer-name">{layer_name.upper()}</div>
                <div class="layer-count">{lt}</div>
                <div class="layer-detail">
                    <span class="pass-dot"></span>{lp}
                    <span class="fail-dot"></span>{lf}
                    <span class="skip-dot"></span>{ls}
                </div>
            </div>""")

    layer_html = "\n".join(layer_cards)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Smart Test Automation - 断言报告</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; background: #f0f2f5; color: #1a1a1a; line-height: 1.6; }}

  .header {{ background: linear-gradient(135deg, #1a73e8 0%, #0d47a1 100%); color: #fff; padding: 32px 40px; }}
  .header h1 {{ font-size: 22px; font-weight: 600; margin-bottom: 4px; }}
  .header .meta {{ font-size: 13px; opacity: 0.85; }}

  .container {{ max-width: 1100px; margin: -24px auto 40px; padding: 0 20px; }}

  /* 顶部状态栏 */
  .status-bar {{ display: flex; gap: 16px; margin-bottom: 24px; }}
  .status-card {{ flex: 1; background: #fff; border-radius: 10px; padding: 20px 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
  .status-card .label {{ font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }}
  .status-card .value {{ font-size: 28px; font-weight: 700; }}
  .status-card .value.pass {{ color: #2e7d32; }}
  .status-card .value.fail {{ color: #c62828; }}
  .status-card .value.rate {{ color: #1565c0; }}

  /* 全局状态标签 */
  .overall {{ display: inline-block; padding: 6px 18px; border-radius: 20px; font-size: 14px; font-weight: 700; letter-spacing: 1px; margin-top: 4px; }}
  .status-pass {{ background: #e8f5e9; color: #2e7d32; }}
  .status-fail {{ background: #ffebee; color: #c62828; }}

  /* 层卡片 */
  .layers {{ display: flex; gap: 16px; margin-bottom: 24px; }}
  .layer-card {{ flex: 1; background: #fff; border-radius: 10px; padding: 18px 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); border-left: 4px solid #ccc; }}
  .layer-ui {{ border-left-color: #7c4dff; }}
  .layer-api {{ border-left-color: #00bcd4; }}
  .layer-db {{ border-left-color: #ff9800; }}
  .layer-name {{ font-size: 13px; font-weight: 600; color: #555; letter-spacing: 0.5px; }}
  .layer-count {{ font-size: 26px; font-weight: 700; margin: 4px 0; }}
  .layer-detail {{ font-size: 12px; color: #888; }}
  .pass-dot, .fail-dot, .skip-dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 2px; }}
  .pass-dot {{ background: #4caf50; }}
  .fail-dot {{ background: #e53935; }}
  .skip-dot {{ background: #ff9800; }}

  /* 详情表格 */
  .detail-section {{ background: #fff; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); overflow: hidden; }}
  .detail-section h2 {{ font-size: 16px; padding: 16px 24px; border-bottom: 1px solid #eee; color: #333; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  thead th {{ background: #fafafa; padding: 10px 14px; text-align: left; font-weight: 600; color: #555; border-bottom: 2px solid #eee; font-size: 12px; text-transform: uppercase; letter-spacing: 0.3px; }}
  tbody td {{ padding: 10px 14px; border-bottom: 1px solid #f5f5f5; vertical-align: top; }}
  .col-idx {{ width: 40px; text-align: center; color: #bbb; }}
  .col-desc {{ max-width: 320px; word-break: break-all; }}
  .col-expected, .col-actual {{ font-family: "SF Mono", Monaco, Consolas, monospace; font-size: 12px; }}

  /* badge */
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; }}
  .badge-ui {{ background: #ede7f6; color: #5e35b1; }}
  .badge-api {{ background: #e0f7fa; color: #00838f; }}
  .badge-db {{ background: #fff3e0; color: #e65100; }}

  /* 状态图标 */
  .status-icon {{ display: inline-flex; align-items: center; gap: 4px; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }}
  .icon-passed {{ background: #e8f5e9; color: #2e7d32; }}
  .icon-failed {{ background: #ffebee; color: #c62828; }}
  .icon-skipped {{ background: #fff3e0; color: #e65100; }}
  .icon-error {{ background: #fce4ec; color: #ad1457; }}

  /* 行高亮 */
  tr.row-failed {{ background: #fff8f8; }}
  tr.row-error {{ background: #fef5f8; }}
  .error-msg {{ margin-top: 4px; font-size: 11px; color: #c62828; background: #fff0f0; padding: 4px 8px; border-radius: 4px; }}

  .footer {{ text-align: center; padding: 20px; font-size: 12px; color: #aaa; }}
</style>
</head>
<body>

<div class="header">
  <h1>Smart Test Automation - 断言报告</h1>
  <div class="meta">
    <span>执行时间: {timestamp}</span>
    &nbsp;|&nbsp;
    <span>总计断言: {total} 条</span>
    &nbsp;|&nbsp;
    <span class="overall {status_class}">{status_icon}</span>
  </div>
</div>

<div class="container">
  <div class="status-bar">
    <div class="status-card">
      <div class="label">通过</div>
      <div class="value pass">{passed}</div>
    </div>
    <div class="status-card">
      <div class="label">失败</div>
      <div class="value fail">{s['failed']}</div>
    </div>
    <div class="status-card">
      <div class="label">跳过</div>
      <div class="value" style="color:#e65100">{s['skipped']}</div>
    </div>
    <div class="status-card">
      <div class="label">通过率</div>
      <div class="value rate">{pass_rate}</div>
    </div>
  </div>

  <div class="layers">
    {layer_html}
  </div>

  <div class="detail-section">
    <h2>断言详情</h2>
    <table>
      <thead>
        <tr>
          <th class="col-idx">#</th>
          <th>层级</th>
          <th>描述</th>
          <th>期望值</th>
          <th>实际值</th>
          <th>状态</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </div>
</div>

<div class="footer">
  Smart Test Automation &copy; 2026 &nbsp;|&nbsp; Generated by assertion/report.py
</div>

</body>
</html>"""
    return html
