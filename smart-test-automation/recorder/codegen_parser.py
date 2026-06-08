#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AST 解析器，从 Playwright codegen 输出中提取结构化操作序列。

将 codegen 生成的 Python-pytest 脚本解析为 UIOperation 列表，
例如 page.get_by_role('button', name='提交').click()
会被提取为 action="click", selector_type="role", selector_value="button"。

解析基于 Python ast 模块，比正则匹配更准确可靠。
"""

import ast
import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class UIOperation:
    """UI 操作记录"""
    step_index: int              # 步骤序号
    action: str                  # click / fill / select / navigate / press / check / hover
    selector_type: str           # role / text / test_id / label / placeholder / css / xpath
    selector_value: str          # 选择器主参数（如 role 名、testid 值）
    selector_name: Optional[str] = None  # name 参数（如 getByRole 的 name）
    selector_exact: Optional[bool] = None  # exact 参数
    value: Optional[str] = None  # fill 值 / select 选项 / press 按键
    raw_line: str = ""           # 原始代码行（用于 ScriptTransformer 修补）
    line_number: int = 0         # 源码行号


# 选择器方法映射：Python API 方法名 → 选择器类型
SELECTOR_METHOD_MAP = {
    "get_by_role": "role",
    "get_by_text": "text",
    "get_by_test_id": "test_id",
    "get_by_label": "label",
    "get_by_placeholder": "placeholder",
    "get_by_title": "title",
    "locator": "css",
}

# 操作方法映射：链式调用的最终方法 → 操作类型
ACTION_METHOD_MAP = {
    "click": "click",
    "dblclick": "dblclick",
    "fill": "fill",
    "type": "type",
    "select_option": "select",
    "check": "check",
    "uncheck": "uncheck",
    "hover": "hover",
    "press": "press",
    "set_input_files": "upload",
    "goto": "navigate",
    "wait_for_url": "wait_url",
}

# 操作方法有 value 参数的
VALUE_ACTIONS = {"fill", "type", "press", "select_option", "set_input_files", "goto"}


class RecordingASTParser:
    """用 AST 解析 Playwright codegen 生成的 Python-pytest 脚本。"""

    def parse(self, script_path: str) -> List[UIOperation]:
        """解析 codegen 生成的 Python 脚本。

        :param script_path: codegen 生成的脚本文件路径
        :type script_path: str
        :return: 提取的 UI 操作序列
        :rtype: List[UIOperation]
        """
        with open(script_path, 'r', encoding='utf-8') as f:
            source = f.read()

        tree = ast.parse(source)
        operations: List[UIOperation] = []

        # 遍历所有函数定义（test 函数）
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_") or node.name == "run":
                    self._parse_function(node, source, operations)

        # 如果没有 test 函数，尝试解析所有表达式
        if not operations:
            for node in ast.walk(tree):
                if isinstance(node, ast.Expr):
                    op = self._parse_expr(node, source)
                    if op:
                        op.step_index = len(operations)
                        operations.append(op)

        # 最后尝试行级解析（兜底，处理 AST 无法解析的复杂调用链）
        if not operations:
            operations = self._line_based_parse(source)

        return operations

    def _parse_function(self, func_node, source: str, operations: List[UIOperation]):
        """解析一个 test 函数体中的所有 UI 操作"""
        for stmt in func_node.body:
            # 处理简单表达式语句
            if isinstance(stmt, ast.Expr):
                op = self._parse_expr(stmt, source)
                if op:
                    op.step_index = len(operations)
                    operations.append(op)

            # 处理 with 语句（如 with page.expect_response...）
            elif isinstance(stmt, ast.With):
                for item in stmt.items:
                    # with 语句的上下文表达式不提取为 UI 操作
                    pass
                for body_stmt in stmt.body:
                    if isinstance(body_stmt, ast.Expr):
                        op = self._parse_expr(body_stmt, source)
                        if op:
                            op.step_index = len(operations)
                            operations.append(op)

    def _parse_expr(self, expr_node, source: str) -> Optional[UIOperation]:
        """解析一个表达式语句"""
        call = expr_node.value
        if not isinstance(call, ast.Call):
            return None
        return self._parse_call_chain(call, source)

    def _parse_call_chain(self, call: ast.Call, source: str) -> Optional[UIOperation]:
        """解析链式调用：page.get_by_role(...).action(...)

        结构:
          Call(func=Call(func=Attribute(value=Call(func=Attribute(...))))

        我们需要：
        1. 找到最内层的 "page.xxx" 或 "page.get_by_xxx" 选择器调用
        2. 找到最外层的 ".click()" / ".fill()" 等操作调用
        """
        # 递归解包调用链，收集所有方法调用
        chain = self._unpack_call_chain(call)

        if not chain:
            return None

        # 找选择器调用和操作调用
        selector_info = None
        action_info = None
        value_info = None

        for i, (method_name, args, keywords) in enumerate(chain):
            # 选择器方法：get_by_role, get_by_text, locator 等
            if method_name in SELECTOR_METHOD_MAP and selector_info is None:
                selector_info = self._extract_selector(method_name, args, keywords)

            # 操作方法：click, fill, select_option 等
            if method_name in ACTION_METHOD_MAP:
                action_info = ACTION_METHOD_MAP[method_name]
                if method_name in VALUE_ACTIONS and args:
                    value_info = self._extract_value(args[0])

        # 特殊处理：page.goto(url) — 没有 chain，直接是 page.goto
        if not selector_info and action_info == "navigate" and chain:
            method_name, args, keywords = chain[0]
            if method_name == "goto" and args:
                url = self._extract_value(args[0])
                return UIOperation(
                    step_index=0,
                    action="navigate",
                    selector_type="url",
                    selector_value=url or "",
                    value=url,
                    raw_line=ast.get_source_segment(source, call) or "",
                )

        if not selector_info or not action_info:
            return None

        op = UIOperation(
            step_index=0,  # 后续由调用者设置
            action=action_info,
            selector_type=selector_info["type"],
            selector_value=selector_info["value"],
            selector_name=selector_info.get("name"),
            selector_exact=selector_info.get("exact"),
            value=value_info,
            raw_line=ast.get_source_segment(source, call) or "",
        )

        return op

    def _unpack_call_chain(self, call: ast.Call) -> List[tuple]:
        """解包链式调用，返回 [(method_name, args, keywords), ...]"""
        chain = []
        current = call

        while isinstance(current, ast.Call):
            # 提取方法名
            func = current.func

            if isinstance(func, ast.Attribute):
                method_name = func.attr
                args = current.args
                keywords = current.keywords
                chain.append((method_name, args, keywords))

                # 继续解包
                if isinstance(func.value, ast.Call):
                    current = func.value
                elif isinstance(func.value, ast.Attribute):
                    # page.xxx 模式，不再有更深的调用链
                    break
                elif isinstance(func.value, ast.Name):
                    # 简单变量名，如 page.xxx()
                    break
                else:
                    break
            elif isinstance(func, ast.Name):
                # 直接函数调用（如 goto(url)）
                method_name = func.id
                args = current.args
                keywords = current.keywords
                chain.append((method_name, args, keywords))
                break
            else:
                break

        # 反转顺序：从内到外 → 从外到内
        chain.reverse()
        return chain

    def _extract_selector(self, method_name: str, args: list, keywords: list) -> Dict[str, Any]:
        """从选择器调用中提取选择器信息

        Args:
            method_name: 方法名（如 "get_by_role"）
            args: 位置参数
            keywords: 关键字参数

        Returns:
            dict: {type, value, name, exact}
        """
        selector_type = SELECTOR_METHOD_MAP.get(method_name, "css")

        result = {"type": selector_type, "value": "", "name": None, "exact": None}

        if selector_type == "role":
            # get_by_role('button', name='提交', exact=True)
            if args:
                result["value"] = self._extract_value(args[0]) or ""
            for kw in keywords:
                if kw.arg == "name":
                    result["name"] = self._extract_value(kw.value) or ""
                elif kw.arg == "exact":
                    result["exact"] = self._extract_bool(kw.value)

        elif selector_type in ("text", "test_id", "label", "placeholder", "title"):
            # get_by_text('提交') / get_by_test_id('btn-submit')
            if args:
                result["value"] = self._extract_value(args[0]) or ""
            for kw in keywords:
                if kw.arg == "exact":
                    result["exact"] = self._extract_bool(kw.value)

        elif selector_type == "css":
            # locator('#submit-btn') 或 locator('text=xxx')
            if args:
                result["value"] = self._extract_value(args[0]) or ""

        return result

    def _extract_value(self, node) -> Optional[str]:
        """从 AST 节点提取字符串值"""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return str(node.value)
        # f-string 或模板字符串
        return None

    def _extract_bool(self, node) -> Optional[bool]:
        """从 AST 节点提取布尔值"""
        if isinstance(node, ast.Constant) and isinstance(node.value, bool):
            return node.value
        return None

    def _line_based_parse(self, source: str) -> List[UIOperation]:
        """行级兜底解析：当 AST 解析失败时，用正则逐行提取

        这是最后的兜底策略，处理 AST 无法解析的复杂链式调用
        """
        operations = []
        lines = source.split('\n')

        # 匹配 page.get_by_xxx(...).action(...) 模式
        patterns = [
            # page.get_by_role('button', name='xxx').click()
            r'page\.get_by_role\(["\'](\w+)["\'](?:,\s*name=["\']([^"\']+)["\'])?(?:,\s*exact=(True|False))?\)\.(click|fill|check|hover|dblclick|press|select_option)\((?:["\']([^"\']*)["\'])?\)',
            # page.get_by_text('xxx').click()
            r'page\.get_by_text\(["\']([^"\']+)["\'](?:,\s*exact=(True|False))?\)\.(click|fill|hover)\((?:["\']([^"\']*)["\'])?\)',
            # page.get_by_test_id('xxx').click()
            r'page\.get_by_test_id\(["\']([^"\']+)["\']\)\.(click|fill|check|hover)\((?:["\']([^"\']*)["\'])?\)',
            # page.get_by_label('xxx').fill('yyy')
            r'page\.get_by_label\(["\']([^"\']+)["\']\)\.(click|fill)\((?:["\']([^"\']*)["\'])?\)',
            # page.get_by_placeholder('xxx').fill('yyy')
            r'page\.get_by_placeholder\(["\']([^"\']+)["\']\)\.(click|fill)\((?:["\']([^"\']*)["\'])?\)',
            # page.locator('xxx').click()
            r'page\.locator\(["\']([^"\']+)["\']\)\.(click|fill|check|hover|select_option)\((?:["\']([^"\']*)["\'])?\)',
            # page.goto('xxx')
            r'page\.goto\(["\']([^"\']+)["\']\)',
        ]

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or stripped.startswith('import'):
                continue

            for pattern in patterns:
                match = re.search(pattern, stripped)
                if match:
                    groups = match.groups()

                    if 'goto' in pattern:
                        op = UIOperation(
                            step_index=len(operations),
                            action="navigate",
                            selector_type="url",
                            selector_value=groups[0],
                            value=groups[0],
                            raw_line=stripped,
                            line_number=line_num,
                        )
                    elif 'get_by_role' in pattern:
                        op = UIOperation(
                            step_index=len(operations),
                            action=groups[3] if len(groups) > 3 else "click",
                            selector_type="role",
                            selector_value=groups[0],
                            selector_name=groups[1] if len(groups) > 1 else None,
                            selector_exact=groups[2] == 'True' if len(groups) > 2 and groups[2] else None,
                            value=groups[4] if len(groups) > 4 else None,
                            raw_line=stripped,
                            line_number=line_num,
                        )
                    elif 'get_by_text' in pattern:
                        op = UIOperation(
                            step_index=len(operations),
                            action=groups[2] if len(groups) > 2 else "click",
                            selector_type="text",
                            selector_value=groups[0],
                            selector_exact=groups[1] == 'True' if len(groups) > 1 and groups[1] else None,
                            value=groups[3] if len(groups) > 3 else None,
                            raw_line=stripped,
                            line_number=line_num,
                        )
                    elif 'get_by_test_id' in pattern:
                        op = UIOperation(
                            step_index=len(operations),
                            action=groups[1],
                            selector_type="test_id",
                            selector_value=groups[0],
                            value=groups[2] if len(groups) > 2 else None,
                            raw_line=stripped,
                            line_number=line_num,
                        )
                    elif 'get_by_label' in pattern:
                        op = UIOperation(
                            step_index=len(operations),
                            action=groups[1],
                            selector_type="label",
                            selector_value=groups[0],
                            value=groups[2] if len(groups) > 2 else None,
                            raw_line=stripped,
                            line_number=line_num,
                        )
                    elif 'get_by_placeholder' in pattern:
                        op = UIOperation(
                            step_index=len(operations),
                            action=groups[1],
                            selector_type="placeholder",
                            selector_value=groups[0],
                            value=groups[2] if len(groups) > 2 else None,
                            raw_line=stripped,
                            line_number=line_num,
                        )
                    elif 'locator' in pattern:
                        op = UIOperation(
                            step_index=len(operations),
                            action=groups[1],
                            selector_type="css",
                            selector_value=groups[0],
                            value=groups[2] if len(groups) > 2 else None,
                            raw_line=stripped,
                            line_number=line_num,
                        )
                    else:
                        continue

                    operations.append(op)
                    break

        return operations