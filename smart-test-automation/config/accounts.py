#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试账号配置文件

包含所有项目的测试账号和机构信息，
按项目和环境分类管理，密码从环境变量读取。
"""

import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from pathlib import Path
from loguru import logger

# 自动加载 .env 文件，避免硬编码密码
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass


@dataclass
class TestAccount:
    """测试账号数据类"""
    account: str
    password: str
    org_id: str
    org_name: str
    role: str
    description: str


@dataclass
class ProjectConfig:
    """项目配置数据类"""
    name: str
    base_url: str           # 项目主域名（如 https://deman.test.zcygov.cn）
    login_page_url: str     # 前端登录页面URL（浏览器打开，供手动登录）
    login_api_url: str      # API登录接口URL（程序调用，如 /oauth/token）
    auth_header: str
    auth_type: str          # token, cookie
    accounts: List[TestAccount]


class AccountManager:
    """测试账号管理器

    统一管理多个项目的测试账号，密码从环境变量读取。

    用法::

        # 获取凭证
        creds = AccountManager.get_login_credentials("web-demand")

        # 获取所有账号
        accounts = AccountManager.get_all_accounts("web-demand")

        # 获取指定角色账号
        admins = AccountManager.get_accounts_by_role("web-demand", "admin")
    """

    _configs: Dict[str, ProjectConfig] = {}

    @classmethod
    def _init_configs(cls) -> None:
        """初始化配置"""
        if cls._configs:
            return

        cls._configs = {
            "web-demand": ProjectConfig(
                name="web-demand",
                base_url=os.environ.get("WEB_DEMAND_URL"),
                login_page_url=os.environ.get("WEB_DEMAND_LOGIN_PAGE_URL"),
                login_api_url=os.environ.get("WEB_DEMAND_LOGIN_API_URL", ""),
                auth_header=os.environ.get("WEB_DEMAND_AUTH_HEADER"),
                auth_type="token",
                accounts=[
                    TestAccount(
                        account=os.environ.get("WEB_DEMAND_ACCOUNT"),
                        password=os.environ.get("WEB_DEMAND_PASSWORD"),
                        org_id="10001000304257",
                        org_name="拓麦科技",
                        role="admin",
                        description="管理员账号",
                    ),
                    TestAccount(
                        account="tmind_1",
                        password=os.environ.get("WEB_DEMAND_PASSWORD"),
                        org_id="10001000304257",
                        org_name="拓麦科技",
                        role="user",
                        description="普通用户账号",
                    ),
                    TestAccount(
                        account="tmind_002",
                        password=os.environ.get("WEB_DEMAND_PASSWORD"),
                        org_id="10001000304257",
                        org_name="拓麦科技",
                        role="viewer",
                        description="查看者账号",
                    ),
                ],
            ),
        }

    @classmethod
    def get_project_config(cls, project: str) -> Optional[ProjectConfig]:
        """获取项目配置"""
        cls._init_configs()
        return cls._configs.get(project)

    @classmethod
    def get_all_accounts(cls, project: str) -> List[TestAccount]:
        """获取项目所有账号"""
        config = cls.get_project_config(project)
        return config.accounts if config else []

    @classmethod
    def get_account(cls, project: str, account: str) -> Optional[TestAccount]:
        """获取指定账号"""
        accounts = cls.get_all_accounts(project)
        for acc in accounts:
            if acc.account == account:
                return acc
        return None

    @classmethod
    def get_accounts_by_role(cls, project: str, role: str) -> List[TestAccount]:
        """获取指定角色的所有账号"""
        accounts = cls.get_all_accounts(project)
        return [acc for acc in accounts if acc.role == role]

    @classmethod
    def get_accounts_by_org(cls, project: str, org_id: str) -> List[TestAccount]:
        """获取指定机构的所有账号"""
        accounts = cls.get_all_accounts(project)
        return [acc for acc in accounts if acc.org_id == org_id]

    @classmethod
    def get_random_account(cls, project: str) -> Optional[TestAccount]:
        """获取随机账号"""
        import random
        accounts = cls.get_all_accounts(project)
        return random.choice(accounts) if accounts else None

    @classmethod
    def list_projects(cls) -> List[str]:
        """列出所有项目"""
        cls._init_configs()
        return list(cls._configs.keys())

    @classmethod
    def get_login_credentials(cls, project: str, account: Optional[str] = None) -> Dict[str, str]:
        """获取登录凭证

        Args:
            project: 项目名称
            account: 可选账号名（不指定则使用第一个账号）

        Returns:
            Dict: 包含 account, password, base_url, auth_header 等的字典
        """
        config = cls.get_project_config(project)
        if not config:
            return {}

        if account:
            acc = cls.get_account(project, account)
        else:
            accounts = cls.get_all_accounts(project)
            acc = accounts[0] if accounts else None

        if not acc:
            return {}

        return {
            "account": acc.account,
            "password": acc.password,
            "org_id": acc.org_id,
            "org_name": acc.org_name,
            "role": acc.role,
            "base_url": config.base_url,
            "login_page_url": config.login_page_url,
            "login_api_url": config.login_api_url,
            "auth_header": config.auth_header,
            "auth_type": config.auth_type,
        }

    @classmethod
    def auto_login(cls, project: str) -> Optional[Any]:
        """自动登录项目，返回 AuthManager 实例"""
        from core.auth_manager import AuthManager

        creds = cls.get_login_credentials(project)
        if not creds:
            logger.warning(f"[Account] No account for: {project}")
            return None

        auth = AuthManager.get_instance(project)
        auth.configure(creds["base_url"], creds["auth_type"])

        if creds["auth_type"] == "token":
            auth.login_with_password(
                creds["login_api_url"],
                creds["account"],
                creds["password"],
                creds.get("auth_header"),
            )
        else:
            auth.login_with_cookie(
                creds["login_api_url"],
                creds["account"],
                creds["password"],
            )

        return auth


if __name__ == "__main__":
    import sys

    project = sys.argv[1] if len(sys.argv) > 1 else None
    AccountManager._init_configs()

    if project:
        AccountManager.get_login_credentials(project)
    else:
        for proj in AccountManager.list_projects():
            creds = AccountManager.get_login_credentials(proj)
            if creds:
                print(f"\n项目: {proj}")
                print(f"  Base URL: {creds['base_url']}")
                print(f"  账号: {creds['account']}")
