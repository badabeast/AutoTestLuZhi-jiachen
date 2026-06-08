"""
tests/conftest.py — 测试目录级别的配置

继承项目根目录 conftest.py 的 healing_config 配置，
加载 .env 确保环境变量可用。
"""

import os
from pathlib import Path

# 加载项目根目录的 .env
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    with open(_env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())