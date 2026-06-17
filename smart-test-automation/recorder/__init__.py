"""数据获取层 — codegen 解析 + HAR 解析 + 录制编排 + 脚本转换 + 通用守卫 + DOM Schema 抓取"""

from .codegen_parser import RecordingASTParser, UIOperation
from .har_parser import HARParser, APICall
from .recording_wrapper import TwoStepRecorder
from .script_transformer import HealingScriptTransformer
from .guards import ensure_logged_in, dismiss_dialogs, wait_for_page_ready, safe_click, safe_fill
from .dom_schema_capture import DomSchemaCapture, capture_dom_schema

__all__ = [
    "RecordingASTParser",
    "UIOperation",
    "HARParser",
    "APICall",
    "TwoStepRecorder",
    "HealingScriptTransformer",
    "ensure_logged_in",
    "dismiss_dialogs",
    "wait_for_page_ready",
    "safe_click",
    "safe_fill",
    "DomSchemaCapture",
    "capture_dom_schema",
]
