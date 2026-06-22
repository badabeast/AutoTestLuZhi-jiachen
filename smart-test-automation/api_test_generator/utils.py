# -*- coding: utf-8 -*-
"""工具函数 - JSON字段提取、值匹配、安全解析"""

from typing import Any, Dict, List, Optional, Tuple


def extract_leaf_fields(data: Any, prefix: str = "", max_depth: int = 10) -> List[Tuple[str, Any]]:
    """递归提取JSON的叶子字段，返回 (路径, 值) 列表

    例: {"result": {"id": 123}} → [("result.id", 123)]
    """
    if max_depth <= 0:
        return []

    fields: List[Tuple[str, Any]] = []

    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, (dict, list)):
                fields.extend(extract_leaf_fields(value, path, max_depth - 1))
            else:
                fields.append((path, value))
    elif isinstance(data, list):
        for i, item in enumerate(data[:10]):  # 只取前10个元素
            path = f"{prefix}[{i}]"
            if isinstance(item, (dict, list)):
                fields.extend(extract_leaf_fields(item, path, max_depth - 1))
            else:
                fields.append((path, item))

    return fields


def find_value_in_json(data: Any, target_value: Any, prefix: str = "",
                       max_depth: int = 10) -> List[str]:
    """在JSON数据中找某个值的位置，返回所有匹配的字段路径"""
    if max_depth <= 0 or target_value is None:
        return []

    paths: List[str] = []

    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else key
            if value == target_value:
                paths.append(path)
            elif isinstance(value, (dict, list)):
                paths.extend(find_value_in_json(value, target_value, path, max_depth - 1))
    elif isinstance(data, list):
        for i, item in enumerate(data[:20]):
            path = f"{prefix}[{i}]"
            if item == target_value:
                paths.append(path)
            elif isinstance(item, (dict, list)):
                paths.extend(find_value_in_json(item, target_value, path, max_depth - 1))

    return paths


def parse_json_safely(text: str) -> Optional[Any]:
    """安全解析JSON，失败返回None"""
    import json
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def is_meaningful_value(value: Any) -> bool:
    """判断一个值是否值得用于参数传递链匹配

    过滤掉 None、空字符串、0、bool、短字符串等无意义值
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        if value == 0:
            return False
        return True
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped in ("null", "undefined", "None", "false", "true"):
            return False
        if len(stripped) < 3:
            return False
        # 常见无意义值
        if stripped in ("0", "-1", "1", "{}", "[]"):
            return False
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return False
    return True


def field_path_to_var_name(field_path: str) -> str:
    """把字段路径转成合法的Python变量名

    例: "result.id" → "result_id"
    """
    import re
    # 替换非字母数字下划线为下划线
    name = re.sub(r'[^a-zA-Z0-9]', '_', field_path)
    # 去掉连续下划线
    name = re.sub(r'_+', '_', name).strip('_')
    # 不能以数字开头
    if name and name[0].isdigit():
        name = "v_" + name
    return name.lower()
