"""AI 分析模块"""

from .provider import (
    AIProvider,
    OpenAICompatibleProvider,
    MinimaxProvider,
    OpenAIProvider,
    create_ai_provider,
    list_available_models,
    MODEL_REGISTRY,
    # 轻量数据模型（替代已抛弃的 models/data_models.py）
    UIOperation,
    APICall,
    OperationIntent,
    SelectorOptimization,
    OptimizedScript,
)
from .dependency_analyzer import AIDependencyAnalyzer

__all__ = [
    "AIProvider",
    "OpenAICompatibleProvider",
    "MinimaxProvider",
    "OpenAIProvider",
    "create_ai_provider",
    "list_available_models",
    "MODEL_REGISTRY",
    "AIDependencyAnalyzer",
    "UIOperation",
    "APICall",
    "OperationIntent",
    "SelectorOptimization",
    "OptimizedScript",
]
