#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
综合报告生成器

将断言报告、自愈修复报告、策略修复报告合并为一个多 Tab 的 HTML 报告页面。
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any


def generate_comprehensive_report(
    module_name: str,
    assertion_json_path: Optional[str] = None,
    heal_json_path: Optional[str] = None,
    strategy_json_path: Optional[str] = None,
    output_path: str = "",
) -> Path:
    """生成综合 HTML 报告（三合一，Tab 切换）

    Args:
        module_name: 模块名称
        assertion_json_path: 断言报告 JSON 路径
        heal_json_path: 自愈修复报告 JSON 路径
        strategy_json_path: 策略修复报告 JSON 路径
        output_path: 输出 HTML 路径（默认: output/modules/<module>/comprehensive_report.html）

    Returns:
        Path: 生成的 HTML 文件路径
    """
    data = {
        "module_name": module_name,
        "assertion": _load_json(assertion_json_path),
        "heal": _load_json(heal_json_path),
        "strategy": _load_json(strategy_json_path),
    }

    html = _render_comprehensive_html(data)

    if not output_path:
        output_path = f"output/modules/{module_name}/comprehensive_report.html"

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


def _load_json(path: Optional[str]) -> Optional[Dict[str, Any]]:
    """安全加载 JSON 文件"""
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _render_comprehensive_html(data: Dict[str, Any]) -> str:
    """渲染综合报告 HTML"""
    module_name = data["module_name"]
    assertion_data = data.get("assertion")
    heal_data = data.get("heal")
    strategy_data = data.get("strategy")

    # 计算整体状态
    overall_success = True
    if assertion_data and not assertion_data.get("success", False):
        overall_success = False
    if strategy_data and strategy_data.get("failed", 0) > 0:
        overall_success = False

    status_class = "status-pass" if overall_success else "status-fail"
    status_text = "PASS" if overall_success else "FAIL"

    # 统计可用报告数
    report_count = sum(1 for v in [assertion_data, heal_data, strategy_data] if v)

    # Tab 标签
    tabs = []
    tab_contents = []
    tab_ids = []

    if assertion_data:
        tab_ids.append("assertion")
        tabs.append(("assertion", "断言报告", _render_assertion_badge(assertion_data)))
        tab_contents.append(("assertion", _render_assertion_tab(assertion_data)))

    if heal_data:
        tab_ids.append("heal")
        tabs.append(("heal", "自愈修复", _render_heal_badge(heal_data)))
        tab_contents.append(("heal", _render_heal_tab(heal_data)))

    if strategy_data:
        tab_ids.append("strategy")
        tabs.append(("strategy", "策略修复", _render_strategy_badge(strategy_data)))
        tab_contents.append(("strategy", _render_strategy_tab(strategy_data)))

    # 生成 Tab 按钮 HTML
    tabs_html = ""
    for i, (tid, label, badge) in enumerate(tabs):
        active = " active" if i == 0 else ""
        tabs_html += f'<button class="tab-btn{active}" onclick="switchTab(\'{tid}\')" id="tab-{tid}">{label} {badge}</button>\n'

    # 生成 Tab 内容 HTML
    contents_html = ""
    for i, (tid, content) in enumerate(tab_contents):
        display = "block" if i == 0 else "none"
        contents_html += f'<div class="tab-content" id="content-{tid}" style="display:{display}">{content}</div>\n'

    # 无报告时的提示
    no_data_html = ""
    if report_count == 0:
        no_data_html = '<div class="no-data">暂无报告数据，请先运行测试: <code>python3 cli.py run {module_name}</code></div>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>综合报告 - {module_name}</title>
<style>
{_get_css()}
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <h1>综合测试报告</h1>
    <div class="module-name">{module_name}</div>
  </div>
  <div class="header-right">
    <span class="overall-badge {status_class}">{status_text}</span>
    <div class="meta">{report_count} 份报告</div>
  </div>
</div>

<div class="container">

  {_render_summary_cards(assertion_data, heal_data, strategy_data)}

  <div class="tabs">
    {tabs_html}
  </div>

  {no_data_html}
  {contents_html}

</div>

<div class="footer">
  Smart Test Automation &copy; 2026 &nbsp;|&nbsp; Comprehensive Report
</div>

