#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用采购需求表单填写页面对象 — DemandFormPage

核心能力：
  - 动态扫描页面必填字段（不硬编码字段列表）
  - 根据入口类型（货物/服务/工程）自动适配
  - 7 级填充策略：textarea → input → select → cascader → radio → 兜底 input → smart_fill
  - 按 DOM 顺序填写（字段依赖关系：如先填部门再填部门负责人）
  - control-wrapper 逐级向上搜索（最多 8 层）
  - 经费关联弹窗处理
  - 提交后多轮审核弹窗处理

基于 doraemon 组件库的页面结构：
  .doraemon-row
    ├── .doraemon-col.doraemon-form-item-label    ← 字段标签
    └── .doraemon-col.doraemon-form-item-control-wrapper  ← 控件容器

关键教训（来自经验沉淀）：
  - 红色星号 * 是 CSS 伪元素 ::before，text_content() 拿不到
  - 必须用 .doraemon-form-item-required class 识别必填字段
  - label 和 control-wrapper 不一定是直接兄弟关系，需逐级搜索
  - 不能用硬编码字段列表，必须动态扫描页面
"""

import re
import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, List, Tuple, Any

from playwright.sync_api import Page, Locator

logger = logging.getLogger(__name__)


# ============================================================
# 入口类型枚举 & 配置
# ============================================================

class EntryType(str, Enum):
    """采购需求入口类型"""
    GOODS = "goods"           # 货物类
    SERVICE = "service"       # 服务类
    ENGINEERING = "engineering"  # 工程类


@dataclass
class EntryConfig:
    """入口配置：定义不同入口类型的表单处理差异"""
    entry_type: EntryType
    entrance_name: str         # 入口按钮文本（如 "货物类"、"服务类"、"工程类"）
    need_product_link: bool    # 是否需要商品链接识别
    need_budget_bind: bool     # 是否需要经费关联
    need_org_form: bool        # 是否需要组织形式（cascader）
    submit_popup_rounds: int   # 提交后弹窗轮数（0=直接知道了）
    extra_skip_fields: List[str] = field(default_factory=list)  # 需要跳过的字段关键词


# 预设入口配置
ENTRY_CONFIGS: Dict[str, EntryConfig] = {
    "entry2": EntryConfig(
        entry_type=EntryType.GOODS,
        entrance_name="",  # 通过 nth 或名称匹配
        need_product_link=True,
        need_budget_bind=False,
        need_org_form=True,
        submit_popup_rounds=1,  # 直接点"知道了"
    ),
    "entry3": EntryConfig(
        entry_type=EntryType.GOODS,
        entrance_name="",
        need_product_link=True,
        need_budget_bind=False,
        need_org_form=True,
        submit_popup_rounds=5,
    ),
    "entry5": EntryConfig(
        entry_type=EntryType.GOODS,
        entrance_name="",
        need_product_link=True,
        need_budget_bind=False,
        need_org_form=True,
        submit_popup_rounds=3,
    ),
    "entry6": EntryConfig(
        entry_type=EntryType.GOODS,
        entrance_name="",
        need_product_link=True,
        need_budget_bind=True,
        need_org_form=True,
        submit_popup_rounds=5,
    ),
    "engineering": EntryConfig(
        entry_type=EntryType.ENGINEERING,
        entrance_name="工程类",
        need_product_link=False,
        need_budget_bind=True,
        need_org_form=True,
        submit_popup_rounds=5,
    ),
    "service": EntryConfig(
        entry_type=EntryType.SERVICE,
        entrance_name="服务类",
        need_product_link=True,
        need_budget_bind=True,
        need_org_form=True,
        submit_popup_rounds=5,
    ),
}


# ============================================================
# 必填字段默认值配置
# ============================================================

# 通过关键词匹配字段标签，给定默认值
# 优先级：_value_overrides > REQUIRED_FIELD_DEFAULTS > 关键词推断
REQUIRED_FIELD_DEFAULTS: Dict[str, str] = {
    "需求单名称": "自动化测试需求单",
    "联系人姓名": "测试人员",
    "申请人部门": "测试部",
    "采购内容": "办公用品采购",
    "需求单编号": "AUTO-TEST-001",
    "工号": "10001",
    "单位名称": "测试单位",
}


# ============================================================
# DemandFormPage — 通用表单填写页面对象
# ============================================================

class DemandFormPage:
    """通用采购需求表单填写页面对象

    使用方式：
        page = DemandFormPage(healing_page, config)
        page.navigate_to_demand_page()
        page.click_create_demand("entry6")
        page.auto_fill_required_fields()
        page.select_products()          # 货物/服务类
        page.bind_budget()              # 需要经费关联时
        page.submit_and_handle_popups()
    """

    # ── doraemon 组件库选择器常量 ──
    LABEL_SELECTOR = ".doraemon-form-item-label"
    REQUIRED_CLASS = "doraemon-form-item-required"
    CONTROL_WRAPPER_SELECTOR = ".doraemon-form-item-control-wrapper"
    ROW_SELECTOR = ".doraemon-row"
    MAX_SEARCH_LEVELS = 8  # control-wrapper 最大搜索层数

    # ── 控件选择器 ──
    TEXTAREA_SELECTOR = "textarea.doraemon-input, textarea"
    INPUT_TEXT_SELECTOR = "input.doraemon-input:not([type='radio']):not([type='checkbox']):not([type='hidden'])"
    SELECT_SELECTOR = ".doraemon-select-selection"
    CASCADER_SELECTOR = ".doraemon-cascader-input"
    RADIO_SELECTOR = "input[type='radio'], .doraemon-radio-wrapper"

    def __init__(
        self,
        page: Page,
        config: Optional[EntryConfig] = None,
        value_overrides: Optional[Dict[str, str]] = None,
    ):
        """初始化

        Args:
            page: Playwright Page 对象（通常是 healing_page）
            config: 入口配置，不指定时默认 entry6
            value_overrides: 外部传入的字段值覆盖（如带时间戳的需求单名称）
        """
        self.page = page
        self.config = config or ENTRY_CONFIGS["entry6"]
        self._value_overrides: Dict[str, str] = value_overrides or {}
        self._filled_fields: List[str] = []  # 已填写的字段标签（去重）

    # ============================================================
    # 导航
    # ============================================================

    def navigate_to_demand_page(self, base_url: str = ""):
        """导航到采购需求申报页面

        流程：采购需求管理 → 采购需求申报
        """
        logger.info("导航到采购需求申报页面")

        # 如果页面在 about:blank 或未指定 base_url，先从 .env 加载并导航
        if not base_url:
            import os
            base_url = os.environ.get("WEB_DEMAND_URL", "")
        if base_url and (self.page.url == "about:blank" or "demand_front" not in self.page.url):
            logger.info(f"先导航到: {base_url}")
            self.page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)  # SPA 路由初始化等待

        # 点击"采购需求管理"
        try:
            self.page.get_by_text("采购需求管理").click()
            time.sleep(1)  # SPA 路由跳转等待
        except Exception:
            logger.warning("点击'采购需求管理'失败，可能已在目标页面")

        # 点击"采购需求申报"
        try:
            demand_btn = self.page.get_by_text("采购需求申报")
            demand_btn.wait_for(state="visible", timeout=10000)
            demand_btn.click()
            time.sleep(1)
        except Exception as e:
            logger.warning(f"点击'采购需求申报'失败: {e}")

    def click_create_demand(self, entry_key: str = ""):
        """点击创建需求入口按钮

        Args:
            entry_key: 入口标识（如 "entry2", "engineering", "service"）
                       为空时使用当前 config 的 entrance_name
        """
        # 如果指定了新的 entry_key，切换 config
        if entry_key and entry_key in ENTRY_CONFIGS:
            self.config = ENTRY_CONFIGS[entry_key]

        entrance_name = self.config.entrance_name
        logger.info(f"点击创建需求入口: {entrance_name or entry_key}")

        # 等待入口按钮异步渲染完成
        self.page.locator(".btn-entrance-wrapper").first.wait_for(
            state="visible", timeout=15000
        )
        time.sleep(1)  # 等待所有入口按钮渲染完成

        if entrance_name:
            # 名称匹配（推荐）
            entrance_btn = self.page.locator(".btn-entrance").filter(
                has_text=entrance_name
            )
            entrance_btn.wait_for(state="visible", timeout=10000)
            entrance_btn.click()
        else:
            # 无名称时按 index 定位（如 entry2/3/5/6）
            # entry6 通常是最后一个（第 6 个入口）
            idx_map = {"entry2": 2, "entry3": 3, "entry5": 5, "entry6": 6}
            idx = idx_map.get(entry_key, 6)
            self.page.locator(
                f"div:nth-child({idx}) > .btn-entrance-wrapper > .btn-entrance > .m-btn-wrapper"
            ).click()

        # 等待表单异步渲染
        self._wait_for_form_loaded()

    def _wait_for_form_loaded(self, timeout: int = 30):
        """等待表单异步渲染完成

        轮询等待页面上出现 textbox 控件（说明表单已渲染）
        """
        logger.info("等待表单加载...")
        for i in range(timeout):
            try:
                textbox_count = self.page.locator(
                    "input.doraemon-input, textarea.doraemon-input"
                ).count()
                if textbox_count > 0:
                    logger.info(f"表单已加载，检测到 {textbox_count} 个输入控件")
                    time.sleep(1)  # 额外等待确保完全渲染
                    return
            except Exception:
                pass
            time.sleep(1)
        logger.warning(f"等待表单加载超时({timeout}s)")

    # ============================================================
    # 核心：动态扫描 + 自动填充必填字段
    # ============================================================

    def auto_fill_required_fields(self, scroll_top: bool = True) -> Dict[str, Any]:
        """动态扫描页面所有可见的必填字段并自动填充

        核心流程：
          1. 扫描 .doraemon-form-item-required（可见的）→ 必填字段列表
          2. 按 DOM 顺序逐个处理（保证字段依赖关系）
          3. 对每个字段：找 control-wrapper → 检查是否已填 → 7 级策略填充

        Args:
            scroll_top: 填充前是否滚动到页面顶部

        Returns:
            填充结果摘要 {"filled": [...], "skipped": [...], "failed": [...]}
        """
        if scroll_top:
            self.page.evaluate("window.scrollTo(0, 0)")
            time.sleep(0.5)

        result = {"filled": [], "skipped": [], "failed": []}

        # 1. 扫描所有可见的必填字段
        required_items = self._scan_required_fields()
        logger.info(f"扫描到 {len(required_items)} 个可见必填字段")

        # 2. 按 DOM 顺序逐个处理（自然保证依赖关系）
        for label_text, label_el in required_items:
            try:
                # 检查是否已填写
                if self._is_field_filled(label_el):
                    result["skipped"].append(label_text)
                    logger.debug(f"  [跳过] {label_text} — 已填写")
                    continue

                # 查找 control-wrapper（逐级搜索）
                control = self._find_control_wrapper(label_el)
                if control is None:
                    # 修复方案 2：entry5 采购内容等复杂嵌套 — 尝试全局搜索
                    control = self._find_control_by_label_text_fallback(label_text)
                if control is None:
                    result["failed"].append(label_text)
                    logger.warning(f"  [失败] {label_text} — 找不到 control-wrapper")
                    continue

                # 确保控件可见
                try:
                    control.scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    pass

                # 7 级填充策略
                success = self._try_fill_field(label_text, control)
                if success:
                    result["filled"].append(label_text)
                    self._filled_fields.append(label_text)
                    logger.info(f"  [填充] {label_text}")
                else:
                    result["failed"].append(label_text)
                    logger.warning(f"  [失败] {label_text} — 所有策略均未成功")

            except Exception as e:
                result["failed"].append(label_text)
                logger.error(f"  [异常] {label_text}: {e}")

        logger.info(
            f"填充完成: 成功={len(result['filled'])}, "
            f"跳过={len(result['skipped'])}, 失败={len(result['failed'])}"
        )
        return result

    def _scan_required_fields(self) -> List[Tuple[str, Locator]]:
        """扫描页面上所有可见的必填字段

        Returns:
            [(字段标签文本, label元素Locator), ...] 按 DOM 顺序排列
        """
        required_fields = []

        # 选择所有带必填 class 的 label 元素
        items = self.page.locator(f".{self.REQUIRED_CLASS}")
        count = items.count()

        for i in range(count):
            item = items.nth(i)

            # 只处理可见的（过滤隐藏字段）
            try:
                if not item.is_visible():
                    continue
            except Exception:
                continue

            # 提取标签文本（去掉红色星号伪元素的影响）
            label_text = self._extract_label_text(item)
            if not label_text:
                continue

            required_fields.append((label_text, item))

        return required_fields

    def _extract_label_text(self, label_el: Locator) -> str:
        """从 label 元素提取纯文本（去掉星号等）

        红色星号 * 是 CSS 伪元素 ::before，text_content() 拿不到
        但有些 label 文本本身可能包含 *
        """
        text = label_el.text_content() or ""
        # 清理：去星号、去空白
        text = text.replace("*", "").strip()
        # 去掉可能的中文冒号
        text = text.replace(":", "").replace("：", "").strip()
        return text

    def _find_control_wrapper(self, label_el: Locator) -> Optional[Locator]:
        """从 label 元素逐级向上搜索 control-wrapper

        label 和 control-wrapper 不一定是直接兄弟关系，
        需要在 .doraemon-row 级别或更高层查找。

        搜索策略（最多 MAX_SEARCH_LEVELS 层）：
          parent = label_el.locator("..")  逐级向上
          在 parent 中查找 .doraemon-form-item-control-wrapper
        """
        current = label_el

        for level in range(1, self.MAX_SEARCH_LEVELS + 1):
            try:
                parent = current.locator("..")
                # 在 parent 级别查找 control-wrapper
                controls = parent.locator(self.CONTROL_WRAPPER_SELECTOR)
                if controls.count() > 0:
                    # 找到了，返回第一个可见的
                    for j in range(controls.count()):
                        ctrl = controls.nth(j)
                        try:
                            if ctrl.is_visible():
                                return ctrl
                        except Exception:
                            continue
                    # 如果都不可见，返回第一个
                    return controls.first
            except Exception:
                pass

            # 继续向上搜索
            current = current.locator("..")

        return None

    def _find_control_by_label_text_fallback(self, label_text: str) -> Optional[Locator]:
        """兜底方案：通过标签文本全局搜索 control-wrapper

        用于 entry5 采购内容等复杂嵌套场景，
        label 和 control-wrapper 可能跨多层嵌套面板（如 tab 面板、折叠面板）。
        """
        try:
            # 先用 label 文本定位到 label 元素
            label_locator = self.page.locator(
                f".{self.LABEL_SELECTOR}"
            ).filter(has_text=label_text)

            if label_locator.count() == 0:
                return None

            label_el = label_locator.first

            """从 label 的父级 .doraemon-row 开始，搜索整个 form 区域
            尝试在 form 上下文中搜索
            尝试找到最近的 doraemon-row 祖先"""
            try:
                row = label_el.locator(
                    "xpath=ancestor::div[contains(@class, 'doraemon-row')]"
                )
                if row.count() > 0:
                    controls = row.first.locator(self.CONTROL_WRAPPER_SELECTOR)
                    if controls.count() > 0:
                        return controls.first
            except Exception:
                pass

            # 尝试在 form 容器中搜索
            for ancestor_sel in ["form", "#doraemon-table-container"]:
                try:
                    if ancestor_sel.startswith("#"):
                        xpath = f"xpath=ancestor::div[@id='{ancestor_sel[1:]}']"
                    else:
                        xpath = f"xpath=ancestor::{ancestor_sel}"
                    ancestor = label_el.locator(xpath)
                    if ancestor.count() > 0:
                        row = ancestor.first.locator(
                            "xpath=.//div[contains(@class, 'doraemon-row')]"
                        ).filter(has_text=label_text)
                        if row.count() > 0:
                            controls = row.first.locator(self.CONTROL_WRAPPER_SELECTOR)
                            if controls.count() > 0:
                                return controls.first
                except Exception:
                    continue

            # 最终兜底：直接在 label 的更宽范围的祖先中搜索
            for extra_levels in range(8, 15):
                try:
                    parent = label_el
                    for _ in range(extra_levels):
                        parent = parent.locator("..")
                    controls = parent.locator(self.CONTROL_WRAPPER_SELECTOR)
                    if controls.count() > 0:
                        for j in range(controls.count()):
                            ctrl = controls.nth(j)
                            try:
                                if ctrl.is_visible():
                                    return ctrl
                            except Exception:
                                continue
                        return controls.first
                except Exception:
                    continue

        except Exception as e:
            logger.debug(f"fallback 搜索失败: {e}")

        return None

    def _is_field_filled(self, label_el: Locator) -> bool:
        """检查字段是否已填写

        查找该 label 对应的 control-wrapper，检查内部控件是否有值。
        """
        try:
            control = self._find_control_wrapper(label_el)
            if control is None:
                return False

            # 检查 input/textarea 是否有值
            inputs = control.locator("input, textarea")
            for i in range(inputs.count()):
                inp = inputs.nth(i)
                value = inp.input_value()
                if value and value.strip():
                    return True

            # 检查 select 是否有选中值（placeholder 是否还在）
            select_placeholder = control.locator(
                ".doraemon-select-selection__placeholder"
            )
            if select_placeholder.count() > 0:
                # placeholder 存在 = 未选择
                return False

            return False
        except Exception:
            return False

    # ============================================================
    # 7 级填充策略
    # ============================================================

    def _try_fill_field(self, label_text: str, control: Locator) -> bool:
        """尝试填充一个字段（7 级策略）

        策略优先级：
          1. textarea — 大文本框（采购内容等）
          2. input[type='text'] — 普通文本输入
          3. select — 下拉选择
          4. cascader — 级联选择器
          5. radio — 单选
          6. 兜底 input — 任意 input
          7. smart_fill — 最终兜底

        Args:
            label_text: 字段标签文本
            control: control-wrapper Locator

        Returns:
            是否填充成功
        """
        value = self._get_field_value(label_text)

        # 策略 1: textarea
        if self._try_fill_textarea(control, value):
            return True

        # 策略 2: input[type='text']
        if self._try_fill_input_text(control, value):
            return True

        # 策略 3: select
        if self._try_fill_select(control, value, label_text):
            return True

        # 策略 4: cascader
        if self._try_fill_cascader(control, value, label_text):
            return True

        # 策略 5: radio
        if self._try_fill_radio(control, value, label_text):
            return True

        # 策略 6: 兜底 input（type 不是 text 的 input，如 number 等）
        if self._try_fill_fallback_input(control, value):
            return True

        # 策略 7: smart_fill — 基于 label 文本定位
        if self._try_smart_fill(label_text, value):
            return True

        return False

    def _get_field_value(self, label_text: str) -> str:
        """获取字段应填的默认值

        优先级：_value_overrides > REQUIRED_FIELD_DEFAULTS > 关键词推断
        """
        # 1. 外部覆盖
        for key, val in self._value_overrides.items():
            if key in label_text:
                return val

        # 2. 默认值配置
        for key, val in REQUIRED_FIELD_DEFAULTS.items():
            if key in label_text:
                return val

        # 3. 关键词推断
        if "名称" in label_text:
            return "自动化测试"
        if "内容" in label_text:
            return "办公用品"
        if "编号" in label_text:
            return "AUTO-001"
        if "姓名" in label_text or "联系人" in label_text:
            return "测试人员"
        if "部门" in label_text:
            return "测试部"

        # 4. 兜底
        return "自动化测试"

    def _try_fill_textarea(self, control: Locator, value: str) -> bool:
        """策略 1: 填充 textarea"""
        try:
            textarea = control.locator(self.TEXTAREA_SELECTOR)
            if textarea.count() > 0 and textarea.first.is_visible():
                textarea.first.click()
                time.sleep(0.3)
                textarea.first.fill(value)
                time.sleep(0.3)
                return True
        except Exception:
            pass
        return False

    def _try_fill_input_text(self, control: Locator, value: str) -> bool:
        """策略 2: 填充 input[type='text']"""
        try:
            input_el = control.locator(self.INPUT_TEXT_SELECTOR)
            if input_el.count() > 0 and input_el.first.is_visible():
                input_el.first.click()
                time.sleep(0.3)
                input_el.first.fill(value)
                time.sleep(0.3)
                return True
        except Exception:
            pass
        return False

    def _try_fill_select(self, control: Locator, value: str, label_text: str) -> bool:
        """策略 3: 下拉选择（doraemon-select）

        点击 select 触发下拉 → 在选项中匹配默认值 → 点击选项
        """
        try:
            select = control.locator(self.SELECT_SELECTOR)
            if select.count() == 0 or not select.first.is_visible():
                return False

            # 点击展开下拉
            select.first.click()
            time.sleep(0.5)

            # 在全局下拉面板中查找选项（doraemon 的下拉面板渲染在 body 下）
            option = self._find_matching_option(value, label_text)
            if option:
                option.click()
                time.sleep(0.3)
                return True

            # 匹配不到，按 ESC 关闭下拉并选第一个选项
            first_option = self.page.locator(
                ".doraemon-select-dropdown .doraemon-select-dropdown-menu-item"
            ).first
            if first_option.count() > 0 and first_option.is_visible():
                first_option.click()
                time.sleep(0.3)
                return True

            # ESC 关闭
            self.page.keyboard.press("Escape")
            return False

        except Exception:
            try:
                self.page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    def _try_fill_cascader(self, control: Locator, value: str, label_text: str) -> bool:
        """策略 4: 级联选择器（doraemon-cascader）

        级联选择器（如"申请人部门"）：
          点击触发 → 逐级选择 → 最终确认
        """
        try:
            cascader = control.locator(self.CASCADER_SELECTOR)
            if cascader.count() == 0 or not cascader.first.is_visible():
                return False

            # 点击展开级联
            cascader.first.click()
            time.sleep(0.8)

            # 尝试选择第一级的第一个选项
            cascader_menus = self.page.locator(
                ".doraemon-cascader-menus .doraemon-cascader-menu"
            )
            if cascader_menus.count() == 0:
                # 尝试其他选择器
                cascader_menus = self.page.locator(".doraemon-cascader-menu")

            if cascader_menus.count() > 0:
                # 选择第一级第一个可见选项
                first_menu_item = cascader_menus.first.locator(
                    ".doraemon-cascader-menu-item"
                ).first
                if first_menu_item.count() > 0 and first_menu_item.is_visible():
                    first_menu_item.click()
                    time.sleep(0.5)

                    # 等待子级加载，选择第二级（如果存在）
                    time.sleep(0.5)
                    menus = self.page.locator(
                        ".doraemon-cascader-menus .doraemon-cascader-menu"
                    )
                    if menus.count() > 1:
                        second_item = menus.nth(1).locator(
                            ".doraemon-cascader-menu-item"
                        ).first
                        if second_item.count() > 0 and second_item.is_visible():
                            second_item.click()
                            time.sleep(0.3)

                    # 点击空白处关闭（或等自动关闭）
                    self.page.keyboard.press("Escape")
                    time.sleep(0.3)
                    return True

            self.page.keyboard.press("Escape")
            return False

        except Exception:
            try:
                self.page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    def _try_fill_radio(self, control: Locator, value: str, label_text: str) -> bool:
        """策略 5: 单选按钮（doraemon-radio）

        在 control-wrapper 内找 radio 组，匹配默认值文本或选第一个。
        """
        try:
            # 方式 1: doraemon-radio-wrapper（有文本标签的 radio 组）
            radio_wrappers = control.locator(
                ".doraemon-radio-wrapper, label.doraemon-radio-wrapper"
            )
            if radio_wrappers.count() > 0:
                # 尝试匹配 value 文本
                for i in range(radio_wrappers.count()):
                    wrapper = radio_wrappers.nth(i)
                    text = wrapper.text_content() or ""
                    if value in text:
                        wrapper.click()
                        time.sleep(0.3)
                        return True
                # 匹配不到，选第一个
                radio_wrappers.first.click()
                time.sleep(0.3)
                return True

            # 方式 2: 原生 input[type='radio']
            radios = control.locator("input[type='radio']")
            if radios.count() > 0:
                radios.first.check()
                time.sleep(0.3)
                return True

            # 方式 3: doraemon-radio 类名
            radio_labels = control.locator(".doraemon-radio")
            if radio_labels.count() > 0:
                radio_labels.first.click()
                time.sleep(0.3)
                return True

        except Exception:
            pass
        return False

    def _try_fill_fallback_input(self, control: Locator, value: str) -> bool:
        """策略 6: 兜底 input（不限 type）"""
        try:
            inputs = control.locator("input:not([type='radio']):not([type='checkbox']):not([type='hidden']):not([type='file'])")
            if inputs.count() > 0:
                inp = inputs.first
                if inp.is_visible():
                    inp.click()
                    time.sleep(0.3)
                    inp.fill(value)
                    time.sleep(0.3)
                    return True
        except Exception:
            pass
        return False

    def _try_smart_fill(self, label_text: str, value: str) -> bool:
        """策略 7: smart_fill — 基于 label 文本全局定位

        最终兜底：用 get_by_role("textbox", name=...) 或 get_by_label 定位。
        """
        try:
            # 清理 label 文本，构造 name 参数
            clean_label = label_text.replace("*", "").strip()

            # 尝试 get_by_role("textbox", name=...)
            textbox = self.page.get_by_role("textbox", name=clean_label)
            if textbox.count() > 0 and textbox.first.is_visible():
                textbox.first.click()
                time.sleep(0.3)
                textbox.first.fill(value)
                time.sleep(0.3)
                return True

            # 尝试 get_by_label
            by_label = self.page.get_by_label(clean_label)
            if by_label.count() > 0 and by_label.first.is_visible():
                by_label.first.click()
                time.sleep(0.3)
                by_label.first.fill(value)
                time.sleep(0.3)
                return True

        except Exception:
            pass
        return False

    # ============================================================
    # 选项匹配
    # ============================================================

    def _find_matching_option(self, value: str, label_text: str = "") -> Optional[Locator]:
        """在下拉面板中查找匹配的选项

        doraemon 的下拉面板通常渲染在 body 下，不在 control-wrapper 内。
        """
        try:
            # 等待下拉面板出现
            time.sleep(0.5)

            # doraemon-select 下拉选项
            options = self.page.locator(
                ".doraemon-select-dropdown-menu-item, "
                ".doraemon-select-dropdown .doraemon-select-option, "
                "[role='option']"
            )

            option_count = options.count()
            if option_count == 0:
                return None

            # 先精确匹配 value
            for i in range(option_count):
                opt = options.nth(i)
                text = opt.text_content() or ""
                if text.strip() == value:
                    return opt

            # 再模糊匹配
            for i in range(option_count):
                opt = options.nth(i)
                text = opt.text_content() or ""
                if value in text.strip():
                    return opt

            # 找不到匹配项，返回第一个非空选项
            for i in range(option_count):
                opt = options.nth(i)
                text = opt.text_content() or ""
                if text.strip():
                    return opt

        except Exception:
            pass
        return None

    # ============================================================
    # 商品信息处理
    # ============================================================

    def select_products_from_cart(self, timeout: int = 15000):
        """从购物车选品

        货物类和服务类需要选品，工程类跳过。
        """
        if not self.config.need_product_link:
            logger.info("当前入口类型不需要选品，跳过")
            return

        logger.info("从购物车选品...")

        try:
            # 点击"从购物车选品"按钮
            cart_btn = self.page.get_by_role("button", name="从购物车选品")
            cart_btn.wait_for(state="visible", timeout=timeout)
            cart_btn.click()
            time.sleep(1)

            # 等待购物车弹窗加载
            self.page.locator(".doraemon-modal-wrap, [role='dialog']").first.wait_for(
                state="visible", timeout=10000
            )

            # 选择商品（勾选前两个）
            checkboxes = self.page.get_by_role("row").get_by_label("", exact=True)
            selected = 0
            for i in range(checkboxes.count()):
                if selected >= 2:
                    break
                try:
                    cb = checkboxes.nth(i)
                    if cb.is_visible() and not cb.is_checked():
                        cb.check()
                        selected += 1
                        time.sleep(0.3)
                except Exception:
                    continue

            # 点击确定
            confirm_btn = self.page.get_by_role("button", name="确定")
            if confirm_btn.count() > 0:
                confirm_btn.first.click()
                time.sleep(1)

            logger.info(f"选品完成，选了 {selected} 个商品")

        except Exception as e:
            logger.error(f"选品失败: {e}")

    def handle_product_info_fill(self):
        """处理商品信息区域的填写

        提交前可能需要填写商品信息表（采购方式、执行方式等）。
        """
        logger.info("处理商品信息区域...")

        try:
            # 滚动到商品信息区域
            product_header = self.page.get_by_text("商品信息")
            if product_header.count() > 0:
                product_header.first.scroll_into_view_if_needed()
                time.sleep(0.5)

            """扫描商品信息区域的必填字段
            商品信息区域的表单在表格内，可能有不同的结构
            尝试自动填充"""
            self.auto_fill_required_fields(scroll_top=False)

        except Exception as e:
            logger.warning(f"处理商品信息区域异常: {e}")

    def batch_fill_product_info(self):
        """批量填充商品信息（点击"批量填充"按钮）"""
        try:
            batch_btn = self.page.get_by_role("button", name="批量填充")
            if batch_btn.count() > 0 and batch_btn.first.is_visible():
                batch_btn.first.click()
                time.sleep(1)
                logger.info("已点击批量填充")
        except Exception as e:
            logger.warning(f"批量填充失败: {e}")

    # ============================================================
    # 经费关联
    # ============================================================

    def bind_budget(self):
        """经费关联弹窗处理

        精确定位"关联经费"模块下的"立即关联"按钮（不误点"关联预算"）。
        """
        if not self.config.need_budget_bind:
            logger.info("当前入口类型不需要经费关联，跳过")
            return

        logger.info("处理经费关联...")

        try:
            # 滚动到经费关联区域
            budget_section = self.page.get_by_text("关联经费", exact=False)
            if budget_section.count() > 0:
                budget_section.first.scroll_into_view_if_needed()
                time.sleep(0.5)

            # 精确定位：在"关联经费"区域下的"立即关联"按钮
            # 方法 1: 通过父级容器定位
            link_btn = self._find_budget_link_button()
            if link_btn:
                link_btn.click()
                time.sleep(1)
            else:
                # 方法 2: 最后的兜底
                self.page.get_by_text("立即关联", exact=True).last.click()
                time.sleep(1)

            # 填写经费弹窗
            self._fill_budget_dialog()

        except Exception as e:
            logger.error(f"经费关联失败: {e}")

    def _find_budget_link_button(self) -> Optional[Locator]:
        """精确定位"关联经费"区域下的"立即关联"按钮

        修复问题：页面可能同时有"关联预算"和"关联经费"两个区域，
        每个区域下都有"立即关联"按钮，需要精确区分。
        """
        try:
            # 方法 1: 找到包含"关联经费"文本的容器，在其内部找"立即关联"
            budget_sections = self.page.locator(
                "div, section, .doraemon-card"
            ).filter(has_text=re.compile(r"^关联经费"))

            for i in range(budget_sections.count()):
                section = budget_sections.nth(i)
                link_btn = section.locator("text=立即关联")
                if link_btn.count() > 0 and link_btn.first.is_visible():
                    return link_btn.first

            # 方法 2: 通过包含关系 — "关联经费" 的兄弟/父级中有 "立即关联"
            label = self.page.locator(
                ".doraemon-form-item-label, .doraemon-row"
            ).filter(has_text="关联经费")

            if label.count() > 0:
                # 在 label 的父级容器中搜索按钮
                parent = label.first.locator("..")
                for _ in range(5):
                    btn = parent.locator(
                        "button, a, .m-btn-wrapper"
                    ).filter(has_text="立即关联")
                    if btn.count() > 0 and btn.first.is_visible():
                        return btn.first
                    parent = parent.locator("..")

        except Exception as e:
            logger.debug(f"精确定位经费按钮失败: {e}")

        return None

    def _fill_budget_dialog(self):
        """填写经费关联弹窗"""
        logger.info("填写经费弹窗...")

        # 等待弹窗出现
        dialog = self.page.locator(
            ".doraemon-modal-wrap, [role='dialog']"
        ).last
        dialog.wait_for(state="visible", timeout=10000)
        time.sleep(0.5)

        try:
            # 经费项目号
            fund_input = self.page.get_by_role("textbox", name="经费项目号")
            if fund_input.count() > 0 and fund_input.first.is_visible():
                fund_input.first.click()
                fund_input.first.fill(self._value_overrides.get("经费项目号", "1111YCS2233"))
                time.sleep(0.5)

            # 费用类型 — 下拉选择
            expense_select = self.page.locator("#expensesCode")
            if expense_select.count() > 0:
                placeholder = expense_select.locator(
                    ".doraemon-select-selection__placeholder"
                )
                if placeholder.count() > 0 and placeholder.first.is_visible():
                    placeholder.first.click()
                    time.sleep(0.5)
                    # 选择"办公用品"
                    option = self.page.get_by_role("option", name="办公用品")
                    if option.count() > 0:
                        option.first.click()
                        time.sleep(0.5)

            # 预算科目 — 下拉选择（需要先选费用类型才会加载）
            budget_select_texts = [
                "填写卡号和费用项后选择",
                "预算科目",
            ]
            for text in budget_select_texts:
                budget_el = self.page.get_by_text(text)
                if budget_el.count() > 0 and budget_el.first.is_visible():
                    budget_el.first.click()
                    time.sleep(0.5)
                    # 选择第一个选项
                    option = self.page.get_by_role("option").first
                    if option.count() > 0:
                        option.click()
                        time.sleep(0.5)
                    break

            # 经办人 — 下拉搜索选择
            manager_select = self.page.locator("#costManagerId")
            if manager_select.count() > 0:
                placeholder = manager_select.locator(
                    ".doraemon-select-selection__placeholder"
                )
                if placeholder.count() > 0 and placeholder.first.is_visible():
                    placeholder.first.click()
                    time.sleep(0.5)
                    # 搜索关键词
                    search_input = manager_select.locator("input")
                    if search_input.count() > 0:
                        search_input.first.fill("测试")
                        time.sleep(1)  # 等待搜索结果
                    # 选择第一个搜索结果
                    option = self.page.get_by_role("option").first
                    if option.count() > 0 and option.is_visible():
                        option.click()
                        time.sleep(0.3)

            # 点确定
            confirm_btn = dialog.locator("button").filter(has_text="确定")
            if confirm_btn.count() > 0:
                confirm_btn.first.click()
                time.sleep(1)

            logger.info("经费弹窗填写完成")

        except Exception as e:
            logger.error(f"填写经费弹窗失败: {e}")
            # ESC 关闭弹窗
            self.page.keyboard.press("Escape")

    # ============================================================
    # 提交 + 多轮审核弹窗
    # ============================================================

    def submit_and_handle_popups(self, max_rounds: int = 0):
        """提交需求单并处理多轮审核弹窗

        提交流程：
          1. 点击"提交"按钮
          2. 多轮审核弹窗（每轮可能需要搜索选审核人）
          3. 最后一轮点"知道了"完成

        Args:
            max_rounds: 最大弹窗轮数，0 表示使用 config 中的默认值
        """
        rounds = max_rounds or self.config.submit_popup_rounds
        logger.info(f"提交需求单（预计 {rounds} 轮弹窗）...")

        # 点击提交
        try:
            submit_btn = self.page.get_by_role("button", name="提交")
            submit_btn.wait_for(state="visible", timeout=10000)
            submit_btn.click()
            time.sleep(1)
        except Exception as e:
            logger.error(f"点击提交按钮失败: {e}")
            return

        # 处理弹窗
        self._handle_submit_popups(rounds)

    def _handle_submit_popups(self, max_rounds: int = 5):
        """处理提交后的多轮审核弹窗

        弹窗流程（来自经验沉淀）：
          第1轮: 点确定 → 可能报"不能为空" → 搜索选审核人 → 确定
          第2轮: 点确定 → 无报错 → 确定
          第3轮: 点确定 → 可能报"不能为空" → 搜索选审核人 → 确定
          第4轮: 点确定 → 无报错 → 确定
          第5轮: 点击"知道了" → 创建完成
        """
        for round_num in range(1, max_rounds + 2):  # +2 为安全余量
            logger.info(f"弹窗第 {round_num} 轮")

            # 等待弹窗出现
            time.sleep(1.5)

            # 检查是否有"知道了"按钮（最后一步）
            know_btn = self.page.get_by_role("button", name="知道了")
            if know_btn.count() > 0 and know_btn.first.is_visible():
                know_btn.first.click()
                logger.info("点击'知道了'，需求单创建完成")
                time.sleep(1)
                return

            # 检查是否有"确定"按钮
            confirm_btn = self.page.get_by_role("button", name="确定")
            if confirm_btn.count() > 0 and confirm_btn.first.is_visible():
                # 尝试先搜索选审核人（如果弹窗中有搜索框）
                self._try_select_auditor()
                time.sleep(0.5)

                # 点击确定
                confirm_btn.first.click()
                time.sleep(1)

                # 检查是否有错误提示（如"不能为空"）
                error_msg = self.page.locator(
                    ".doraemon-form-explain, .doraemon-message-error"
                )
                if error_msg.count() > 0 and error_msg.first.is_visible():
                    logger.warning("检测到错误提示，尝试填充审核人...")
                    self._try_select_auditor()
                    time.sleep(0.5)
                    # 重新点确定
                    confirm_btn = self.page.get_by_role("button", name="确定")
                    if confirm_btn.count() > 0:
                        confirm_btn.first.click()
                        time.sleep(1)
            else:
                # 没有确定也没有知道了，可能弹窗已消失
                logger.info("未检测到弹窗按钮，弹窗处理结束")
                return

        logger.warning(f"弹窗处理达到最大轮数 {max_rounds}，可能未完成")

    def _try_select_auditor(self):
        """尝试在弹窗中搜索并选择审核人

        审核人 = 当前登录用户（页面右上角获取）
        """
        try:
            username = self._get_current_username()
            if not username:
                logger.warning("无法获取当前用户名，跳过审核人选择")
                return

            # 查找弹窗内的搜索框
            # doraemon-select 搜索选择框
            search_selects = self.page.locator(
                ".doraemon-select-selection__placeholder"
            ).filter(has_text=re.compile(r"请输入后选择|请选择|搜索"))

            if search_selects.count() > 0:
                search_selects.first.click()
                time.sleep(0.3)

                # 输入用户名搜索
                search_input = self.page.locator(
                    ".doraemon-select-search__field, "
                    ".doraemon-select input[type='search'], "
                    ".doraemon-select-selection input"
                )
                if search_input.count() > 0:
                    search_input.first.fill(username[:4])  # 输入前几个字搜索
                    time.sleep(1)  # 等搜索结果

                    # 选择第一个匹配的选项
                    option = self.page.get_by_role("option").first
                    if option.count() > 0 and option.is_visible():
                        option.click()
                        time.sleep(0.3)
                        return

            # 尝试 #auditUsers 定位（来自录制脚本经验）
            audit_select = self.page.locator("#auditUsers")
            if audit_select.count() > 0:
                placeholder = audit_select.locator(
                    ".doraemon-select-selection__placeholder"
                )
                if placeholder.count() > 0:
                    placeholder.first.click()
                    time.sleep(0.3)
                    search_input = audit_select.locator("input")
                    if search_input.count() > 0:
                        search_input.first.fill(username[:4])
                        time.sleep(1)
                    option = self.page.get_by_role("option").first
                    if option.count() > 0 and option.is_visible():
                        option.click()
                        time.sleep(0.3)
                        return

            # 尝试 #aservice_self_purchase_confirm_ 定位（来自录制脚本经验）
            service_select = self.page.locator(
                "[id^='aservice_self_purchase_confirm_']"
            )
            if service_select.count() > 0:
                service_select.first.fill(username[:4])
                time.sleep(1)
                option = self.page.get_by_role("option").first
                if option.count() > 0 and option.is_visible():
                    option.click()
                    time.sleep(0.3)
                    return

        except Exception as e:
            logger.warning(f"选择审核人失败: {e}")

    def _get_current_username(self) -> str:
        """获取当前登录用户名（页面右上角）"""
        try:
            # 选择器来自经验沉淀文档
            username_el = self.page.locator(
                "#back-sky > div > div.microlayout-header-wrap > div > "
                "div.microlayout-header-user > div > div.display-name"
            )
            if username_el.count() > 0:
                return username_el.text_content() or ""

            # 备用选择器
            username_el = self.page.locator(
                ".microlayout-header-user .display-name"
            )
            if username_el.count() > 0:
                return username_el.text_content() or ""

        except Exception:
            pass
        return ""

    # ============================================================
    # 组织形式（cascader）
    # ============================================================

    def fill_org_form(self):
        """填写组织形式（级联选择器）

        不是 select，是 .doraemon-cascader-input
        位于 #doraemon-table-container > form 中
        """
        if not self.config.need_org_form:
            return

        logger.info("填写组织形式（级联选择器）...")

        try:
            cascader = self.page.locator(
                "#doraemon-table-container form .doraemon-cascader-input"
            )
            if cascader.count() == 0:
                # 备用：全局搜索
                cascader = self.page.locator(self.CASCADER_SELECTOR)

            if cascader.count() > 0 and cascader.first.is_visible():
                cascader.first.click()
                time.sleep(0.8)

                # 逐级选择
                menus = self.page.locator(
                    ".doraemon-cascader-menus .doraemon-cascader-menu"
                )
                for level in range(menus.count()):
                    menu_items = menus.nth(level).locator(
                        ".doraemon-cascader-menu-item"
                    )
                    if menu_items.count() > 0:
                        menu_items.first.click()
                        time.sleep(0.5)

                # 关闭
                self.page.keyboard.press("Escape")
                time.sleep(0.3)
                logger.info("组织形式填写完成")

        except Exception as e:
            logger.warning(f"填写组织形式失败: {e}")
            try:
                self.page.keyboard.press("Escape")
            except Exception:
                pass

    # ============================================================
    # 完整流程编排
    # ============================================================

    def run_full_flow(
        self,
        entry_key: str = "entry6",
        base_url: str = "",
        demand_name: str = "",
    ):
        """执行完整的创建需求单流程

        Args:
            entry_key: 入口标识（"entry2", "entry3", "entry5", "entry6",
                       "engineering", "service"）
            base_url: 基础 URL（可选）
            demand_name: 需求单名称（可选，自动加时间戳）
        """
        # 切换配置
        if entry_key in ENTRY_CONFIGS:
            self.config = ENTRY_CONFIGS[entry_key]

        # 需求单名称覆盖
        if demand_name:
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            self._value_overrides["需求单名称"] = f"{demand_name}_{ts}"

        logger.info(f"=== 开始执行 {self.config.entry_type.value} 类需求单创建流程 ===")

        # 1. 导航
        self.navigate_to_demand_page(base_url)

        # 2. 点击创建入口
        self.click_create_demand(entry_key)

        # 3. 自动填充必填字段
        result = self.auto_fill_required_fields()
        logger.info(f"基本表单填充结果: {result}")

        # 4. 填写组织形式
        self.fill_org_form()

        # 5. 选品（货物/服务类）
        if self.config.need_product_link:
            self.select_products_from_cart()

        # 6. 处理商品信息区域
        self.handle_product_info_fill()

        # 7. 批量填充
        self.batch_fill_product_info()

        # 8. 经费关联
        if self.config.need_budget_bind:
            self.bind_budget()

        # 9. 提交 + 处理弹窗
        self.submit_and_handle_popups()

        logger.info(f"=== {self.config.entry_type.value} 类需求单创建流程完成 ===")

    # ============================================================
    # 工具方法
    # ============================================================

    def get_filled_fields(self) -> List[str]:
        """获取已填充的字段列表"""
        return self._filled_fields[:]

    def set_value_override(self, label_keyword: str, value: str):
        """动态设置字段值覆盖

        Args:
            label_keyword: 标签关键词（如 "需求单名称"）
            value: 填充值
        """
        self._value_overrides[label_keyword] = value

    def debug_scan_fields(self) -> List[Dict[str, Any]]:
        """调试用：扫描并返回所有必填字段信息

        Returns:
            [{"label": "字段名", "visible": True, "filled": False, "level": 2}, ...]
        """
        fields_info = []
        items = self.page.locator(f".{self.REQUIRED_CLASS}")
        count = items.count()

        for i in range(count):
            item = items.nth(i)
            try:
                visible = item.is_visible()
                label_text = self._extract_label_text(item)
                filled = self._is_field_filled(item) if visible else None
                control = self._find_control_wrapper(item) if visible else None
                has_control = control is not None

                fields_info.append({
                    "index": i,
                    "label": label_text,
                    "visible": visible,
                    "filled": filled,
                    "has_control_wrapper": has_control,
                })
            except Exception as e:
                fields_info.append({
                    "index": i,
                    "label": "(error)",
                    "visible": False,
                    "filled": None,
                    "has_control_wrapper": False,
                    "error": str(e),
                })

        return fields_info
