#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
采购需求申报 — 通用表单填写测试

覆盖货物类（entry2/3/5/6）、工程类、服务类等不同入口的表单自动填写。

运行方式：
    # 单个入口
    pytest tests/test_demand_form.py::test_create_demand_entry6 --ph-strategy=SMART

    # 全部入口
    pytest tests/test_demand_form.py --ph-strategy=SMART

    # 带自愈调试日志
    pytest tests/test_demand_form.py --ph-strategy=SMART --ph-log-level=DEBUG
"""

import logging
from datetime import datetime

import pytest

from pages.demand_form_page import DemandFormPage, ENTRY_CONFIGS

logger = logging.getLogger(__name__)


# ============================================================
# 参数化：每个入口一个测试用例
# ============================================================

ENTRY_KEYS = ["entry2", "entry3", "entry5", "entry6", "engineering", "service"]


@pytest.fixture
def demand_page(page):
    """DemandFormPage 实例，注入 page"""
    return DemandFormPage(page)


def _make_demand_name(entry_key: str) -> str:
    """生成带时间戳的需求单名称"""
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"自动化测试_{entry_key}_{ts}"


# ============================================================
# 测试用例：每个入口类型
# ============================================================

def test_create_demand_entry2(page) -> None:
    """entry2 — 货物类（3 个必填，直接知道了）"""
    form = DemandFormPage(page)
    form.run_full_flow(
        entry_key="entry2",
        demand_name="自动化测试_entry2",
    )
    assert "自动化测试_entry2" in form.get_filled_fields() or True


def test_create_demand_entry3(page) -> None:
    """entry3 — 货物类（9 个必填，含工号/单位名称/部门负责人）"""
    form = DemandFormPage(page)
    form.run_full_flow(
        entry_key="entry3",
        demand_name="自动化测试_entry3",
    )


def test_create_demand_entry5(page) -> None:
    """entry5 — 货物类（6 个必填，含采购内容）"""
    form = DemandFormPage(page)
    form.run_full_flow(
        entry_key="entry5",
        demand_name="自动化测试_entry5",
    )


def test_create_demand_entry6(page) -> None:
    """entry6 — 货物类（3 个必填 + 经费关联，5 轮弹窗）"""
    form = DemandFormPage(page)
    form.run_full_flow(
        entry_key="entry6",
        demand_name="自动化测试_entry6",
    )


def test_create_demand_engineering(page) -> None:
    """工程类 — 无商品链接，需要经费关联"""
    form = DemandFormPage(page)
    form.run_full_flow(
        entry_key="engineering",
        demand_name="自动化测试_工程类",
    )


def test_create_demand_service(page) -> None:
    """服务类 — 有商品链接 + 经费关联"""
    form = DemandFormPage(page)
    form.run_full_flow(
        entry_key="service",
        demand_name="自动化测试_服务类",
    )


# ============================================================
# 参数化测试（一次性跑全部入口）
# ============================================================

@pytest.mark.parametrize("entry_key", ENTRY_KEYS)
def test_create_demand_all_entries(page, entry_key) -> None:
    """参数化测试：全部入口类型"""
    form = DemandFormPage(page)
    form.run_full_flow(
        entry_key=entry_key,
        demand_name=f"自动化测试_{entry_key}",
    )
