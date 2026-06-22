"""AST精准源码回写模块

独创性：临时自愈+源码永久固化双闭环
- 运行时：HealingLocator 临时替换选择器，测试继续执行
- 源码级：SourcePatcher 通过AST精准回写，永久修复源文件
- 支持角色/文本类型选择器（get_by_role/get_by_text/get_by_label），
  healer内置SourcePatcher不支持这些类型，只能处理CSS selector
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Optional

from .selector_parser import parse_selector, MethodCall, SelectorExpr

logger = logging.getLogger(__name__)


class SourcePatcher:
    """AST精准回写：将失效选择器替换为修复后的选择器

    核心策略：
    策略1：直接字符串替换（快速，覆盖90%场景）
    策略1b：宽松字符串替换（处理引号差异、空格差异）
    策略2：AST精准替换（处理格式差异、空白差异等）

    注意：使用 selector_parser 的 parse_selector / SelectorExpr.to_string
    进行序列化，而不是自行拼接。
    """

    @staticmethod
    def patch_file(file_path: str, old_selector: str, new_selector: str) -> bool:
        """在源文件中替换失效选择器

        Args:
            file_path: 源文件路径
            old_selector: 失效的完整选择器表达式
            new_selector: 修复后的完整选择器表达式

        Returns:
            bool: 是否成功替换
        """
        path = Path(file_path)
        if not path.exists():
            logger.warning("源文件不存在: %s", file_path)
            return False

        source = path.read_text(encoding="utf-8")

        # 策略1：直接字符串替换
        if old_selector in source:
            return SourcePatcher._string_replace(file_path, source, old_selector, new_selector)

        # 策略1b：宽松字符串替换（处理引号差异）
        old_parsed = parse_selector(old_selector)
        new_parsed = parse_selector(new_selector)

        if SourcePatcher._fuzzy_string_replace(file_path, source, old_parsed, new_parsed):
            return True

        # 策略2：AST精准替换
        return SourcePatcher._ast_replace(file_path, source, old_parsed, new_parsed)

    @staticmethod
    def _string_replace(file_path: str, source: str, old_sel: str, new_sel: str) -> bool:
        """直接字符串替换 + 备份"""
        path = Path(file_path)
        backup = file_path + ".bak"
        if not Path(backup).exists():
            Path(backup).write_text(source, encoding="utf-8")
        new_source = source.replace(old_sel, new_sel)
        if new_source == source:
            return False
        path.write_text(new_source, encoding="utf-8")
        logger.info("字符串替换成功: %s → %s", old_sel, new_sel)
        return True

    @staticmethod
    def _fuzzy_string_replace(
        file_path: str,
        source: str,
        old_parsed: SelectorExpr,
        new_parsed: SelectorExpr,
    ) -> bool:
        """宽松字符串替换：尝试不同的引号和空格组合"""
        variants = SourcePatcher._generate_variants(old_parsed)
        new_canonical = new_parsed.to_string()

        for variant in variants:
            if variant in source:
                path = Path(file_path)
                backup = file_path + ".bak"
                if not Path(backup).exists():
                    Path(backup).write_text(source, encoding="utf-8")
                new_source = source.replace(variant, new_canonical)
                path.write_text(new_source, encoding="utf-8")
                logger.info("宽松字符串替换成功: %s → %s", variant, new_canonical)
                return True
        return False

    @staticmethod
    def _generate_variants(expr: SelectorExpr) -> list[str]:
        """生成选择器表达式的格式变体

        考虑：单双引号交替、参数间空格差异
        """
        variants: list[str] = []

        # 标准序列化（双引号）
        variants.append(expr.to_string())

        # 单引号版本
        variants.append(SourcePatcher._with_single_quotes(expr))

        return variants

    @staticmethod
    def _with_single_quotes(expr: SelectorExpr) -> str:
        """生成使用单引号的选择器表达式"""
        def fmt_val(v) -> str:
            if isinstance(v, str):
                escaped = v.replace("'", "\\'")
                return f"'{escaped}'"
            return str(v)

        def fmt_call(call: MethodCall) -> str:
            parts = [fmt_val(a) for a in call.args]
            parts += [f"{k}={fmt_val(v)}" for k, v in call.kwargs.items()]
            return f"{call.method}({', '.join(parts)})"

        # 基础选择器
        result = fmt_call(expr.calls[0]) if expr.calls else ""
        # 链式后缀
        for call in expr.calls[1:]:
            result += "." + fmt_call(call)
        return result

    @staticmethod
    def _ast_replace(
        file_path: str,
        source: str,
        old_parsed: SelectorExpr,
        new_parsed: SelectorExpr,
    ) -> bool:
        """AST级别替换：精确匹配方法调用节点"""
        try:
            tree = ast.parse(source)
            patcher = _SelectorASTPatcher(old_parsed, new_parsed)
            new_tree = patcher.visit(tree)

            if patcher.patched_count > 0:
                ast.fix_missing_locations(new_tree)
                # Python 3.9+ 使用 ast.unparse，否则用 astunparse
                try:
                    new_source = ast.unparse(new_tree)
                except AttributeError:
                    import astunparse
                    new_source = astunparse.unparse(new_tree)
                backup = file_path + ".bak"
                if not Path(backup).exists():
                    Path(backup).write_text(source, encoding="utf-8")
                Path(file_path).write_text(new_source, encoding="utf-8")
                logger.info("AST替换成功，共替换 %d 处", patcher.patched_count)
                return True
        except Exception as e:
            logger.warning("AST替换失败: %s", e)
        return False


class _SelectorASTPatcher(ast.NodeTransformer):
    """AST访问器：定位匹配的链式选择器调用并替换"""

    def __init__(self, old_parsed: SelectorExpr, new_parsed: SelectorExpr):
        self.old_parsed = old_parsed
        self.new_parsed = new_parsed
        self.patched_count = 0

    def visit_Call(self, node: ast.Call) -> ast.Call:
        """访问Call节点，检查是否匹配选择器链"""
        self.generic_visit(node)

        # 尝试匹配链式选择器调用
        if self._matches_selector_chain(node):
            # 构建新的AST替换节点
            new_node = self._build_new_chain(node)
            self.patched_count += 1
            return new_node

        return node

    def _matches_selector_chain(self, node: ast.Call) -> bool:
        """检查AST Call节点是否匹配old_parsed的链式调用

        从最外层向内层逐级匹配方法名和参数，
        因为在AST中 page.get_by_role("button").nth(1) 的结构是：
        Call(func=Attribute(value=Call(func=Attribute(value=Name('page'), attr='get_by_role'), ...), attr='nth'), ...)
        即最外层是链式的最后一个方法调用。
        """
        calls = self.old_parsed.calls
        current = node

        # 从后往前匹配链式调用（AST中 .nth(1) 是最外层Call）
        for i in range(len(calls) - 1, 0, -1):
            if not isinstance(current, ast.Call):
                return False
            if not isinstance(current.func, ast.Attribute):
                return False
            if current.func.attr != calls[i].method:
                return False
            # 校验方法参数
            if not self._matches_call_args(current, calls[i]):
                return False
            current = current.func.value

        # 匹配基础选择器（第一个call）
        if not isinstance(current, ast.Call):
            return False
        if not isinstance(current.func, ast.Attribute):
            return False
        if current.func.attr != calls[0].method:
            return False

        return self._matches_call_args(current, calls[0])

    def _matches_call_args(self, call_node: ast.Call, method_call: MethodCall) -> bool:
        """匹配单个方法调用的参数"""
        # 位置参数
        if len(call_node.args) != len(method_call.args):
            return False

        for arg_node, arg_val in zip(call_node.args, method_call.args):
            if isinstance(arg_node, ast.Constant):
                if arg_node.value != arg_val:
                    return False
            elif isinstance(arg_node, ast.Str):  # Python 3.7 兼容
                if arg_node.s != arg_val:
                    return False

        # 关键字参数
        call_kwargs = {kw.arg: kw.value for kw in call_node.keywords if kw.arg}
        for k, v in method_call.kwargs.items():
            if k not in call_kwargs:
                return False
            kw_node = call_kwargs[k]
            if isinstance(kw_node, ast.Constant):
                if kw_node.value != v:
                    return False
            elif isinstance(kw_node, ast.Str):
                if kw_node.s != v:
                    return False

        return True

    def _build_new_chain(self, original_node: ast.Call) -> ast.Call:
        """基于new_parsed构建新的AST调用链

        策略：
        1. 提取原始接收者（如 page / self.page）
        2. 用 _obj_ 占位符拼接 new_parsed 的字符串表达式
        3. 解析为AST后，将 _obj_ 替换回原始接收者
        """
        # 保留原始的接收者（page / self.page 等）
        receiver = None
        current = original_node
        # 找到最内层的接收者
        while isinstance(current, ast.Call) and isinstance(current.func, ast.Attribute):
            current = current.func.value
        receiver = current

        """从new_parsed.calls构建新链：
        先用占位符 _obj_ 作为前缀拼接完整表达式字符串，
        然后解析并将 _obj_ 替换为原始 receiver"""
        new_sel_str = self.new_parsed.to_string()
        expr_str = f"_obj_.{new_sel_str}"
        try:
            expr = ast.parse(expr_str, mode="eval")
            new_node = expr.body
            # 替换 _obj_ 为原始receiver
            self._replace_receiver(new_node, receiver)
            return new_node
        except SyntaxError:
            return original_node

    def _replace_receiver(self, node: ast.AST, receiver: ast.expr) -> None:
        """递归替换AST中的_obj_ Name节点为原始receiver

        使用 ast.walk 遍历所有子节点，找到 Attribute.value 为 _obj_ Name 的节点，
        将其 value 属性替换为 receiver。ast.walk 返回的是节点引用，
        修改其属性会直接影响原树结构。
        """
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute):
                if isinstance(child.value, ast.Name) and child.value.id == "_obj_":
                    child.value = receiver
