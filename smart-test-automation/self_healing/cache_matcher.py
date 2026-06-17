"""L1: 历史缓存 locator 优先匹配

独创性：
1. 持久化本地 JSON（区别于开源 healer 内存 LRU 不跨 session）
2. 失效惩罚机制：使用后仍失败的选择器会被降权
3. 二级索引：selector_hash + url_pattern 加速查询
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import OrderedDict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class CacheEntry:
    """缓存条目"""
    selector: str                    # 原始失效选择器
    healed_selector: str             # 修复后的选择器
    page_url: str = ""               # 页面 URL（模糊匹配用）
    confidence: float = 0.0          # 置信度
    success_count: int = 0           # 成功次数
    fail_count: int = 0              # 失败次数
    last_used: float = 0.0           # 最后使用时间戳
    created_at: float = 0.0          # 创建时间戳

    @property
    def score(self) -> float:
        """加权得分：成功越多分数越高，失败惩罚"""
        if self.success_count + self.fail_count == 0:
            return self.confidence
        return self.confidence * (self.success_count / (self.success_count + self.fail_count * 2))


class SelectorCache:
    """选择器缓存 — JSON 持久化 + LRU"""

    MAX_ENTRIES = 500

    def __init__(self, cache_dir: str):
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_file = self._cache_dir / "selector_cache.json"
        self._entries: OrderedDict[str, CacheEntry] = OrderedDict()
        self._load()

    def _entry_key(self, selector: str, page_url: str = "") -> str:
        """二级索引键：selector_hash + url_pattern"""
        url_pattern = self._url_pattern(page_url)
        sel_hash = hashlib.md5(selector.encode()).hexdigest()[:8]
        return f"{sel_hash}:{url_pattern}"

    @staticmethod
    def _url_pattern(url: str) -> str:
        """将 URL 提取为模式（去掉 query 和 hash，保留 path）"""
        try:
            if "://" in url:
                path = url.split("://", 1)[1].split("?", 1)[0].split("#", 1)[0]
                # 去掉域名，只保留路径
                if "/" in path:
                    path = "/" + path.split("/", 1)[1] if "/" in path else "/"
                return path
            return url
        except Exception:
            return url

    def lookup(self, selector: str, page_url: str = "") -> Optional[CacheEntry]:
        """查找缓存"""
        key = self._entry_key(selector, page_url)
        entry = self._entries.get(key)
        if entry:
            # 移到末尾（LRU）
            self._entries.move_to_end(key)
            entry.last_used = time.time()
        return entry

    def store(self, selector: str, healed_selector: str, page_url: str = "", confidence: float = 0.0) -> None:
        """存储修复记录"""
        key = self._entry_key(selector, page_url)
        existing = self._entries.get(key)
        if existing:
            existing.healed_selector = healed_selector
            existing.confidence = max(existing.confidence, confidence)
            existing.success_count += 1
            existing.last_used = time.time()
            self._entries.move_to_end(key)
        else:
            entry = CacheEntry(
                selector=selector,
                healed_selector=healed_selector,
                page_url=page_url,
                confidence=confidence,
                success_count=1,
                last_used=time.time(),
                created_at=time.time(),
            )
            self._entries[key] = entry

        # LRU 淘汰
        while len(self._entries) > self.MAX_ENTRIES:
            self._entries.popitem(last=False)

        self._save()

    def mark_failed(self, selector: str, page_url: str = "") -> None:
        """标记缓存条目失败（失效惩罚）"""
        key = self._entry_key(selector, page_url)
        entry = self._entries.get(key)
        if entry:
            entry.fail_count += 1
            self._save()

    def _load(self) -> None:
        """从 JSON 加载缓存"""
        if self._cache_file.exists():
            try:
                data = json.loads(self._cache_file.read_text(encoding="utf-8"))
                for key, entry_dict in data.items():
                    self._entries[key] = CacheEntry(**entry_dict)
            except Exception:
                self._entries = OrderedDict()

    def _save(self) -> None:
        """持久化到 JSON"""
        try:
            data = {k: asdict(v) for k, v in self._entries.items()}
            self._cache_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass


class L1CacheMatcher:
    """L1: 历史缓存优先匹配"""

    def __init__(self, cache: SelectorCache):
        self._cache = cache

    def heal(self, selector: str, page_url: str = "") -> Optional[tuple[str, float]]:
        """尝试从缓存中获取修复方案

        Returns:
            (healed_selector, confidence) 或 None
        """
        entry = self._cache.lookup(selector, page_url)
        if entry and entry.score >= 0.5:  # 缓存最低门槛
            return entry.healed_selector, min(entry.score, 1.0)
        return None