<script>
function switchTab(tabId) {{
  // 隐藏所有 tab content
  document.querySelectorAll('.tab-content').forEach(function(el) {{
    el.style.display = 'none';
  }});
  // 移除所有 active
  document.querySelectorAll('.tab-btn').forEach(function(el) {{
    el.classList.remove('active');
  }});
  // 显示目标 tab
  var content = document.getElementById('content-' + tabId);
  if (content) content.style.display = 'block';
  var tab = document.getElementById('tab-' + tabId);
  if (tab) tab.classList.add('active');
}}
</script>

</body>
</html>"""


# ── 摘要卡片 ──────────────────────────────────────────

def _render_summary_cards(assertion_data, heal_data, strategy_data) -> str:
    """渲染顶部摘要卡片"""
    cards = []

    if assertion_data:
        s = assertion_data.get("summary", {})
        total = s.get("total", 0)
        passed = s.get("passed", 0)
        failed = s.get("failed", 0)
        rate = f"{passed/total*100:.0f}%" if total > 0 else "-"
        color_class = "card-green" if failed == 0 else "card-red"
        cards.append(f"""
        <div class="summary-card {color_class}">
          <div class="card-title">断言通过率</div>
          <div class="card-value">{rate}</div>
          <div class="card-detail">{passed} 通过 / {failed} 失败 / {total} 总计</div>
        </div>""")

    if heal_data:
        failures = heal_data.get("failures", [])
        count = len(failures)
        cards.append(f"""
        <div class="summary-card card-blue">
          <div class="card-title">自愈触发</div>
          <div class="card-value">{count}</div>
          <div class="card-detail">次定位失败捕获</div>
        </div>""")

    if strategy_data:
        repaired = strategy_data.get("repaired", 0)
        total_f = strategy_data.get("total_failures", 0)
        failed_s = strategy_data.get("failed", 0)
        cards.append(f"""
        <div class="summary-card {"card-green" if failed_s == 0 else "card-orange"}">
          <div class="card-title">策略修复</div>
          <div class="card-value">{repaired}/{total_f}</div>
          <div class="card-detail">修复成功 / 总失败数</div>
        </div>""")

    if not cards:
        return ""

    return f'<div class="summary-cards">{"".join(cards)}</div>'


# ── Tab Badge ─────────────────────────────────────────

def _render_assertion_badge(data: Dict) -> str:
    s = data.get("summary", {})
    failed = s.get("failed", 0)
    if failed > 0:
        return f'<span class="badge badge-red">{failed} 失败</span>'
    return '<span class="badge badge-green">全部通过</span>'


def _render_heal_badge(data: Dict) -> str:
    failures = data.get("failures", [])
    count = len(failures)
    if count > 0:
        return f'<span class="badge badge-orange">{count} 次</span>'
    return '<span class="badge badge-green">无触发</span>'


def _render_strategy_badge(data: Dict) -> str:
    repaired = data.get("repaired", 0)
    failed = data.get("failed", 0)
    if failed > 0:
        return f'<span class="badge badge-red">{failed} 未修复</span>'
    if repaired > 0:
        return f'<span class="badge badge-green">{repaired} 已修复</span>'
    return '<span class="badge badge-gray">-</span>'


# ── Tab 内容：断言报告 ────────────────────────────────

def _render_assertion_tab(data: Dict) -> str:
    s = data.get("summary", {})
    details = data.get("details", [])
    timestamp = data.get("timestamp", "")

    # 层统计
    layer_html = ""
    for layer_name in ["ui", "api", "db"]:
        lc = s.get("by_layer", {}).get(layer_name, {})
        lp = lc.get("passed", 0)
        lf = lc.get("failed", 0)
        ls = lc.get("skipped", 0)
        layer_html += f"""
        <div class="layer-chip layer-{layer_name}">
          <strong>{layer_name.upper()}</strong>
          <span class="pass-dot"></span>{lp}
          <span class="fail-dot"></span>{lf}
          <span class="skip-dot"></span>{ls}
        </div>"""

    # 详情表格
    rows = ""
    for i, d in enumerate(details, 1):
        layer = d.get("layer", "").upper()
        status = d.get("status", "")
        icon = {"passed": "&#10004;", "failed": "&#10008;", "skipped": "&#9654;", "error": "&#9888;"}.get(status, "?")
        desc = d.get("description", "")
        expected = d.get("expected", "")
        actual = d.get("actual", "")
        error_msg = d.get("error_message", "")
        error_cell = f'<div class="error-msg">{error_msg}</div>' if error_msg else ""
        row_class = f"row-{status}" if status in ("failed", "error") else ""

        rows += f"""
        <tr class="{row_class}">
          <td class="col-idx">{i}</td>
          <td><span class="layer-badge layer-badge-{layer.lower()}">{layer}</span></td>
          <td class="col-desc">{desc}{error_cell}</td>
          <td class="col-mono">{expected}</td>
          <td class="col-mono">{actual}</td>
          <td><span class="status-pill status-{status}">{icon} {status}</span></td>
        </tr>"""

    return f"""
    <div class="section-info">
      <span>执行时间: {timestamp}</span>
      <span>总计: {s.get("total", 0)} 条断言</span>
    </div>
    <div class="layer-chips">{layer_html}</div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th class="col-idx">#</th><th>层级</th><th>描述</th><th>期望值</th><th>实际值</th><th>状态</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""


