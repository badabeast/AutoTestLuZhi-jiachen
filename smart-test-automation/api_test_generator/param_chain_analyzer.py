# -*- coding: utf-8 -*-
"""响应→请求参数传递链分析

从HAR完整数据中，找"响应字段值 → 请求字段值"的参数传递关系。
支持三种传递方式：request_body / query_string / url_path。

值匹配策略（多层模糊匹配）：
- 精确匹配（confidence: 1.0x）
- 类型归一化：int/float/str 互转（0.95x）
- 子串匹配：source 值是 target 值的子串或反过来（0.85x）
- URL 解码匹配：target 值含 URL 编码字符（0.9x）
- 数组元素匹配：source 是数组，target 值是其中某个元素（0.8x）
"""

import re
from typing import List, Dict, Tuple, Any, Optional
from urllib.parse import urlparse, parse_qs, unquote

from recorder.har_parser import APICall
from .models import ParamChain
from .utils import extract_leaf_fields, is_meaningful_value, field_path_to_var_name


class ParamChainAnalyzer:
    """分析API调用之间的参数传递链"""

    # 值匹配类型的置信度乘数
    MATCH_MULTIPLIERS = {
        "exact": 1.0,
        "type_normalized": 0.95,
        "url_decoded": 0.9,
        "substring": 0.85,
        "array_element": 0.8,
    }

    # 噪音值黑名单：全局高频出现的值，不参与参数传递匹配
    NOISE_VALUES = frozenset({
        "true", "false", "null", "none", "undefined",
        "admin", "system", "success", "ok", "yes", "no",
        "active", "inactive", "enabled", "disabled",
        "asc", "desc", "default", "normal",
    })

    def __init__(self, min_value_length: int = 3, noise_frequency_threshold: float = 0.4):
        self.min_value_length = min_value_length
        # 某个值在超过该比例的响应字段中出现时，视为噪音
        self.noise_frequency_threshold = noise_frequency_threshold

    def analyze_chains(self, api_calls: List[APICall]) -> List[ParamChain]:
        """分析所有API调用，建立响应→请求的参数传递链

        覆盖三种传递方式：
        1. request_body（POST/PUT 的 JSON body）
        2. query_string（GET 请求的 URL 参数）
        3. url_path（REST 风格的路径参数，如 /api/demand/12345）

        Args:
            api_calls: API调用列表（按时间顺序）

        Returns:
            List[ParamChain]: 参数传递链
        """
        if not api_calls:
            return []

        # 1. 收集所有响应字段（source）
        response_fields: List[Tuple[str, str, Any, int]] = []
        # (api_label, field_path, value, api_index)

        # 2. 收集所有请求字段（target）- 包含 body / query / path 三种来源
        request_fields: List[Tuple[str, str, Any, int, str]] = []
        # (api_label, field_path, value, api_index, source_type)

        for idx, call in enumerate(api_calls):
            api_label = f"{call.method} {call.path}"

            # 收集响应字段
            if call.response_body and isinstance(call.response_body, dict):
                for field_path, value in extract_leaf_fields(call.response_body):
                    if is_meaningful_value(value):
                        response_fields.append((api_label, field_path, value, idx))

            # 收集请求 body 字段
            if call.request_body and isinstance(call.request_body, dict):
                for field_path, value in extract_leaf_fields(call.request_body):
                    if is_meaningful_value(value):
                        request_fields.append((api_label, field_path, value, idx, "body"))

            # 收集 query string 参数
            query_params = self._extract_query_params(call.url)
            for param_name, param_value in query_params.items():
                if is_meaningful_value(param_value):
                    request_fields.append((api_label, f"query.{param_name}", param_value, idx, "query"))

            # 收集 URL 路径参数
            path_params = self._extract_path_params(call.path)
            for param_name, param_value in path_params:
                if is_meaningful_value(param_value):
                    request_fields.append((api_label, f"path.{param_name}", param_value, idx, "path"))

        # 3. 噪音过滤：剔除全局高频值，减少误报
        noise_values = self._detect_noise_values(response_fields, api_calls)

        # 过滤 response_fields 中的噪音值
        response_fields = [
            (api, fp, val, idx)
            for api, fp, val, idx in response_fields
            if self._normalize_value(val) not in noise_values
        ]

        # 过滤 request_fields 中的噪音值
        request_fields = [
            (api, fp, val, idx, src)
            for api, fp, val, idx, src in request_fields
            if self._normalize_value(val) not in noise_values
        ]

        # 4. 建立值索引（支持模糊匹配）
        value_index = self._build_value_index(response_fields)

        # 5. 匹配
        chains: List[ParamChain] = []

        for target_api, target_field, target_value, target_idx, target_source in request_fields:
            matches = self._find_matches(target_value, value_index, response_fields, target_idx)

            for src_i, match_type in matches:
                source_api, source_field, _, source_idx = response_fields[src_i]

                # 计算置信度
                confidence = self._calculate_confidence(
                    source_field, target_field, target_value, match_type
                )

                chain_type = f"value_{match_type}"
                if target_source == "query":
                    chain_type = f"query_{match_type}"
                elif target_source == "path":
                    chain_type = f"path_{match_type}"

                chains.append(ParamChain(
                    source_api=source_api,
                    source_field=source_field,
                    source_example=target_value,
                    target_api=target_api,
                    target_field=target_field,
                    chain_type=chain_type,
                    confidence=round(confidence, 2),
                ))

        # 6. 去重
        chains = self._deduplicate_chains(chains)

        # 7. 按置信度排序
        chains.sort(key=lambda c: c.confidence, reverse=True)

        return chains

    # ── Query String 参数提取 ─────────────────────────────

    def _extract_query_params(self, url: str) -> Dict[str, Any]:
        """从 URL 中提取 query string 参数

        例: /api/demand/list?page=1&size=20 → {"page": "1", "size": "20"}
        """
        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query, keep_blank_values=False)
            # parse_qs 返回 list，取第一个值
            return {k: v[0] if len(v) == 1 else v for k, v in params.items() if v}
        except Exception:
            return {}

    # ── URL 路径参数提取 ─────────────────────────────────

    # 常见的 REST 路径模式：/api/resource/{id}
    _PATH_PARAM_PATTERNS = [
        # /api/demand/12345 → id=12345
        (r'/api/[^/]+/(\d{5,})', 'id'),
        # /api/demand/detail/12345 → id=12345
        (r'/api/[^/]+/[^/]+/(\d{5,})', 'id'),
        # /api/v2/12345/resource → id=12345
        (r'/api/v\d+/(\d{5,})/', 'id'),
        # UUID 路径段
        (r'/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', 'uuid'),
    ]

    def _extract_path_params(self, path: str) -> List[Tuple[str, str]]:
        """从 URL 路径中提取疑似动态参数

        策略：用正则匹配常见模式（长数字ID、UUID），
        将匹配到的值作为路径参数。

        Returns:
            List[Tuple[str, str]]: [(param_name, param_value), ...]
        """
        params = []
        for pattern, param_name in self._PATH_PARAM_PATTERNS:
            for match in re.finditer(pattern, path, re.IGNORECASE):
                value = match.group(1)
                if len(value) >= self.min_value_length:
                    params.append((param_name, value))
        return params

    # ── 模糊值匹配引擎 ─────────────────────────────────

    def _build_value_index(
        self,
        response_fields: List[Tuple[str, str, Any, int]],
    ) -> Dict[str, List[int]]:
        """建立多层值索引，支持模糊匹配

        对每个响应值生成多个索引键：
        - 原始值（精确匹配）
        - 类型归一化值（str(123) 和 123 都索引为 "123"）
        - 小写值（大小写不敏感匹配）
        """
        index: Dict[str, List[int]] = {}

        for i, (_, _, value, _) in enumerate(response_fields):
            # 原始值索引
            keys = set()

            if isinstance(value, (int, float)):
                keys.add(str(value))  # str 形式
                keys.add(str(int(value)) if isinstance(value, float) and value == int(value) else str(value))
            elif isinstance(value, str):
                keys.add(value)  # 原始
                keys.add(value.lower())  # 小写
                # 如果是数字字符串，也索引为纯数字
                if value.isdigit():
                    keys.add(value.lstrip('0') or '0')
            elif isinstance(value, list):
                # 数组：索引每个元素
                for item in value[:20]:
                    if isinstance(item, (str, int, float)):
                        keys.add(str(item))

            for key in keys:
                if len(key) >= self.min_value_length or key.isdigit():
                    if key not in index:
                        index[key] = []
                    index[key].append(i)

        return index

    def _find_matches(
        self,
        target_value: Any,
        value_index: Dict[str, List[int]],
        response_fields: List[Tuple[str, str, Any, int]],
        target_idx: int,
    ) -> List[Tuple[int, str]]:
        """在响应字段中查找与 target_value 匹配的字段

        Returns:
            List[Tuple[int, str]]: [(response_field_index, match_type), ...]
        """
        matches = []

        # 归一化 target 值为字符串
        target_str = self._normalize_value(target_value)
        if not target_str:
            return []

        # 精确匹配
        for src_i in value_index.get(target_str, []):
            if self._is_valid_pair(src_i, target_idx, response_fields):
                matches.append((src_i, "exact"))

        # 类型归一化匹配（target 是 "123"，source 是 123）
        if isinstance(target_value, str) and target_value.isdigit():
            for src_i in value_index.get(target_value, []):
                if self._is_valid_pair(src_i, target_idx, response_fields):
                    if (src_i, "exact") not in matches:
                        matches.append((src_i, "type_normalized"))

        # URL 解码匹配
        if isinstance(target_value, str) and '%' in target_value:
            decoded = unquote(target_value)
            if decoded != target_value:
                for src_i in value_index.get(decoded, []):
                    if self._is_valid_pair(src_i, target_idx, response_fields):
                        if (src_i, "exact") not in matches:
                            matches.append((src_i, "url_decoded"))

        # 子串匹配（target 值包含在 source 值中，或反过来）
        if isinstance(target_value, str) and len(target_str) >= 5:
            for key, indices in value_index.items():
                if key == target_str:
                    continue
                # source 值包含 target 值
                if target_str in key and len(target_str) / len(key) > 0.5:
                    for src_i in indices:
                        if self._is_valid_pair(src_i, target_idx, response_fields):
                            if (src_i, "substring") not in matches:
                                matches.append((src_i, "substring"))
                # target 值包含 source 值
                elif key in target_str and len(key) / len(target_str) > 0.5:
                    for src_i in indices:
                        if self._is_valid_pair(src_i, target_idx, response_fields):
                            if (src_i, "substring") not in matches:
                                matches.append((src_i, "substring"))

        # 去重（同一 src_i 只保留最高置信度的 match_type）
        seen_src = {}
        for src_i, match_type in matches:
            if src_i not in seen_src:
                seen_src[src_i] = match_type
            else:
                # 保留乘数更高的
                old_mult = self.MATCH_MULTIPLIERS.get(seen_src[src_i], 0)
                new_mult = self.MATCH_MULTIPLIERS.get(match_type, 0)
                if new_mult > old_mult:
                    seen_src[src_i] = match_type

        return [(src_i, mt) for src_i, mt in seen_src.items()]

    def _normalize_value(self, value: Any) -> Optional[str]:
        """归一化值为字符串（用于匹配）"""
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped or stripped in ("null", "None", "undefined"):
                return None
            return stripped
        if isinstance(value, list):
            # 数组不参与直接匹配，由 _find_matches 单独处理
            return None
        return str(value)

    def _is_valid_pair(
        self,
        src_i: int,
        target_idx: int,
        response_fields: List[Tuple[str, str, Any, int]],
    ) -> bool:
        """检查源和目标是否构成有效的传递对"""
        _, _, _, source_idx = response_fields[src_i]
        # 自己跟自己不算
        if source_idx == target_idx:
            return False
        # source 必须在 target 之前
        if source_idx > target_idx:
            return False
        return True

    # ── 噪音字段检测 ─────────────────────────────────

    def _detect_noise_values(
        self,
        response_fields: List[Tuple[str, str, Any, int]],
        api_calls: List[APICall],
    ) -> set:
        """检测全局高频噪音值

        策略：
        1. 硬编码黑名单（NOISE_VALUES）中的值直接标记为噪音
        2. 统计每个归一化值在所有响应字段中的出现比例，
           超过 noise_frequency_threshold 的视为噪音
        3. 短数字值（0, 1, 2）和短字符串（a, b, c）也视为噪音

        Returns:
            set: 被判定为噪音的归一化值集合
        """
        noise = set(self.NOISE_VALUES)

        if not response_fields:
            return noise

        # 统计每个值出现的 API 数量（去重，同一 API 内多次出现只算 1 次）
        value_api_count: Dict[str, set] = {}
        for api_label, _, value, _ in response_fields:
            norm = self._normalize_value(value)
            if not norm:
                continue
            key = norm.lower()
            if key not in value_api_count:
                value_api_count[key] = set()
            value_api_count[key].add(api_label)

        total_apis = len(api_calls)
        if total_apis == 0:
            return noise

        for val_key, api_set in value_api_count.items():
            frequency = len(api_set) / total_apis
            if frequency >= self.noise_frequency_threshold:
                noise.add(val_key)

        # 短数字和单字符也是常见噪音
        noise.update({"0", "1", "2", "-1", ""})

        return noise

    # ── 置信度计算 ─────────────────────────────────────

    def _calculate_confidence(
        self,
        source_field: str,
        target_field: str,
        target_value: Any,
        match_type: str,
    ) -> float:
        """计算参数传递链的置信度"""
        # 基础分 × 匹配类型乘数
        base = 0.7
        multiplier = self.MATCH_MULTIPLIERS.get(match_type, 0.7)
        confidence = base * multiplier

        # 字段路径关键词匹配加分
        source_keywords = self._extract_keywords(source_field)
        target_keywords = self._extract_keywords(target_field)
        overlap = (source_keywords & target_keywords) - {'result', 'data', 'list', 'items', 'value'}
        if overlap:
            confidence = min(confidence + 0.15, 1.0)

        # ID 关键词检测加分
        id_keywords = {"id", "uuid", "code", "no", "number", "seq", "token", "key"}
        if any(kw in source_field.lower() for kw in id_keywords):
            confidence = min(confidence + 0.1, 1.0)
        if any(kw in target_field.lower() for kw in id_keywords):
            confidence = min(confidence + 0.05, 1.0)

        # 数值 > 100 或长字符串更可能是 ID
        if isinstance(target_value, (int, float)) and target_value > 100:
            confidence = min(confidence + 0.05, 1.0)
        elif isinstance(target_value, str) and len(target_value) > 10:
            confidence = min(confidence + 0.05, 1.0)

        return confidence

    def _extract_keywords(self, field_path: str) -> set:
        """从字段路径中提取关键词（支持驼峰和下划线拆分）"""
        # 先按 . [ ] 分割
        parts = field_path.replace('[', '.').replace(']', '').split('.')
        keywords = set()
        for part in parts:
            # 驼峰拆分：userId → user, id
            camel_parts = re.sub(r'([a-z])([A-Z])', r'\1_\2', part).lower().split('_')
            keywords.update(camel_parts)
        return keywords

    # ── 去重 ───────────────────────────────────────────

    def _deduplicate_chains(self, chains: List[ParamChain]) -> List[ParamChain]:
        """同一target只保留最高置信度的链"""
        best: Dict[str, ParamChain] = {}
        for chain in chains:
            key = f"{chain.target_api}#{chain.target_field}"
            if key not in best or chain.confidence > best[key].confidence:
                best[key] = chain
        return list(best.values())

    # ── 跨模块依赖 ─────────────────────────────────────

    def analyze_cross_module_chains(
        self,
        current_module: str,
        current_api_calls: List[APICall],
        existing_modules: Dict[str, Dict],
    ) -> List[ParamChain]:
        """分析跨模块参数传递依赖"""
        cross_chains: List[ParamChain] = []

        other_module_values: Dict[str, List[Tuple[str, str, Any]]] = {}
        for mod_name, mod_def in existing_modules.items():
            if mod_name == current_module:
                continue
            old_chains = mod_def.get("param_chains", [])
            for chain_data in old_chains:
                src_api = chain_data.get("source_api", "")
                src_field = chain_data.get("source_field", "")
                src_example = chain_data.get("source_example")
                if src_example and self._is_meaningful(src_example):
                    if mod_name not in other_module_values:
                        other_module_values[mod_name] = []
                    other_module_values[mod_name].append((src_api, src_field, src_example))

        if not other_module_values:
            return cross_chains

        for call in current_api_calls:
            # 检查 request body
            if call.request_body and isinstance(call.request_body, dict):
                request_values = self._flatten_values(call.request_body)
                cross_chains.extend(
                    self._match_cross_module(call, request_values, other_module_values, "body")
                )

            # 检查 query string
            query_params = self._extract_query_params(call.url)
            if query_params:
                query_values = [str(v) for v in query_params.values() if isinstance(v, (str, int, float))]
                cross_chains.extend(
                    self._match_cross_module(call, query_values, other_module_values, "query")
                )

            # 检查 URL 路径
            path_params = self._extract_path_params(call.path)
            if path_params:
                path_values = [v for _, v in path_params]
                cross_chains.extend(
                    self._match_cross_module(call, path_values, other_module_values, "path")
                )

        return cross_chains

    def _match_cross_module(
        self,
        call: APICall,
        target_values: List[str],
        other_module_values: Dict[str, List[Tuple[str, str, Any]]],
        source_type: str,
    ) -> List[ParamChain]:
        """在跨模块值中查找匹配"""
        chains = []
        api_label = f"{call.method} {call.path}"

        for mod_name, values in other_module_values.items():
            for src_api, src_field, src_value in values:
                src_str = str(src_value)
                # 精确匹配或子串匹配
                matched = False
                match_type = "exact"
                for tv in target_values:
                    if src_str == tv:
                        matched = True
                        match_type = "exact"
                        break
                    elif len(src_str) >= 5 and src_str in tv:
                        matched = True
                        match_type = "substring"
                        break
                    elif len(src_str) >= 5 and tv in src_str:
                        matched = True
                        match_type = "substring"
                        break

                if matched:
                    chains.append(ParamChain(
                        source_api=src_api,
                        source_field=src_field,
                        source_example=src_value,
                        target_api=api_label,
                        target_field=f"{source_type}.cross_module",
                        chain_type=f"cross_module_{match_type}",
                        confidence=0.85 * self.MATCH_MULTIPLIERS.get(match_type, 0.7),
                    ))

        return chains

    # ── 工具方法 ───────────────────────────────────────

    def _is_meaningful(self, value: Any) -> bool:
        if value is None:
            return False
        s = str(value).strip()
        if not s or s in ("null", "None", "undefined", "0", ""):
            return False
        if len(s) < 3:
            return False
        return True

    def _flatten_values(self, data: Any) -> List[str]:
        """递归展平数据结构为字符串值列表（用于跨模块匹配）

        支持 dict / list / str / int / float 的递归展平。
        """
        values = []
        if isinstance(data, dict):
            for v in data.values():
                values.extend(self._flatten_values(v))
        elif isinstance(data, list):
            for v in data:
                values.extend(self._flatten_values(v))
        elif isinstance(data, str) and data:
            values.append(data)
        elif isinstance(data, (int, float)) and not isinstance(data, bool):
            values.append(str(data))
        return values

    @staticmethod
    def extract_vars_from_chains(chains: List[ParamChain]) -> List[Dict[str, str]]:
        """从参数传递链中提取可提取变量（兼容旧 extract_vars 格式）"""
        seen = set()
        extract_vars = []
        for chain in chains:
            key = f"{chain.source_api}#{chain.source_field}"
            if key in seen:
                continue
            seen.add(key)
            var_name = chain.source_field.replace('.', '_').replace('[', '_').replace(']', '').lower()
            extract_vars.append({
                "name": var_name,
                "from_api": chain.source_api,
                "from_field": chain.source_field,
                "example_value": str(chain.source_example)[:100] if chain.source_example else "",
            })
        return extract_vars
