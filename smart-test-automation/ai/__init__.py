"""AI 分析模块"""

from .provider import (
    AIProvider,
    OpenAICompatibleProvider,
    MinimaxProvider,
    OpenAIProvider,
    create_ai_provider,
    list_available_models,
    MODEL_REGISTRY,
    # 轻量数据模型
    UIOperation,
    APICall,
    OperationIntent,
    SelectorOptimization,
    OptimizedScript,
)
from .dependency_analyzer import SmartDependencyInferencer

__all__ = [
    "AIProvider",
    "OpenAICompatibleProvider",
    "MinimaxProvider",
    "OpenAIProvider",
    "create_ai_provider",
    "list_available_models",
    "MODEL_REGISTRY",
    "SmartDependencyInferencer",
    "UIOperation",
    "APICall",
    "OperationIntent",
    "SelectorOptimization",
    "OptimizedScript",
]
