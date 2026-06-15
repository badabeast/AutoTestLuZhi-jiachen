#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pages 包 — 采购需求申报页面对象层

提供通用表单填写能力，支持货物类、服务类、工程类等不同入口表单。
"""

from .demand_form_page import DemandFormPage, EntryType

__all__ = ["DemandFormPage", "EntryType"]
