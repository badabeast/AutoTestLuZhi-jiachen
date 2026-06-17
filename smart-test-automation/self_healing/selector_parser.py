"""链式选择器表达式解析器

独创性：完整解析 Playwright 语义定位器的链式调用，
包括 .nth()/.first/.last/.filter() 等，
支持任意深度嵌套的序列化和反序列化。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class MethodCall:
    """方法调用节点"""
    method: str          # 方法名，如 "get_by_role", "nth", "filter"
    args: list = field(default_factory=list)       # 位置参数
    kwargs: dict = field(default_factory=dict)      # 关键字参数

    def to_string(self) -> str:
        """序列化为字符串"""
        # 属性访问（.first / .last）无括号
        if self.method in ("first", "last") and not self.args and not self.kwargs:
            return self.method

        def _quote_str(v: str) -> str:
            """用双引号包裹字符串，内部双引号转义为 \\"，与 Playwright 风格一致"""
            escaped = v.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'

        parts = []
        parts.extend(_quote_str(a) if isinstance(a, str) else str(a) for a in self.args)
        parts.extend(f"{k}={_quote_str(v)}" if isinstance(v, str) else f"{k}={v}" for k, v in self.kwargs.items())
        return f"{self.method}({', '.join(parts)})"


@dataclass
class SelectorExpr:
    """完整的链式选择器表达式"""
    calls: list[MethodCall] = field(default_factory=list)

    @property
    def base_selector(self) -> str:
        """返回第一个方法调用（基础选择器）"""
        return self.calls[0].to_string() if self.calls else ""

    @property
    def chain_suffix(self) -> str:
        """返回链式后缀（.nth(1), .first 等）"""
        return "." + ".".join(c.to_string() for c in self.calls[1:]) if len(self.calls) > 1 else ""

    def to_string(self) -> str:
        """序列化为完整字符串"""
        return ".".join(c.to_string() for c in self.calls)

    def replace_base(self, new_base: str) -> "SelectorExpr":
        """替换基础选择器，保留链式后缀"""
        new_calls = [MethodCall(method="__replaced__", args=[new_base])] + self.calls[1:]
        return SelectorExpr(calls=new_calls)


def parse_selector(selector_str: str) -> SelectorExpr:
    """解析链式选择器字符串为结构化表达式

    支持的格式：
    - get_by_role("textbox", name="请输入")
    - get_by_role("textbox", name="请输入").nth(1)
    - locator(".btn-entrance").first
    - get_by_text("提交").filter(has_text="确认")
    - get_by_label("用户名").nth(0).click()  # 忽略终端操作
    """
    calls = []
    # 拆分链式调用
    chain_parts = _split_chain(selector_str.strip())

    for part in chain_parts:
        method_call = _parse_method_call(part.strip())
        if method_call:
            # 过滤掉终端操作（click/fill/check等）
            if method_call.method not in ("click", "fill", "check", "uncheck",
                                           "type", "press", "select_option",
                                           "set_input_files", "hover", "focus",
                                           "blur", "tap", "dispatch_event"):
                calls.append(method_call)

    return SelectorExpr(calls=calls)


def _split_chain(s: str) -> list[str]:
    """拆分链式调用，处理括号嵌套"""
    parts = []
    current = []
    depth = 0

    for char in s:
        if char == '(':
            depth += 1
            current.append(char)
        elif char == ')':
            depth -= 1
            current.append(char)
        elif char == '.' and depth == 0:
            # 顶层点号，拆分
            if current:
                parts.append(''.join(current))
                current = []
        else:
            current.append(char)

    if current:
        parts.append(''.join(current))

    return parts


def _parse_method_call(s: str) -> MethodCall | None:
    """解析单个方法调用"""
    # 匹配 method_name(args)
    match = re.match(r'^(\w+)\((.*)\)$', s, re.DOTALL)
    if not match:
        # 处理属性访问（如 .first, .last）
        if s in ('first', 'last'):
            return MethodCall(method=s)
        return None

    method = match.group(1)
    args_str = match.group(2).strip()

    if not args_str:
        return MethodCall(method=method)

    args, kwargs = _parse_args(args_str)
    return MethodCall(method=method, args=args, kwargs=kwargs)


def _parse_args(args_str: str) -> tuple[list, dict]:
    """解析参数列表，支持位置参数和关键字参数"""
    args = []
    kwargs = {}

    # 拆分参数（处理字符串内的逗号）
    parts = _split_args(args_str)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # 检查是否是关键字参数
        kw_match = re.match(r'^(\w+)\s*=\s*(.+)$', part)
        if kw_match:
            key = kw_match.group(1)
            value = _parse_value(kw_match.group(2).strip())
            kwargs[key] = value
        else:
            args.append(_parse_value(part))

    return args, kwargs


def _split_args(s: str) -> list[str]:
    """拆分参数列表，处理字符串和嵌套括号"""
    parts = []
    current = []
    depth = 0
    in_string = False
    string_char = None

    for char in s:
        if in_string:
            current.append(char)
            if char == string_char:
                in_string = False
            continue

        if char in ('"', "'"):
            in_string = True
            string_char = char
            current.append(char)
        elif char == '(':
            depth += 1
            current.append(char)
        elif char == ')':
            depth -= 1
            current.append(char)
        elif char == ',' and depth == 0:
            parts.append(''.join(current))
            current = []
        else:
            current.append(char)

    if current:
        parts.append(''.join(current))

    return parts


def _parse_value(s: str):
    """解析单个值"""
    s = s.strip()

    # 字符串
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]

    # 布尔
    if s == 'True':
        return True
    if s == 'False':
        return False

    # 数字
    try:
        if '.' in s:
            return float(s)
        return int(s)
    except ValueError:
        return s  # 作为原始字符串返回
