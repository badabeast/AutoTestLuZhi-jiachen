"""组件库档案管理器

职责：
- 加载内置档案（self_healing/profiles/ 目录下的 JSON 文件）
- 加载用户自定义档案（config/component_profiles/ 目录）
- 缓存已加载的 Profile 实例
- 提供按名称检索 Profile 能力
- 档案合并：用户自定义同名档案可覆盖内置档案
- 单例模式：全局共享同一份缓存
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from self_healing.component_profile import ComponentLibraryProfile


class ComponentLibraryManager:
    """组件库档案管理器

    职责：
    - 加载内置档案（self_healing/profiles/ 目录下的 JSON 文件）
    - 加载用户自定义档案（config/component_profiles/ 目录）
    - 缓存已加载的 Profile 实例
    - 提供按名称检索 Profile 能力
    - 档案合并：用户自定义同名档案可覆盖内置档案
    """

    BUILTIN_PROFILES_DIR: Path = Path(__file__).parent / "profiles"
    CUSTOM_PROFILES_DIR_NAME: str = "config/component_profiles"

    _instance: Optional["ComponentLibraryManager"] = None
    _profiles: dict[str, ComponentLibraryProfile] = {}

    def __new__(cls) -> "ComponentLibraryManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_all()
        return cls._instance

    @property
    def custom_profiles_dir(self) -> Path:
        """获取自定义档案目录，支持环境变量覆盖"""
        env_dir = os.environ.get("COMPONENT_PROFILES_DIR", "")
        if env_dir:
            return Path(env_dir)
        # 默认从项目根目录查找
        return Path(self.CUSTOM_PROFILES_DIR_NAME)

    def _load_all(self) -> None:
        """加载所有档案：先内置，再自定义（覆盖同名）"""
        self._profiles.clear()

        # 内置档案
        if self.BUILTIN_PROFILES_DIR.exists():
            for f in self.BUILTIN_PROFILES_DIR.glob("*.json"):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    profile = ComponentLibraryProfile.from_dict(d)
                    self._profiles[profile.name] = profile
                except Exception:
                    pass

        # 用户自定义档案（覆盖同名内置）
        custom_dir = self.custom_profiles_dir
        if custom_dir.exists():
            for f in custom_dir.glob("*.json"):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    profile = ComponentLibraryProfile.from_dict(d)
                    self._profiles[profile.name] = profile
                except Exception:
                    pass

    def get_profile(self, name: str) -> Optional[ComponentLibraryProfile]:
        """按名称获取组件库档案

        Args:
            name: 档案名称，如 "ant_design", "custom_lib_xxx"

        Returns:
            对应的 ComponentLibraryProfile 实例，不存在则返回 None
        """
        return self._profiles.get(name)

    def list_profiles(self) -> list[ComponentLibraryProfile]:
        """列出所有可用档案

        Returns:
            所有已加载的 ComponentLibraryProfile 列表
        """
        return list(self._profiles.values())

    def list_profile_names(self) -> list[str]:
        """列出所有可用档案名称

        Returns:
            所有已加载的档案名称列表
        """
        return list(self._profiles.keys())

    def get_active_profiles(self, detected_libraries: list[str]) -> list[ComponentLibraryProfile]:
        """获取当前页面激活的档案列表

        Args:
            detected_libraries: 组件库检测器识别到的组件库名称列表

        Returns:
            激活的 ComponentLibraryProfile 列表（仅在已加载档案中存在的）
        """
        return [self._profiles[name] for name in detected_libraries if name in self._profiles]

    def reload(self) -> None:
        """重新加载所有档案（热更新用）

        清空缓存并重新从磁盘加载所有内置和自定义档案。
        适用于修改了自定义档案后需要立即生效的场景。
        """
        self._profiles.clear()
        self._load_all()
