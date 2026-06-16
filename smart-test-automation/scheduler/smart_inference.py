#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能跨模块依赖推断器

三级推断策略（值相同的前提下）：
  L1 名字完全相同 + 值相同 → 直接确认依赖 (confidence=1.0)
  计算相似度，相似度低的需要AI介入分析


"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from knowledge import load_module_definition, list_modules


##脚本配置项
# 常见缩写映射：全称 → 可能的缩写形式（全部小写）
ABBREVIATION_MAP: Dict[str, List[str]] = {
    "number":     ["no", "nm", "num"],
    "database":   ["db"],
    "identifier": ["id"],
    "code":       ["cd"],
    "name":       ["nm"],
    "type":       ["tp"],
    "sequence":   ["seq"],
    "category":   ["cat"],
    "description":["desc"],
    "count":      ["cnt"],
    "amount":     ["amt"],
    "quantity":   ["qty"],
    "reference":  ["ref"],
    "configuration": ["cfg", "conf"],
    "information":["info"],
    "document":   ["doc"],
    "application":["app"],
    "environment":["env"],
    "management": ["mgmt", "mgt"],
    "department": ["dept"],
    "address":    ["addr"],
    "password":   ["pwd"],
    "telephone":  ["tel"],
    "message":    ["msg"],
    "request":    ["req"],
    "response":   ["resp", "res"],
    "status":     ["sts"],
    "begin":      ["bg"],
    "end":        ["ed"],
    "timestamp":  ["ts"],
    "company":    ["co"],
    "organization":["org"],
    "product":    ["prod"],
    "purchase":   ["pur"],
    "demand":     ["dem", "dm"],
    "supplier":   ["sup"],
    "contract":   ["ct"],
    "budget":     ["bgt"],
    "project":    ["proj"],
    "approve":    ["apv"],
    "audit":      ["adt"],
}


# 部分变量不需要进行匹配
VALUE_FILTER_CONFIG = {
    "min_length": 4,          
    "max_short_digit": 3,     
    "blacklist": frozenset({  
        "true", "false", "null", "none", "undefined",
        "yes", "no", "success", "fail", "ok", "error",
        "pending", "active", "deleted", "enabled", "disabled",
        "normal", "default", "test", "admin",
    }),
}

# 反向映射：缩写 → 全称（自动构建）
_ABBREV_REVERSE: Dict[str, str] = {}
for full, abbrevs in ABBREVIATION_MAP.items():
    for ab in abbrevs:
        _ABBREV_REVERSE[ab] = full


def split_camel_case(name: str) -> List[str]:
    #按照代码规范，变量命名应该是驼峰，按照驼峰进行拆词
    if not name:
        return []

    # 先处理 下划线替换为空格
    name = name.replace("_", " ")

    # 在大写字母前插入空格（驼峰拆分）
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    # 异常处理，只拆一次
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)

    # 拆分并过滤空串
    parts = [p.strip() for p in s.split() if p.strip()]
    return parts


def normalize_word(word: str) -> str:
    ## 将单词全称小写形式
    
    w = word.lower().strip()
    if w in _ABBREV_REVERSE:
        return _ABBREV_REVERSE[w]
    return w


def word_similarity(word_a: str, word_b: str) -> float:
    """计算两个单词的相似度"""
    a = word_a.lower().strip()
    b = word_b.lower().strip()

    if not a or not b:
        return 0.0

    # 1. 完全相同
    if a == b:
        return 1.0

    # 2. 缩写匹配
    a_norm = normalize_word(word_a)
    b_norm = normalize_word(word_b)
    if a_norm == b_norm:
       
        if a != a_norm or b != b_norm:
            return 0.95  
        else:
            return 1.0   

    # 3. 包含关系（前缀匹配）
    if len(a) >= 3 and len(b) >= 3:
        if a.startswith(b) or b.startswith(a):
            shorter = min(len(a), len(b))
            longer = max(len(a), len(b))
            if shorter / longer >= 0.5:  # 长度差不超过一半
                return 0.7

    return 0.0


def name_similarity(name_a: str, name_b: str) -> float:
    """计算两个变量名的整体相似度

    策略：
      1. 驼峰拆词
      2. 根据规则计算规则分数
      3. 计算加权平均相似度
    """
    words_a = split_camel_case(name_a)
    words_b = split_camel_case(name_b)

    if not words_a or not words_b:
        return 0.0

    # 逐词匹配：贪心策略，每个 a 词找 b 中最相似的
    total_score = 0.0
    matched_b = set()

    for wa in words_a:
        best_score = 0.0
        best_idx = -1
        for i, wb in enumerate(words_b):
            if i in matched_b:
                continue
            score = word_similarity(wa, wb)
            if score > best_score:
                best_score = score
                best_idx = i

        if best_idx >= 0:
            matched_b.add(best_idx)
            total_score += best_score

    # 用较长的词列表长度做分母
    max_words = max(len(words_a), len(words_b))
    return total_score / max_words if max_words > 0 else 0.0





