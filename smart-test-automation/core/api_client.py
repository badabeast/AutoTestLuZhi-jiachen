#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API 客户端封装类

功能:
- 自动重试机制
- Session 管理
- 认证 token 管理
- 请求/响应日志记录
- 统一的响应格式化
"""

import requests
from typing import Dict, Any, Optional, List
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from loguru import logger


class APIClient:
    """API 客户端封装类

    用法::

        client = APIClient(base_url="https://api.example.com", auth_token="xxx")
        result = client.get("/users")
        result = client.post("/users", json={"name": "test"})
    """

    def __init__(
        self,
        base_url: str,
        auth_token: Optional[str] = None,
        auth_header: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        self.base_url: str = base_url.rstrip("/")
        self.auth_token: Optional[str] = auth_token
        self.auth_header: Optional[str] = auth_header
        self.timeout: int = timeout
        self.session: requests.Session = self._create_session(max_retries)

        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            }
        )

        if self.auth_token:
            self.session.headers["Authorization"] = f"Bearer {self.auth_token}"
        elif self.auth_header:
            self.session.headers["Authorization"] = self.auth_header

    def _create_session(self, max_retries: int) -> requests.Session:
        """创建带重试机制的 Session"""
        session = requests.Session()
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=[
                "HEAD",
                "GET",
                "PUT",
                "DELETE",
                "OPTIONS",
                "TRACE",
                "POST",
            ],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def set_auth_token(self, token: str) -> None:
        """设置认证 Token"""
        self.auth_token = token
        self.session.headers["Authorization"] = f"Bearer {token}"

    def set_auth_header(self, header: str) -> None:
        """设置认证 Header"""
        self.auth_header = header
        self.session.headers["Authorization"] = header

    def request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json: Optional[Dict] = None,
        data: Optional[Any] = None,
        headers: Optional[Dict] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """发送 HTTP 请求

        Args:
            method: HTTP 方法
            endpoint: API 端点
            params: URL 参数
            json: JSON 请求体
            data: 表单数据
            headers: 自定义请求头
            timeout: 超时时间

        Returns:
            Dict: 包含 success, status_code, data, headers, elapsed 等
        """
        url = f"{self.base_url}{endpoint}"
        request_headers = self.session.headers.copy()
        if headers:
            request_headers.update(headers)

        logger.info(f"[API Request] {method} {url}")

        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json,
                data=data,
                headers=request_headers,
                timeout=timeout or self.timeout,
            )

            logger.info(
                f"[API Response] Status: {response.status_code}, "
                f"Time: {response.elapsed.total_seconds():.3f}s"
            )

            result: Dict[str, Any] = {
                "success": response.status_code < 400,
                "status_code": response.status_code,
                "elapsed": response.elapsed.total_seconds(),
                "headers": dict(response.headers),
            }

            try:
                result["data"] = response.json()
            except Exception:
                result["data"] = response.text

            return result

        except requests.Timeout:
            logger.error(f"[API Error] Timeout: {method} {url}")
            return {
                "success": False,
                "status_code": 0,
                "error": "Request timeout",
                "data": None,
            }
        except Exception as e:
            logger.error(f"[API Error] {method} {url}: {str(e)}")
            return {
                "success": False,
                "status_code": 0,
                "error": str(e),
                "data": None,
            }

    def get(self, endpoint: str, params: Optional[Dict] = None, **kwargs: Any) -> Dict[str, Any]:
        """GET 请求"""
        return self.request("GET", endpoint, params=params, **kwargs)

    def post(self, endpoint: str, json: Optional[Dict] = None, **kwargs: Any) -> Dict[str, Any]:
        """POST 请求"""
        return self.request("POST", endpoint, json=json, **kwargs)

    def put(self, endpoint: str, json: Optional[Dict] = None, **kwargs: Any) -> Dict[str, Any]:
        """PUT 请求"""
        return self.request("PUT", endpoint, json=json, **kwargs)

    def delete(self, endpoint: str, **kwargs: Any) -> Dict[str, Any]:
        """DELETE 请求"""
        return self.request("DELETE", endpoint, **kwargs)

    def patch(self, endpoint: str, json: Optional[Dict] = None, **kwargs: Any) -> Dict[str, Any]:
        """PATCH 请求"""
        return self.request("PATCH", endpoint, json=json, **kwargs)

    def upload_file(
        self, endpoint: str, file_path: str, field_name: str = "file", **kwargs: Any
    ) -> Dict[str, Any]:
        """文件上传"""
        url = f"{self.base_url}{endpoint}"
        logger.info(f"[API Upload] POST {url}, File: {file_path}")

        with open(file_path, "rb") as f:
            files = {field_name: f}
            response = self.session.post(url, files=files, timeout=self.timeout)

        return {
            "success": response.status_code < 400,
            "status_code": response.status_code,
            "data": response.json() if response.content else None,
        }

    def download_file(self, endpoint: str, save_path: str, **kwargs: Any) -> bool:
        """文件下载"""
        url = f"{self.base_url}{endpoint}"
        logger.info(f"[API Download] GET {url}, Save: {save_path}")

        response = self.session.get(url, timeout=self.timeout, stream=True)

        if response.status_code == 200:
            with open(save_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info("[API Download] Success")
            return True
        else:
            logger.error(f"[API Download] Failed: {response.status_code}")
            return False

    def close(self) -> None:
        """关闭 Session"""
        self.session.close()

    def __enter__(self) -> "APIClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


class AuthClient(APIClient):
    """认证客户端 - 用于登录获取 Token"""

    LOGIN_URL = "/oauth/token"

    def __init__(
        self,
        base_url: str,
        account: str,
        password: str,
        auth_header: str,
        **kwargs: Any,
    ):
        super().__init__(base_url, **kwargs)
        self.account = account
        self.password = password
        self.auth_header = auth_header
        self._token: Optional[str] = None

    def login(self) -> Optional[str]:
        """执行登录并获取 Token"""
        url = f"{self.base_url}{self.LOGIN_URL}"

        headers = {
            "Authorization": self.auth_header,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = {
            "username": self.account,
            "password": self.password,
            "grant_type": "password",
        }

        logger.info(f"[Auth] Login: {self.account}")

        try:
            response = self.session.post(
                url, data=data, headers=headers, timeout=15
            )

            if response.status_code == 200:
                result = response.json()
                self._token = result.get("access_token")
                self.set_auth_token(self._token)
                logger.info("[Auth] Login Success")
                return self._token
            else:
                logger.error(f"[Auth] Login Failed: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"[Auth] Login Error: {str(e)}")
            return None

    def get_token(self) -> Optional[str]:
        """获取 Token，如果未登录则先登录"""
        if not self._token:
            return self.login()
        return self._token
