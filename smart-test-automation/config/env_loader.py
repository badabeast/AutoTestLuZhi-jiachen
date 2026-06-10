#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
.env 文件加载工具

手动解析 .env 文件（不依赖 python-dotenv，兼容 Python 3.14）。
支持:
  - 带引号的值: KEY="value with spaces"
  - 行内注释: KEY=value # comment
  - 空行和注释行跳过
"""

import os
from pathlib import Path
from typing import Optional


def load_env(env_path: Optional[str] = None) -> dict:
    """加载 .env 文件到 os.environ

    Args:
        env_path: .env 文件路径，默认为项目根目录下的 .env

    Returns:
        dict: 加载的键值对
    """
    if env_path is None:
        env_path = Path(__file__).parent.parent / ".env"
    else:
        env_path = Path(env_path)

    if not env_path.exists():
        return {}

    loaded = {}
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # 跳过空行和注释
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue

            key, raw_value = line.split("=", 1)
            key = key.strip()

            # 解析值：去除引号和尾部注释
            value = _parse_value(raw_value)
            loaded[key] = value
            # 不覆盖已存在的环境变量
            os.environ.setdefault(key, value)

    # 环境切换：TEST_ENV=staging 时，用 STAGING_* 变量覆盖标准变量
    _apply_env_override()

    return loaded


def _apply_env_override():
    """根据 TEST_ENV 切换环境配置

    当 TEST_ENV=staging 时，将 STAGING_WEB_DEMAND_* 变量覆盖到 WEB_DEMAND_*
    下游代码无需任何改动。
    """
    env = os.environ.get("TEST_ENV", "test")

    if env == "staging":
        # 预发环境变量映射
        mappings = {
            "STAGING_WEB_DEMAND_URL": "WEB_DEMAND_URL",
            "STAGING_WEB_DEMAND_ACCOUNT": "WEB_DEMAND_ACCOUNT",
            "STAGING_WEB_DEMAND_PASSWORD": "WEB_DEMAND_PASSWORD",
        }
        for staging_key, standard_key in mappings.items():
            val = os.environ.get(staging_key)
            if val:
                os.environ[standard_key] = val
                print(f"[ENV] {standard_key} = {val}  (from {staging_key})")


def _parse_value(raw: str) -> str:
    """解析 .env 值：处理引号包裹和行内注释

    Examples:
        'value'           → 'value'
        '"value"'         → 'value'
        "'value'"         → 'value'
        'value # comment' → 'value'
        '"value # not comment"' → 'value # not comment'
    """
    raw = raw.strip()

    # 带双引号的值：保留引号内的所有内容（包括 #）
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        return raw[1:-1]

    # 带单引号的值
    if raw.startswith("'") and raw.endswith("'") and len(raw) >= 2:
        return raw[1:-1]

    # 无引号：去除尾部注释
    if " #" in raw:
        raw = raw[: raw.index(" #")]

    return raw.strip()