def is_meaningful_value(val: Any) -> bool:
    """判断一个值是否适合用于匹配

    过滤掉太短、太通用、容易误匹配的值。
   可通过 VALUE_FILTER_CONFIG 调整。
    """
    if val is None:
        return False
    s = str(val).strip()
    cfg = VALUE_FILTER_CONFIG

    # 长度不够
    if len(s) < cfg["min_length"]:
        return False

    sl = s.lower()
    # 在黑名单中
    if sl in cfg["blacklist"]:
        return False

    # 纯数字且很短（如 id=1, id=99）
    if s.isdigit() and len(s) <= cfg["max_short_digit"]:
        return False

    return True


class CrossModuleInferencer:
    """跨模块依赖推断器

    三级推断策略（值相同的前提下）：
      L1 名字完全相同 + 值相同 → 直接确认
      L2 名字相似度高 + 值相同 → 确认
      L3 名字相似度低 + 值相同 → AI 仲裁
    """

    # 相似度阈值：>= 此值直接确认依赖，< 此值交给 AI
    SIMILARITY_THRESHOLD = 0.7

    def __init__(self):
        self.knowledge_dir = Path("knowledge/modules")
        self._ai_provider = None  # 延迟初始化

   

    def infer_cross_module(
        self,
        module_a: str,
        module_b: str,
    ) -> Optional[Dict[str, Any]]:
        """推断两个模块之间的依赖关系

        """
        def_a = load_module_definition(module_a)
        def_b = load_module_definition(module_b)

        if not def_a or not def_b:
            return None

        # 收集 A 的产出变量
        a_vars = []
        for var in def_a.get("smart_analysis", {}).get("extract_vars", []):
            val = var.get("example_value", "")
            if val and is_meaningful_value(val):
                a_vars.append({
                    "name": var.get("name", ""),
                    "field": var.get("from_field", ""),
                    "value": str(val),
                    "api": var.get("from_api", ""),
                })

        # 收集 B 的输入参数
        b_params = []
        for param in def_b.get("smart_analysis", {}).get("input_params", []):
            val = param.get("value", "")
            if val and is_meaningful_value(val):
                b_params.append({
                    "name": param.get("name", param.get("field", "")),
                    "field": param.get("field", ""),
                    "value": str(val),
                })

        if not a_vars or not b_params:
            return None

        # 三级匹配：收集所有候选，最后去重
        candidates = []

        for a_var in a_vars:
            for b_param in b_params:
                # 前提：值必须相同
                if a_var["value"] != b_param["value"]:
                    continue

                a_name = a_var["name"] or a_var["field"]
                b_name = b_param["name"] or b_param["field"]

                # 去掉模块前缀用于名字比较
                a_short = a_name.split("_", 1)[-1] if "_" in a_name and not a_name.startswith("_") else a_name
                # 去掉字段路径前缀
                b_short = b_name.rsplit(".", 1)[-1] if "." in b_name else b_name
                b_short = b_short.split("_", 1)[-1] if "_" in b_short and not b_short.startswith("_") else b_short

                # L1: 名字完全相同
                if a_short.lower() == b_short.lower():
                    candidates.append((a_var, b_param, 1.0, "exact_match",
                                       f"{a_short} == {b_short}"))
                    continue

                # L2: 名字相似度打分
                sim = name_similarity(a_short, b_short)
                if sim >= self.SIMILARITY_THRESHOLD:
                    candidates.append((a_var, b_param, 0.9, "name_similar",
                                       f"{a_short} ≈ {b_short} (sim={sim:.2f})"))
                    continue

                # L3: AI 仲裁（先收集，后面统一处理）
                candidates.append((a_var, b_param, -1.0, "ai_pending",
                                   f"{a_short} vs {b_short} (sim={sim:.2f}, 需AI判断)"))

        # 贪心去重：按置信度降序排列，每个变量只匹配一次
        candidates.sort(key=lambda c: c[2], reverse=True)
        confirmed_mappings = []
        used_a = set()  # 已匹配的 A 变量索引
        used_b = set()  # 已匹配的 B 参数索引

        for a_var, b_param, conf, method, detail in candidates:
            a_idx = id(a_var)   # 用对象 id 标识
            b_idx = id(b_param)
            if a_idx in used_a or b_idx in used_b:
                continue  # 该变量已被更高置信度的匹配占用
            used_a.add(a_idx)
            used_b.add(b_idx)
            confirmed_mappings.append((a_var, b_param, conf, method, detail))

        if not confirmed_mappings:
            return None

        # 处理 L3：需要 AI 仲裁的
        ai_pending = [(i, m) for i, m in enumerate(confirmed_mappings) if m[3] == "ai_pending"]
        if ai_pending:
            ai_results = self._ai_arbitrate(module_a, module_b, ai_pending)
            for (idx, mapping), ai_confidence in zip(ai_pending, ai_results):
                if ai_confidence > 0.8:
                    confirmed_mappings[idx] = (
                        mapping[0], mapping[1], ai_confidence, "ai_confirmed",
                        mapping[4] + f" → AI确认 (conf={ai_confidence:.2f})"
                    )
                else:
                    # AI 说不是依赖，移除
                    confirmed_mappings[idx] = None

        # 过滤掉 AI 否决的
        confirmed_mappings = [m for m in confirmed_mappings if m is not None]

        if not confirmed_mappings:
            return None

        var_mapping = {}
        details = []
        for a_var, b_param, confidence, method, detail in confirmed_mappings:
            a_key = a_var["name"] or a_var["field"]
            b_key = b_param["name"] or b_param["field"]
            var_mapping[a_key] = b_key
            details.append({
                "a_var": a_key,
                "b_param": b_key,
                "confidence": confidence,
                "method": method,
                "detail": detail,
            })

        return {
            "from": module_a,
            "to": module_b,
            "var_mapping": var_mapping,
            "confidence": max(d["confidence"] for d in details),
            "methods": list(set(d["method"] for d in details)),
            "details": details,
        }

    # AI 介入审核check
    

    def _ai_arbitrate(
        self,
        module_a: str,
        module_b: str,
        pending: List[Tuple[int, tuple]],
    ) -> List[float]:
        """调用 AI 判断变量名是否语义相同

        Returns:
            List[float]: 每个待判断项的置信度 (0.0~1.0)
        """
        # 构造 prompt
        pairs_desc = []
        for idx, (a_var, b_param, _, _, detail) in pending:
            pairs_desc.append(f"  - A的变量: {a_var['name']} (字段: {a_var['field']}) "
                             f"vs B的参数: {b_param['name']} (字段: {b_param['field']})")

        prompt = (
            f"判断以下变量名对是否表示同一个业务字段（语义是否相同）。\n"
            f"模块A({module_a})的产出变量 vs 模块B({module_b})的输入参数：\n\n"
            + "\n".join(pairs_desc)
            + "\n\n"
            "返回JSON数组，每个元素包含 index 和 confidence(0~1)：\n"
            '[{"index":0,"confidence":0.9}]\n'
            "confidence>0.8 表示认为是同一字段，<0.3 表示不是。\n"
            "直接返回JSON："
        )

        try:
            if self._ai_provider is None:
                from ai.provider import create_ai_provider
                self._ai_provider = create_ai_provider()

            response = self._ai_provider._call_api(prompt)

            # 解析响应
            import re as _re
            json_match = _re.search(r"\[.*\]", response, _re.DOTALL)
            if json_match:
                results = json.loads(json_match.group())
                confidence_map = {r.get("index", i): r.get("confidence", 0.0)
                                  for i, r in enumerate(results)}
                return [confidence_map.get(i, 0.0) for i in range(len(pending))]
        except Exception as e:
            print(f"   ⚠️ AI仲裁失败: {e}")

        # AI 失败时，默认拒绝
        return [0.0] * len(pending)

    # 批量推断

    def infer_all(self) -> List[Dict[str, Any]]:
        """推断所有已录制模块之间的依赖关系"""
        modules = list_modules()
        dependencies = []

        for module_a in modules:
            for module_b in modules:
                if module_a == module_b:
                    continue
                dep = self.infer_cross_module(module_a, module_b)
                if dep:
                    dependencies.append(dep)

        return dependencies

    def auto_update_graph(self):
        """自动推断所有依赖并更新依赖图"""
        from knowledge import add_dependency

        deps = self.infer_all()
        count = 0
        for dep in deps:
            var_mapping = dep.get("var_mapping", {})
            add_dependency(
                module_name=dep["to"],
                depends_on=dep["from"],
                var_mapping=var_mapping,
            )
            count += 1
            methods = dep.get("methods", [])
            conf = dep.get("confidence", 0)
            print(f"   📎 {dep['from']} → {dep['to']} "
                  f"({list(var_mapping.keys())}) [{'+'.join(methods)} conf={conf:.2f}]")

        return count
