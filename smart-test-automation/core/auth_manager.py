#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局认证管理器

功能:
1. 支持 Cookie 和 Token 两种认证方式
2. 全局共享登录态
3. 自动续期机制
4. 多账号支持

注: AccountManager 已统一移至 config/accounts.py
"""

import os
import json
import time
import requests
from typing import Dict, List, Optional, Any
from pathlib import Path
from loguru import logger


class AuthManager:
    """全局认证管理器

    支持:
    - Cookie 认证
    - Token 认证 (Bearer Token)
    - Basic 认证
    """

    _instance: Optional["AuthManager"] = None
    _cache_file: Optional[Path] = None

    def __init__(self, project: str = "default"):
        self.project: str = project
        self.session: requests.Session = requests.Session()

        self.auth_type: str = "token"
        self.base_url: str = ""

        self._token: Optional[str] = None
        self._cookies: Dict[str, str] = {}
        self._auth_header: Optional[str] = None
        self._expires_at: float = 0.0

        self._cache_file = Path(__file__).parent.parent / ".auth_cache"
        self._load_from_cache()

    @classmethod
    def get_instance(cls, project: str = "default") -> "AuthManager":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls(project)
        return cls._instance

    def configure(self, base_url: str, auth_type: str = "token") -> None:
        """配置认证信息"""
        self.base_url = base_url
        self.auth_type = auth_type
        logger.info(f"[Auth] Configure: base_url={base_url}, type={auth_type}")

    def login_with_password(
        self,
        login_url: str,
        account: str,
        password: str,
        auth_header: Optional[str] = None,
        data: Optional[Dict] = None,
    ) -> bool:
        """通过用户名密码登录"""
        try:
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            }
            if auth_header:
                headers["Authorization"] = auth_header

            login_data: Dict[str, Any] = {
                "username": account,
                "password": password,
                "grant_type": "password",
            }
            if data:
                login_data.update(data)

            logger.info(f"[Auth] Login: {account}")

            response = self.session.post(
                login_url, data=login_data, headers=headers, timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                self._token = result.get("access_token")
                self._cookies = dict(response.cookies)
                self._expires_at = time.time() + 3600
                self._save_to_cache()
                logger.info("[Auth] Login Success")
                return True
            else:
                logger.error(f"[Auth] Login Failed: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"[Auth] Login Error: {str(e)}")
            return False

    def login_with_cookie(
        self,
        login_url: str,
        account: str,
        password: str,
        cookie_name: str = "SESSION",
    ) -> bool:
        """通过用户名密码登录，获取 Cookie"""
        try:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            login_data = {"username": account, "password": password}

            logger.info(f"[Auth] Login with Cookie: {account}")

            response = self.session.post(
                login_url, json=login_data, headers=headers, timeout=30
            )

            if response.status_code in [200, 302]:
                cookies = dict(response.cookies)
                if cookie_name in cookies:
                    self._cookies[cookie_name] = cookies[cookie_name]
                    self._auth_header = f"{cookie_name}={cookies[cookie_name]}"
                    self._expires_at = time.time() + 3600
                    self._save_to_cache()
                    logger.info("[Auth] Cookie Login Success")
                    return True
                else:
                    logger.error(f"[Auth] Cookie not found: {cookie_name}")
                    return False
            else:
                logger.error(f"[Auth] Cookie Login Failed: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"[Auth] Cookie Login Error: {str(e)}")
            return False

    def set_token(self, token: str) -> None:
        """设置 Token"""
        self._token = token
        self._expires_at = time.time() + 3600
        self._save_to_cache()
        logger.info("[Auth] Token set")

    def set_cookies(self, cookies: Dict[str, str]) -> None:
        """设置 Cookies"""
        self._cookies = cookies
        self._expires_at = time.time() + 3600
        self._save_to_cache()
        logger.info(f"[Auth] Cookies set: {list(cookies.keys())}")

    def get_token(self) -> Optional[str]:
        """获取 Token"""
        return self._token

    def get_cookies(self) -> Dict[str, str]:
        """获取 Cookies"""
        return self._cookies.copy()

    def get_cookie_string(self) -> str:
        """获取 Cookie 字符串"""
        return "; ".join([f"{k}={v}" for k, v in self._cookies.items()])

    def get_auth_headers(self) -> Dict[str, str]:
        """获取认证 Header"""
        headers: Dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if self._cookies:
            headers["Cookie"] = self.get_cookie_string()
        return headers

    def is_valid(self) -> bool:
        """检查认证是否有效（过期后返回 False，不再凭 token/cookie 存在就判有效）"""
        if not self._expires_at:
            return False
        # 在有效期（含 5 分钟缓冲）内才算有效
        return time.time() < self._expires_at - 300

    def refresh(self, refresh_url: Optional[str] = None) -> bool:
        """刷新认证"""
        if refresh_url:
            try:
                headers = self.get_auth_headers()
                response = self.session.post(
                    refresh_url, headers=headers, timeout=30
                )
                if response.status_code == 200:
                    result = response.json()
                    self._token = result.get("access_token")
                    self._expires_at = time.time() + 3600
                    self._save_to_cache()
                    logger.info("[Auth] Refresh Success")
                    return True
            except Exception as e:
                logger.error(f"[Auth] Refresh Error: {str(e)}")
        return False

    def logout(self) -> None:
        """登出"""
        self._token = None
        self._cookies = {}
        self._expires_at = 0.0
        self._clear_cache()
        logger.info("[Auth] Logged out")

    def _save_to_cache(self) -> None:
        """保存到缓存"""
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_data = {
                "token": self._token,
                "cookies": self._cookies,
                "expires_at": self._expires_at,
                "project": self.project,
            }
            with open(self._cache_file, "w") as f:
                json.dump(cache_data, f)
        except Exception as e:
            logger.error(f"[Auth] Cache save failed: {str(e)}")

    def _load_from_cache(self) -> None:
        """从缓存加载"""
        try:
            if self._cache_file and self._cache_file.exists():
                with open(self._cache_file, "r") as f:
                    cache_data = json.load(f)
                if cache_data.get("project") == self.project:
                    self._token = cache_data.get("token")
                    self._cookies = cache_data.get("cookies", {})
                    self._expires_at = cache_data.get("expires_at", 0.0)
                    if self.is_valid():
                        logger.info("[Auth] Loaded from cache")
        except Exception as e:
            logger.error(f"[Auth] Cache load failed: {str(e)}")

    def _clear_cache(self) -> None:
        """清除缓存"""
        try:
            if self._cache_file and self._cache_file.exists():
                self._cache_file.unlink()
        except Exception:
            pass

    def __enter__(self) -> "AuthManager":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


