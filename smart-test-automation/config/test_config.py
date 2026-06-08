#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试配置管理类

统一管理所有项目的测试配置。
"""

import os
from typing import Dict, Optional
from enum import Enum
from pathlib import Path

# 自动加载 .env 文件
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

class TestEnvironment(str, Enum):
    """测试环境枚举"""
    TEST = "test"
    STAGING = "staging"
    PRO = "pro"


class EnvProjectConfig:
    """项目环境配置（用于 TestConfig 内部，与 config/accounts.py 的 ProjectConfig 不同）"""

    def __init__(
        self,
        name: str,
        base_url: str,
        api_prefix: str = "/api",
        login_account: str = "",
        login_password: str = "",
        auth_header: Optional[str] = None,
    ):
        self.name = name
        self.base_url = base_url
        self.api_prefix = api_prefix
        self.login_account = login_account
        self.login_password = login_password
        self.auth_header = auth_header


class TestConfig:
    """测试配置管理类

    用法::

        config = TestConfig.get_instance("web-car")
        url = config.get_base_url()
        api_url = config.get_api_url("/users")
        creds = config.get_login_credentials()

    环境通过 URL 域名自动识别：
        .test. → TEST, staging. → STAGING, www.zcygov.cn → PRO
    """

    _instances: Dict[str, "TestConfig"] = {}
    _projects: Dict[str, EnvProjectConfig] = {}

    def __init__(self, project: str = "default"):
        self.project: str = project
        self._load_project_configs()
        self.env: TestEnvironment = self._detect_env()

    @staticmethod
    def _detect_env_from_url(url: str) -> TestEnvironment:
        """从 URL 域名自动识别环境"""
        if ".test." in url:
            return TestEnvironment.TEST
        if "staging." in url:
            return TestEnvironment.STAGING
        if "zcygov.cn" in url:
            return TestEnvironment.PRO
        return TestEnvironment.TEST

    def _detect_env(self) -> TestEnvironment:
        """从当前项目 URL 自动识别环境"""
        config = self.get_project_config()
        return self._detect_env_from_url(config.base_url)

    def _load_project_configs(self) -> None:
        """加载项目配置"""
        self._projects = {
            "web-car": EnvProjectConfig(
                name="web-car",
                base_url=os.environ.get("WEB_CAR_URL", "https://vehicle.test.zcygov.cn"),
                api_prefix="/api/car",
                login_account=os.environ.get("WEB_CAR_ACCOUNT", ""),
                login_password=os.environ.get("WEB_CAR_PASSWORD", ""),
                auth_header=os.environ.get("WEB_CAR_AUTH_HEADER", ""),
            ),
            "web-demand": EnvProjectConfig(
                name="web-demand",
                base_url=os.environ.get("WEB_DEMAND_URL", "https://www.test.zcygov.cn"),
                api_prefix="/api/demand",
                login_account=os.environ.get("WEB_DEMAND_ACCOUNT", ""),
                login_password=os.environ.get("WEB_DEMAND_PASSWORD", ""),
                auth_header=os.environ.get("WEB_DEMAND_AUTH_HEADER", ""),
            ),
        }

    @classmethod
    def get_instance(cls, project: str = "default") -> "TestConfig":
        """获取配置单例实例"""
        if project not in cls._instances:
            cls._instances[project] = cls(project)
        return cls._instances[project]

    def get_project_config(self, project: Optional[str] = None) -> EnvProjectConfig:
        """获取项目配置"""
        project_name = project or self.project
        return self._projects.get(project_name, self._projects.get("web-car"))

    def get_base_url(self, project: Optional[str] = None) -> str:
        """获取项目基础 URL"""
        config = self.get_project_config(project)
        return config.base_url

    def get_api_url(self, endpoint: str, project: Optional[str] = None) -> str:
        """获取完整的 API URL"""
        config = self.get_project_config(project)
        return f"{config.base_url}{config.api_prefix}{endpoint}"

    def get_login_credentials(self, project: Optional[str] = None) -> Dict[str, str]:
        """获取登录凭证"""
        config = self.get_project_config(project)
        return {
            "account": config.login_account,
            "password": config.login_password,
        }

    def get_auth_header(self, project: Optional[str] = None) -> Optional[str]:
        """获取认证头"""
        config = self.get_project_config(project)
        return config.auth_header

    @classmethod
    def from_env(cls, project: str = "web-car") -> "TestConfig":
        """从环境变量创建配置实例"""
        return cls.get_instance(project)

    def get_env(self) -> TestEnvironment:
        """获取当前测试环境"""
        return self.env

    def is_production(self) -> bool:
        """是否为正式环境"""
        return self.env == TestEnvironment.PRO

    def is_test_env(self) -> bool:
        """是否为非生产环境"""
        return self.env in [TestEnvironment.TEST, TestEnvironment.STAGING]
