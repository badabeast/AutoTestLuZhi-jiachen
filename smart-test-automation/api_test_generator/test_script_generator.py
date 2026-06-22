# -*- coding: utf-8 -*-
"""测试脚本生成器 - 从TimelineMapping和ParamChain生成pytest接口测试脚本"""

import os
import re
import json
from datetime import datetime
from typing import List, Optional, Any

from .models import TimelineMapping, ParamChain, APIStep, TestCase
from .utils import field_path_to_var_name, extract_leaf_fields


class TestScriptGenerator:
    """生成pytest + requests接口测试脚本"""

    def generate_test(
        self,
        module_name: str,
        mappings: List[TimelineMapping],
        chains: List[ParamChain],
    ) -> str:
        """生成完整的pytest测试脚本

        Args:
            module_name: 模块名称
            mappings: UI操作→API调用映射列表
            chains: 参数传递链

        Returns:
            str: 生成的Python测试脚本内容
        """
        # 1. 把TimelineMapping转成APIStep
        steps = self._build_steps(mappings)

        # 2. 用ParamChain填充参数传递
        steps = self._apply_chains(steps, chains)

        # 3. 生成Python代码
        return self._render_script(module_name, steps)

    def _build_steps(self, mappings: List[TimelineMapping]) -> List[APIStep]:
        """把TimelineMapping转成APIStep列表"""
        steps: List[APIStep] = []
        step_index = 0

        for mapping in mappings:
            # 跳过没有API调用的UI操作
            if not mapping.api_calls:
                continue

            op_desc = self._describe_operation(mapping.ui_operation)

            for api_call in mapping.api_calls:
                # 提取响应中可提取的变量（ID类字段）
                extract_vars = {}
                if api_call.response_body and isinstance(api_call.response_body, dict):
                    fields = extract_leaf_fields(api_call.response_body)
                    for field_path, value in fields:
                        if self._is_extractable(value, field_path):
                            var_name = field_path_to_var_name(field_path)
                            extract_vars[var_name] = field_path

                steps.append(APIStep(
                    step_index=step_index,
                    method=api_call.method,
                    url=api_call.path,
                    headers={},
                    body=api_call.request_body,
                    expected_status=api_call.status,
                    extract_vars=extract_vars,
                    depends_on=[],
                ))
                step_index += 1

        return steps

    def _apply_chains(self, steps: List[APIStep], chains: List[ParamChain]) -> List[APIStep]:
        """用参数传递链填充步骤间的参数依赖

        如果某个步骤的请求体里有字段X，而另一个步骤的响应里有相同值的字段Y，
        则标记这个步骤依赖那个步骤提取的变量。
        """
        # 建立 source_api → steps 的索引
        api_to_steps = {}
        for step in steps:
            key = f"{step.method} {step.url}"
            if key not in api_to_steps:
                api_to_steps[key] = []
            api_to_steps[key].append(step)

        for chain in chains:
            # 找到 target 步骤
            target_steps = api_to_steps.get(chain.target_api, [])
            for target_step in target_steps:
                # 找到 source 步骤
                source_steps = api_to_steps.get(chain.source_api, [])
                for source_step in source_steps:
                    # 确保 source 在 target 之前
                    if source_step.step_index >= target_step.step_index:
                        continue

                    # source_step的响应字段应该被提取为变量
                    source_var = field_path_to_var_name(chain.source_field)

                    # 如果source_step还没有提取这个变量，添加它
                    if source_var not in source_step.extract_vars:
                        source_step.extract_vars[source_var] = chain.source_field

                    # target_step依赖这个变量
                    if source_var not in target_step.depends_on:
                        target_step.depends_on.append(source_var)

        return steps

    def _render_script(self, module_name: str, steps: List[APIStep]) -> str:
        """渲染pytest测试脚本"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            '# -*- coding: utf-8 -*-',
            f'"""接口自动化测试 - {module_name}',
            f'自动生成时间: {timestamp}',
            '',
            '从UI录制数据自动生成，包含接口间参数传递。',
            '运行: pytest api_test.py -v',
            '"""',
            '',
            'import os',
            'import json',
            'import requests',
            'import pytest',
            '',
            '',
            'BASE_URL = os.environ.get("WEB_DEMAND_URL", "")',
            '',
            '',
            '@pytest.fixture(scope="session")',
            'def api():',
            '    """HTTP会话，自动注入登录Cookie"""',
            '    s = requests.Session()',
            '    s.verify = False',
            '    storage_path = "login_state/storage_state.json"',
            '    if os.path.exists(storage_path):',
            '        with open(storage_path) as f:',
            '            state = json.load(f)',
            '        for cookie in state.get("cookies", []):',
            '            s.cookies.set(',
            '                cookie["name"],',
            '                cookie["value"],',
            '                domain=cookie.get("domain", ""),',
            '            )',
            '    return s',
            '',
            '',
            f'def test_{module_name}(api):',
            f'    """{module_name} 接口测试用例"""',
        ]

        # 生成每个步骤
        for step in steps:
            # 步骤注释
            lines.append(f'')
            lines.append(f'    # Step {step.step_index + 1}: {step.method} {step.url}')

            # 构建请求
            var_prefix = f"resp{step.step_index + 1}"

            if step.method == "GET":
                lines.append(f'    {var_prefix} = api.get(f"{{BASE_URL}}{step.url}")')
            elif step.method == "POST":
                if step.body:
                    body_str = self._format_body(step.body, step.depends_on)
                    lines.append(f'    {var_prefix} = api.post(f"{{BASE_URL}}{step.url}", json={body_str})')
                else:
                    lines.append(f'    {var_prefix} = api.post(f"{{BASE_URL}}{step.url}")')
            elif step.method == "PUT":
                if step.body:
                    body_str = self._format_body(step.body, step.depends_on)
                    lines.append(f'    {var_prefix} = api.put(f"{{BASE_URL}}{step.url}", json={body_str})')
                else:
                    lines.append(f'    {var_prefix} = api.put(f"{{BASE_URL}}{step.url}")')
            elif step.method == "DELETE":
                lines.append(f'    {var_prefix} = api.delete(f"{{BASE_URL}}{step.url}")')
            else:
                lines.append(f'    {var_prefix} = api.request("{step.method}", f"{{BASE_URL}}{step.url}")')

            # 断言状态码
            lines.append(f'    assert {var_prefix}.status_code == {step.expected_status}')

            # 提取变量
            if step.extract_vars:
                for var_name, field_path in step.extract_vars.items():
                    jsonpath = self._field_path_to_jsonpath(field_path)
                    lines.append(f'    {var_name} = {var_prefix}.json(){jsonpath}')

        # 总结
        lines.append('')
        lines.append(f'    # 断言全部完成')
        lines.append(f'    print(f"✅ {module_name} 接口测试通过，共 {len(steps)} 步")')

        return '\n'.join(lines) + '\n'

    def _describe_operation(self, op) -> str:
        """把UI操作描述成可读的注释"""
        action = op.action
        name = op.selector_name or op.selector_value or ""
        value = op.value or ""

        if action == "navigate":
            return f"导航到页面"
        elif action == "click":
            return f"点击 {name}"
        elif action == "fill":
            return f"填写 {name} = {value[:20]}"
        elif action == "check":
            return f"勾选 {name}"
        elif action == "press":
            return f"按键 {value}"
        elif action == "select":
            return f"选择 {name} = {value}"
        else:
            return f"{action} {name}"

    def _is_extractable(self, value: Any, field_path: str) -> bool:
        """判断是否值得提取为变量"""
        from .utils import is_meaningful_value
        if not is_meaningful_value(value):
            return False
        # 字段名包含ID类关键词
        id_keywords = {'id', 'Id', 'ID', 'uuid', 'code', 'no', 'number', 'token', 'key'}
        return any(kw in field_path for kw in id_keywords)

    def _format_body(self, body: Any, depends_on: List[str]) -> str:
        """格式化请求体，把依赖的变量替换为变量引用"""
        if not isinstance(body, dict):
            return "{}"

        # 递归替换
        formatted = self._replace_deps(body, depends_on)
        return formatted

    def _replace_deps(self, obj: Any, depends_on: List[str]) -> str:
        """递归替换请求体中的依赖变量"""
        if isinstance(obj, dict):
            parts = []
            for k, v in obj.items():
                v_str = self._replace_deps(v, depends_on)
                parts.append(f'"{k}": {v_str}')
            return '{' + ', '.join(parts) + '}'
        elif isinstance(obj, list):
            items = [self._replace_deps(item, depends_on) for item in obj[:5]]
            return '[' + ', '.join(items) + ']'
        elif isinstance(obj, str):
            return json.dumps(obj, ensure_ascii=False)
        elif obj is None:
            return 'None'
        else:
            return repr(obj)

    def _field_path_to_jsonpath(self, field_path: str) -> str:
        """把字段路径转成Python的字典访问语法

        例: "result.id" → '["result"]["id"]'
        例: "result.templates[0].id" → '["result"]["templates"][0]["id"]'
        """
        parts = field_path.replace('[', '.').replace(']', '').split('.')
        result = ""
        for part in parts:
            if part.isdigit():
                result += f"[{int(part)}]"
            else:
                result += f'["{part}"]'
        return result
