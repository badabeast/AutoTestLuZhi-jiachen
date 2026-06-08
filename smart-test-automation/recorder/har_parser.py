#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HARParser — 直接 json.load 解析 Playwright HAR 文件

HAR 是 HTTP Archive 1.2 标准 JSON 格式，包含完整的请求/响应数据。
不依赖 haralyzer 等第三方库，直接解析更可控。

用法::
    parser = HARParser(url_filter="**/api/**")
    calls = parser.parse("output/modules/create_demand/api.har")
    for call in calls:
        print(f"{call.method} {call.path} → {call.status}")
"""

import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from urllib.parse import urlparse


@dataclass
class APICall:
    """API 调用记录"""
    step_index: int                  # 序号（按时间排序）
    method: str                      # HTTP 方法
    url: str                         # 完整 URL
    path: str                        # URL 路径部分
    request_headers: Dict = field(default_factory=dict)
    request_body: Optional[Any] = None   # 请求体（dict 或 raw string）
    status: int = 0                  # 响应状态码
    response_headers: Dict = field(default_factory=dict)
    response_body: Optional[Any] = None  # 响应体（dict 或 None）
    mime_type: str = ""              # 响应 MIME 类型
    timing: Dict = field(default_factory=dict)
    timestamp: str = ""              # startedDateTime


class HARParser:
    """直接用 json.load 解析 HAR 1.2 标准文件

    Args:
        url_filter: URL 过滤模式（如 "**/api/**"），只提取匹配的 API 请求
                    None 表示不过滤，提取所有请求
    """

    def __init__(self, url_filter: Optional[str] = None):
        self.url_filter = url_filter

    def parse(self, har_path: str) -> List[APICall]:
        """解析 HAR 文件，提取 API 调用序列

        Args:
            har_path: HAR 文件路径

        Returns:
            List[APICall]: API 调用记录列表（按原始顺序）
        """
        with open(har_path, 'r', encoding='utf-8') as f:
            har = json.load(f)

        calls: List[APICall] = []

        for i, entry in enumerate(har["log"]["entries"]):
            req = entry["request"]
            res = entry["response"]
            url = req["url"]

            # URL 过滤
            if self.url_filter and not self._url_matches(url):
                continue

            # 请求 headers → dict
            req_headers = {}
            for h in req.get("headers", []):
                req_headers[h["name"]] = h["value"]

            # 响应 headers → dict
            res_headers = {}
            for h in res.get("headers", []):
                res_headers[h["name"]] = h["value"]

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
        """提取所有非静态资源请求（只过滤静态资源，其余全保留）

        过滤策略:
          1. 排除静态资源（图片/CSS/JS/字体/source map）
          2. 排除 OPTIONS 预检请求
          3. 其余所有请求都保留（不管是 /api/ 还是 /demand/ 等）

        Args:
            har_path: HAR 文件路径

        Returns:
            List[APICall]: 业务 API 调用列表
        """
        # 不用 url_filter 过滤，先拿到全部请求
        original_filter = self.url_filter
        self.url_filter = None
        all_calls = self.parse(har_path)
        self.url_filter = original_filter

        # 静态资源扩展名
        static_extensions = {
            '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp',
            '.css', '.js', '.woff', '.woff2', '.ttf', '.eot',
            '.map', '.jsonld',
        }

        business_calls = []
        for call in all_calls:
            path_lower = call.path.lower()

            # 跳过静态资源
            if any(path_lower.endswith(ext) for ext in static_extensions):
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
        # 去掉 ** 通配符，简化为子串匹配
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

    def _parse_response_content(self, content: dict) -> Optional[Any]:
        """解析响应体

        HAR 中响应体在 content.text 字段。
        只解析 JSON 响应，非 JSON（图片/CSS等）返回 None。
        """
        text = content.get("text", "")
        if not text:
            return None

        mime = content.get("mimeType", "")
        if "json" in mime:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                # 非 JSON 或截断的 JSON
                return {"_raw": text[:5000], "_parse_error": True}

        # 非 JSON 响应不存储（图片、CSS、JS 等太大且无用）
        return None