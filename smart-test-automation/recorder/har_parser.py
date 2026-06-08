#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HARParser — 直接  解析 Playwright HAR 文件
"""

import json
import sys
from dataclasses import dataclass, field
from typing import Any, List, Dict, Optional
from urllib.parse import urlparse


@dataclass
class APICall:
    """API 调用记录"""
    step_index: int                  # 序号（按时间排序）
    method: str                      # HTTP 方法
    url: str                         # 完整 URL
    path: str                        # URL 路径部分
    request_headers: Dict = field(default_factory=dict)
    request_body: Optional[Any] = None   # 请求体
    status: int = 0                  # 响应状态码
    response_headers: Dict = field(default_factory=dict)
    response_body: Optional[Any] = None  # 响应体
    mime_type: str = ""              # 响应 MIME 类型
    timing: Dict = field(default_factory=dict)
    timestamp: str = ""              # startedDateTime


class HARParser:
    # 直接用 json.load 解析 HAR 
    

    def __init__(self, url_filter: Optional[str] = None):
        self.url_filter = url_filter

    def parse(self, har_path: str, apply_filter: bool = True) -> List[APICall]:
        """解析 HAR 文件，提取 API 调用序列

        Args:
            har_path: HAR 文件路径
            apply_filter: 是否应用 url_filter（内部调用可关闭）

        Returns:
            List[APICall]: API 调用记录列表（按原始顺序）
        """
        with open(har_path, 'r', encoding='utf-8') as f:
            har = json.load(f)

        # HAR 格式校验
        if "log" not in har or "entries" not in har["log"]:
            print(f"⚠️ HAR 文件格式异常: {har_path}（缺少 log.entries）",
                  file=sys.stderr)
            return []

        entries = har["log"]["entries"]
        use_filter = apply_filter and self.url_filter

        calls: List[APICall] = []
        for i, entry in enumerate(entries):
            req = entry["request"]
            res = entry["response"]
            url = req["url"]

            # URL 过滤
            if use_filter and not self._url_matches(url):
                continue

            req_headers = {h["name"]: h["value"] for h in req.get("headers", [])}

            res_headers = {h["name"]: h["value"] for h in res.get("headers", [])}

            calls.append(APICall(
                step_index=i,
                method=req["method"],
                url=url,
                path=urlparse(url).path,
                request_headers=req_headers,
                request_body=self._parse_request_body(req.get("postData")),
                status=res["status"],
                response_headers=res_headers,
                response_body=self._parse_response_content(res.get("content", {})),
                mime_type=res.get("content", {}).get("mimeType", ""),
                timing=entry.get("timings", {}),
                timestamp=entry.get("startedDateTime", ""),
            ))

        return calls

    def parse_api_sequence(self, har_path: str) -> List[APICall]:
        """提取所有非静态资源请求

        过滤策略:
          1. 排除静态资源（图片/CSS/JS/字体/音视频/source map）
          2. 排除 OPTIONS 预检请求
          3. 其余所有请求都保留（不管是 /api/ 还是 /demand/ 等）

        """
        all_calls = self.parse(har_path, apply_filter=False)

        # 静态资源扩展名
        static_extensions = {
            '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp',
            '.css', '.js', '.woff', '.woff2', '.ttf', '.eot',
            '.map', '.jsonld',
            '.wasm', '.pdf',
            '.mp4', '.webm', '.mp3', '.wav', '.ogg', '.flac',
        }

        business_calls = []
        for call in all_calls:
            path_lower = call.path.lower()
            mime_lower = call.mime_type.lower()

            # 跳过静态资源
            if any(path_lower.endswith(ext) for ext in static_extensions):
                continue
            # 跳过 HTML 页面请求（SPA 页面跳转，非业务 API）
            if "text/html" in mime_lower:
                continue
            # 跳过 favicon/robots
            if path_lower.endswith('/favicon.ico') or path_lower.endswith('/robots.txt'):
                continue
            # 跳过 OPTIONS 预检
            if call.method == 'OPTIONS':
                continue

            business_calls.append(call)

        # 重新编号
        for i, call in enumerate(business_calls):
            call.step_index = i

        return business_calls

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _url_matches(self, url: str) -> bool:
        """URL 模式匹配

        支持:
          "**/api/**" → URL 中包含 "/api/" 的匹配
          "*.example.com/**" → 指定域名下所有请求
          精确字符串 → 包含该字符串即匹配
        """
        if not self.url_filter:
            return True

        # 将 glob-like pattern 简化为字符串包含匹配
        pattern = self.url_filter
        pattern = pattern.replace("**/", "/").replace("/**", "/").replace("**", "")
        if not pattern:
            return True

        return pattern in url

    def _parse_request_body(self, post_data: Optional[dict]) -> Optional[Any]:
        """解析请求体"""
        if not post_data:
            return None

        text = post_data.get("text", "")
        if not text:
            return None

        mime = post_data.get("mimeType", "")
        if "json" in mime:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"_raw": text[:2000], "_parse_error": True}
        return {"_raw": text[:2000], "_mime": mime}

    # 大 JSON 截断保护
    MAX_RESPONSE_CHARS = 20000   # 响应体最大保留字符数
    MAX_LIST_ITEMS = 20         # 列表最多保留元素数

    def _parse_response_content(self, content: dict) -> Optional[Any]:
        """解析响应体（含大小保护）"""
        text = content.get("text", "")
        if not text:
            return None

        mime = content.get("mimeType", "")
        if "json" in mime:
            try:
                # 超大响应体直接截断文本再解析，避免内存爆炸
                if len(text) > self.MAX_RESPONSE_CHARS:
                    text = text[:self.MAX_RESPONSE_CHARS]
                data = json.loads(text)
                return self._truncate_large_json(data)
            except json.JSONDecodeError:
                return {"_raw": text[:5000], "_parse_error": True}

        return None

    def _truncate_large_json(self, data: Any, depth: int = 0) -> Any:
        #递归 JSON 结构
        
        if depth > 6:
            return "...(深层嵌套已截断)"

        if isinstance(data, list):
            if len(data) > self.MAX_LIST_ITEMS:
                truncated = [self._truncate_large_json(item, depth + 1) for item in data[:self.MAX_LIST_ITEMS]]
                truncated.append(f"...(共{len(data)}项，已截断)")
                return truncated
            return [self._truncate_large_json(item, depth + 1) for item in data]

        if isinstance(data, dict):
            return {k: self._truncate_large_json(v, depth + 1) for k, v in data.items()}

        return data