# ── Tab 内容：自愈修复报告 ────────────────────────────

def _render_heal_tab(data: Dict) -> str:
    timestamp = data.get("timestamp", "")
    failures = data.get("failures", [])

    if not failures:
        return '<div class="empty-state">本次执行未触发自愈修复</div>'

    rows = ""
    for i, f in enumerate(failures, 1):
        test_name = f.get("test_name", "")
        category = f.get("category", "")
        selector = f.get("selector", "-")
        action = f.get("action", "-")
        page_url = f.get("page_url", "")
        file_path = f.get("file", "")
        line = f.get("line", "")
        error_msg = f.get("error_message", "")
        screenshot = f.get("screenshot", "")

        # 截图链接
        screenshot_cell = ""
        if screenshot and Path(screenshot).exists():
            screenshot_cell = f'<a href="{screenshot}" target="_blank" class="link">查看截图</a>'

        rows += f"""
        <tr>
          <td class="col-idx">{i}</td>
          <td><strong>{test_name}</strong></td>
          <td><span class="category-tag cat-{category}">{category}</span></td>
          <td class="col-mono">{selector or '-'}</td>
          <td class="col-mono">{action or '-'}</td>
          <td>
            <div class="file-info">{file_path}:{line}</div>
            {screenshot_cell}
          </td>
          <td class="col-error">{error_msg}</td>
        </tr>"""

    return f"""
    <div class="section-info">
      <span>触发时间: {timestamp}</span>
      <span>共 {len(failures)} 次定位失败</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th class="col-idx">#</th><th>测试用例</th><th>分类</th><th>选择器</th><th>操作</th><th>文件/截图</th><th>错误信息</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""


# ── Tab 内容：策略修复报告 ────────────────────────────

def _render_strategy_tab(data: Dict) -> str:
    timestamp = data.get("timestamp", "")
    total_failures = data.get("total_failures", 0)
    repaired = data.get("repaired", 0)
    failed = data.get("failed", 0)
    summary = data.get("summary", {})
    details = data.get("details", [])

    # 策略分布
    by_strategy = summary.get("by_strategy", {})
    strategy_chips = ""
    for strategy, count in by_strategy.items():
        strategy_chips += f'<span class="strategy-chip">{strategy}: {count}</span>'

    # 决策摘要
    decisions = summary.get("decisions", [])
    decision_rows = ""
    for d in decisions:
        test_name = d.get("test_name", "")
        sub_cat = d.get("sub_category", "")
        strategy = d.get("strategy", "")
        score = d.get("score", 0)
        decision_rows += f"""
        <tr>
          <td><strong>{test_name}</strong></td>
          <td><span class="category-tag cat-{sub_cat}">{sub_cat}</span></td>
          <td><span class="strategy-tag">{strategy}</span></td>
          <td class="col-mono">{score:.0%}</td>
        </tr>"""

    # 修复详情
    detail_rows = ""
    for d in details:
        test_name = d.get("test_name", "")
        strategy = d.get("strategy", "")
        result = d.get("result", {})
        success = result.get("success", False)
        message = result.get("message", "")
        duration = result.get("duration_ms", 0)
        final_strategy = result.get("strategy", strategy)

        status_icon = "&#10004;" if success else "&#10008;"
        status_cls = "status-passed" if success else "status-failed"
        detail_rows += f"""
        <tr class="{"row-failed" if not success else ""}">
          <td><strong>{test_name}</strong></td>
          <td><span class="strategy-tag">{strategy}</span></td>
          <td><span class="strategy-tag">{final_strategy}</span></td>
          <td><span class="status-pill {status_cls}">{status_icon} {"成功" if success else "失败"}</span></td>
          <td class="col-mono">{duration}ms</td>
          <td class="col-error">{message}</td>
        </tr>"""

    return f"""
    <div class="section-info">
      <span>执行时间: {timestamp}</span>
      <span>失败: {total_failures} &nbsp;|&nbsp; 修复: {repaired} &nbsp;|&nbsp; 未修复: {failed}</span>
    </div>

    {"<h3>策略分布</h3><div class='chip-row'>" + strategy_chips + "</div>" if strategy_chips else ""}

    {"<h3>策略决策</h3><div class='table-wrap'><table><thead><tr><th>测试用例</th><th>细分类</th><th>策略</th><th>评估分数</th></tr></thead><tbody>" + decision_rows + "</tbody></table></div>" if decision_rows else ""}

    {"<h3>修复详情</h3><div class='table-wrap'><table><thead><tr><th>测试用例</th><th>首选策略</th><th>最终策略</th><th>结果</th><th>耗时</th><th>说明</th></tr></thead><tbody>" + detail_rows + "</tbody></table></div>" if detail_rows else ""}
    """


# ── CSS ───────────────────────────────────────────────

def _get_css() -> str:
    return """
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; background: #f0f2f5; color: #1a1a1a; line-height: 1.6; }

  .header { background: linear-gradient(135deg, #1a237e 0%, #283593 50%, #1565c0 100%); color: #fff; padding: 28px 40px; display: flex; justify-content: space-between; align-items: center; }
  .header h1 { font-size: 22px; font-weight: 600; }
  .module-name { font-size: 14px; opacity: 0.8; margin-top: 2px; }
  .header-right { text-align: right; }
  .meta { font-size: 13px; opacity: 0.8; margin-top: 4px; }
  .overall-badge { display: inline-block; padding: 6px 20px; border-radius: 20px; font-size: 14px; font-weight: 700; letter-spacing: 1px; }
  .status-pass { background: #e8f5e9; color: #2e7d32; }
  .status-fail { background: #ffebee; color: #c62828; }

  .container { max-width: 1100px; margin: -20px auto 40px; padding: 0 20px; }

  /* 摘要卡片 */
  .summary-cards { display: flex; gap: 16px; margin-bottom: 20px; }
  .summary-card { flex: 1; background: #fff; border-radius: 10px; padding: 18px 22px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); border-top: 3px solid #ccc; }
  .card-green { border-top-color: #4caf50; }
  .card-red { border-top-color: #e53935; }
  .card-blue { border-top-color: #1565c0; }
  .card-orange { border-top-color: #ff9800; }
  .card-title { font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }
  .card-value { font-size: 30px; font-weight: 700; margin: 4px 0; }
  .card-detail { font-size: 12px; color: #999; }

  /* Tabs */
  .tabs { display: flex; gap: 0; background: #fff; border-radius: 10px 10px 0 0; box-shadow: 0 2px 8px rgba(0,0,0,0.06); overflow: hidden; margin-bottom: 0; }
  .tab-btn { flex: 1; padding: 14px 20px; border: none; background: #fff; font-size: 14px; font-weight: 600; color: #666; cursor: pointer; transition: all 0.2s; border-bottom: 3px solid transparent; display: flex; align-items: center; justify-content: center; gap: 8px; }
  .tab-btn:hover { background: #f8f9fa; color: #333; }
  .tab-btn.active { color: #1565c0; border-bottom-color: #1565c0; background: #e3f2fd; }

  .tab-content { background: #fff; border-radius: 0 0 10px 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); padding: 24px; margin-bottom: 20px; }

  .section-info { display: flex; gap: 20px; font-size: 13px; color: #888; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid #f0f0f0; }

  /* Badge */
  .badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; }
  .badge-green { background: #e8f5e9; color: #2e7d32; }
  .badge-red { background: #ffebee; color: #c62828; }
  .badge-orange { background: #fff3e0; color: #e65100; }
  .badge-gray { background: #f5f5f5; color: #999; }

  /* Layer chips */
  .layer-chips { display: flex; gap: 12px; margin-bottom: 16px; }
  .layer-chip { padding: 6px 14px; border-radius: 8px; font-size: 13px; display: flex; align-items: center; gap: 6px; }
  .layer-ui { background: #ede7f6; color: #5e35b1; }
  .layer-api { background: #e0f7fa; color: #00838f; }
  .layer-db { background: #fff3e0; color: #e65100; }
  .pass-dot, .fail-dot, .skip-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-left: 4px; }
  .pass-dot { background: #4caf50; }
  .fail-dot { background: #e53935; }
  .skip-dot { background: #ff9800; }

  /* Table */
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  thead th { background: #fafafa; padding: 10px 12px; text-align: left; font-weight: 600; color: #555; border-bottom: 2px solid #eee; font-size: 12px; text-transform: uppercase; letter-spacing: 0.3px; white-space: nowrap; }
  tbody td { padding: 10px 12px; border-bottom: 1px solid #f5f5f5; vertical-align: top; }
  .col-idx { width: 40px; text-align: center; color: #bbb; }
  .col-desc { max-width: 300px; word-break: break-all; }
  .col-mono { font-family: "SF Mono", Monaco, Consolas, monospace; font-size: 12px; }
  .col-error { font-size: 12px; color: #c62828; max-width: 250px; word-break: break-all; }

  /* Layer badge */
  .layer-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; }
  .layer-badge-ui { background: #ede7f6; color: #5e35b1; }
  .layer-badge-api { background: #e0f7fa; color: #00838f; }
  .layer-badge-db { background: #fff3e0; color: #e65100; }

  /* Status pill */
  .status-pill { display: inline-flex; align-items: center; gap: 4px; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; white-space: nowrap; }
  .status-passed { background: #e8f5e9; color: #2e7d32; }
  .status-failed { background: #ffebee; color: #c62828; }
  .status-skipped { background: #fff3e0; color: #e65100; }
  .status-error { background: #fce4ec; color: #ad1457; }

  /* Row highlight */
  tr.row-failed { background: #fff8f8; }
  tr.row-error { background: #fef5f8; }
  .error-msg { margin-top: 4px; font-size: 11px; color: #c62828; background: #fff0f0; padding: 4px 8px; border-radius: 4px; }

  /* Category tag */
  .category-tag { display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 11px; font-weight: 600; }
  .cat-assertion { background: #e3f2fd; color: #1565c0; }
  .cat-assertion_value { background: #e3f2fd; color: #1565c0; }
  .cat-selector { background: #fce4ec; color: #c62828; }
  .cat-timeout { background: #fff3e0; color: #e65100; }
  .cat-env_auth { background: #f3e5f5; color: #7b1fa2; }
  .cat-network { background: #e8f5e9; color: #2e7d32; }

  /* Strategy tag */
  .strategy-tag { display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 11px; font-weight: 600; background: #e8eaf6; color: #283593; }
  .chip-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
  .strategy-chip { padding: 4px 12px; background: #e8eaf6; color: #283593; border-radius: 16px; font-size: 12px; font-weight: 600; }

  .file-info { font-size: 11px; color: #888; word-break: break-all; }
  .link { color: #1565c0; text-decoration: none; font-size: 12px; }
  .link:hover { text-decoration: underline; }

  .empty-state { text-align: center; padding: 40px; color: #bbb; font-size: 14px; }
  .no-data { text-align: center; padding: 60px 20px; color: #999; font-size: 15px; background: #fff; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
  .no-data code { background: #f5f5f5; padding: 2px 8px; border-radius: 4px; font-size: 13px; }

  h3 { font-size: 14px; color: #555; margin: 20px 0 10px; padding-bottom: 6px; border-bottom: 1px solid #f0f0f0; }
  h3:first-child { margin-top: 0; }

  .footer { text-align: center; padding: 20px; font-size: 12px; color: #aaa; }
"""
