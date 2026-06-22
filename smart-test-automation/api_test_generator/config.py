# -*- coding: utf-8 -*-
"""
配置管理
用于接口自动化用例生成器的配置参数
"""

from dataclasses import dataclass


@dataclass
class APIGeneratorConfig:
    """接口自动化用例生成器配置"""
    time_window_ms: int = 500  # 时间匹配容错窗口（毫秒）
    min_confidence: float = 0.6  # 最低置信度阈值
    output_dir: str = "output/modules"  # 输出目录
    knowledge_dir: str = "knowledge"  # 知识库目录
    env_var_prefix: str = "SMART_"  # 环境变量前缀
