#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
两步录制的主流程编排

codegen 录制 → 回放拿 HAR/Trace → 解析 → AI 分析 → 生成增强脚本 → 存 knowledge
"""

import subprocess
import sys
import json
import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)

from .codegen_parser import RecordingASTParser
from .har_parser import HARParser
from .script_transformer import HealingScriptTransformer


class TwoStepRecorder:
    """录制 + 回放 + 解析"""

    def __init__(
        self,
        output_base: str = "output/modules",
        storage_state: str = "login_state/storage_state.json",
        viewport: str = "1366,768", #设置Chrome大小
        har_url_filter: str = "",
    ):
        self.output_base = Path(output_base)
        self.storage_state = storage_state
        self.viewport = viewport
        self.har_url_filter = har_url_filter
        self.codegen_parser = RecordingASTParser()
        self.har_parser = HARParser()
        self.script_transformer = HealingScriptTransformer()

    def record(
        self,
        module_name: str,
        target_url: str,
        storage_state: Optional[str] = None,
        har_url_filter: Optional[str] = None,
        headless_step2: bool = False,
    ) -> Optional[Dict]:
        # 参数兜底
        if storage_state is None:
            storage_state = self.storage_state
        if har_url_filter is None:
            har_url_filter = self.har_url_filter

        # 登录态文件检查
        storage_exists = Path(storage_state).exists()
        if not storage_exists:
            print(f"⚠️ 登录态文件不存在: {storage_state}")
            print(f"   首次录制：启动浏览器后请手动登录，录制+回放后会自动保存登录态\n")

        output_dir = self.output_base / module_name
        output_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: codegen 录制
        raw_script = output_dir / "raw_script.py"
        print(f"\n🎬 Step 1: 启动 codegen 录制 [{module_name}]")
        print(f"   URL: {target_url}")
        if storage_exists:
            print(f"   登录态: {storage_state}")
        else:
            print(f"   登录态: 无（首次录制，请手动登录）")
        print(f"   请在浏览器中完成 [{module_name}] 的全部操作")
        print(f"   操作完成后关闭浏览器即可\n")

        # 启动命令：有登录态才传 --load-storage
        cmd = [
            sys.executable, "-m", "playwright", "codegen",
            "--target=python-pytest",
            f"--output={raw_script}",
            f"--viewport-size={self.viewport}",
            "--ignore-https-errors",
        ]
        if storage_exists:
            cmd.append(f"--load-storage={storage_state}")
        cmd.append(target_url)

        try:
            result = subprocess.run(cmd, timeout=600)  # 10min 超时自动关闭
        except subprocess.TimeoutExpired:
            print(f"\n⏰ 录制超时（10分钟），自动关闭浏览器")
            # 超时后浏览器进程已被终止，检查是否有产出
            if raw_script.exists():
                raw_content = raw_script.read_text(encoding='utf-8').strip()
                if len(raw_content) > 50:
                    print(f"   已有录制内容，继续处理...")
                else:
                    print(f"❌ 录制内容过少，退出")
                    return None
            else:
                print(f"❌ 未生成脚本，退出")
                return None

        if not raw_script.exists():
            print("❌ codegen 未生成脚本，退出")
            return None

        raw_content = raw_script.read_text(encoding='utf-8').strip()
        if not raw_content or len(raw_content) < 50:
            print("❌ codegen 生成的脚本内容过少，可能未录制任何操作")
            return None

        print(f"\n✅ Step 1 完成: {raw_script}")

        # 保存带时间戳的副本
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        versioned_script = output_dir / f"raw_script_{ts}.py"
        shutil.copy2(raw_script, versioned_script)
        print(f"   版本副本: {versioned_script}")

        # Step 2: 回放，顺便录 HAR 和 Trace
        api_har = output_dir / "api.har"
        trace_file = output_dir / "trace.zip"

        print(f"\n🔄 Step 2: 自动回放 + HAR + Trace 录制...")

        preprocessed = self._preprocess_raw_script(str(raw_script), output_dir)

        wrapper_script = self._generate_wrapper_script(
            raw_script_path=str(preprocessed),
            har_path=str(api_har),
            trace_path=str(trace_file),
            storage_state=storage_state,
            storage_exists=storage_exists,
            har_url_filter=har_url_filter,
            headless=headless_step2,
        )

        wrapper_path = output_dir / "_wrapper_recording.py"
        wrapper_path.write_text(wrapper_script, encoding='utf-8')

        pytest_cmd = [
            sys.executable, "-m", "pytest",
            str(wrapper_path),
            "-x", "-v",
        ]

        step2_result = subprocess.run(
            pytest_cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )

        har_exists = api_har.exists()
        trace_exists = trace_file.exists()

        logger.info("Step 2 回放完成: returncode=%d, har=%s, trace=%s",
                     step2_result.returncode, har_exists, trace_exists)

        if step2_result.returncode != 0:
            print(f"⚠️ 回放未完全成功 (exit code: {step2_result.returncode})")
            stderr_lines = (step2_result.stderr or "").split('\n')
            for line in stderr_lines[-15:]:
                if line.strip():
                    print(f"   {line.strip()}")
        else:
            print(f"   回放 pytest 通过")

        if har_exists:
            print(f"✅ Step 2 完成: {api_har}")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            versioned_har = output_dir / f"api_{ts}.har"
            shutil.copy2(api_har, versioned_har)
            print(f"   版本副本: {versioned_har}")
            if trace_exists:
                versioned_trace = output_dir / f"trace_{ts}.zip"
                shutil.copy2(trace_file, versioned_trace)
                print(f"   版本副本: {versioned_trace}")
        else:
            print(f"⚠️ HAR 文件未生成，回放可能失败")
            if step2_result.returncode != 0:
                print(f"   pytest stderr: {step2_result.stderr[:500]}")

        # Step 3: 解析产物
        operations = []
        api_calls = []

        if raw_script.exists():
            try:
                operations = self.codegen_parser.parse(str(raw_script))
                print(f"   UI 操作: {len(operations)} 步")
            except Exception as e:
                print(f"   ⚠️ codegen 解析失败: {e}")

        if har_exists:
            try:
                #去掉静态资源，保留业务 API
                api_calls = self.har_parser.parse_api_sequence(str(api_har))
                all_calls_count = len(self.har_parser.parse(str(api_har)))
                print(f"   全部请求: {all_calls_count}, 业务API: {len(api_calls)}")
            except Exception as e:
                print(f"   ⚠️ HAR 解析失败: {e}")

        # Step 4: AI 分析
        ai_analysis = self._smart_analyze(module_name, operations, api_calls)

        # Step 5: 生成增强脚本 + PO 分层
        enhanced_script = output_dir / "enhanced_script.py"
        try:
            self.script_transformer.transform(
                input_path=str(raw_script),
                output_path=str(enhanced_script),
                module_name=module_name,
                extract_vars=ai_analysis.get("extract_vars", []),
            )
            ts5 = datetime.now().strftime("%Y%m%d_%H%M%S")
            versioned_enhanced = output_dir / f"enhanced_script_{ts5}.py"
            shutil.copy2(enhanced_script, versioned_enhanced)
            print(f"   版本副本: {versioned_enhanced}")

            # PO 分层：BasePage + 业务Page + test用例
            po_dir = output_dir / "po"
            try:
                po_result = self.script_transformer.generate_po_layers(
                    enhanced_script_path=str(enhanced_script),
                    output_dir=str(po_dir),
                    module_name=module_name,
                )
            except Exception as e:
                print(f"   ⚠️ PO 分层生成失败: {e}")
                po_result = {}
        except Exception as e:
            print(f"   ⚠️ 增强脚本转换失败: {e}")
            enhanced_script = None
            po_result = {}

        # Step 6: 打包模块定义，存到 knowledge
        module_def = {
            "module_name": module_name,
            "target_url": target_url,
            "raw_script": str(raw_script),
            "api_har": str(api_har) if har_exists else None,
            "trace": str(trace_file) if trace_exists else None,
            "enhanced_script": str(enhanced_script) if enhanced_script and enhanced_script.exists() else None,
            "po_layers": po_result if po_result else None,
            "operations": [
                {
                    "step_index": op.step_index,
                    "action": op.action,
                    "selector_type": op.selector_type,
                    "selector_value": op.selector_value,
                    "selector_name": op.selector_name,
                    "value": op.value,
                    "raw_line": op.raw_line,
                }
                for op in operations
            ],
            "api_calls": [
                {
                    "step_index": c.step_index,
                    "method": c.method,
                    "url": c.url,
                    "path": c.path,
                    "status": c.status,
                    "request_body": bool(c.request_body),
                    "response_body": c.response_body is not None,
                }
                for c in api_calls
            ],
            "smart_analysis": ai_analysis,
        }

        summary_path = output_dir / "recording_summary.json"
        summary_path.write_text(
            json.dumps(module_def, ensure_ascii=False, indent=2, default=str),
            encoding='utf-8',
        )

        try:
            from knowledge import save_module_definition
            knowledge_path = save_module_definition(module_name, module_def)
            print(f"   模块定义: {knowledge_path}")
        except Exception as e:
            print(f"   ⚠️ 保存模块定义失败: {e}")

        print(f"\n✅ 录制完成!")
        print(f"   UI 操作: {len(operations)}")
        print(f"   业务 API: {len(api_calls)}")
        print(f"   产物目录: {output_dir}")

        return module_def

    def replay(self, module_name: str, headless: bool = False) -> Optional[Dict]:
        """重放已有 raw_script，重新抓 HAR 和 Trace（跳过 codegen）"""
        output_dir = Path(f"output/modules/{module_name}")
        raw_script = output_dir / "raw_script.py"
        if not raw_script.exists():
            print(f"❌ 未找到 raw_script.py: {raw_script}")
            return None

        api_har = output_dir / "api.har"
        trace_file = output_dir / "trace.zip"

        for f in [api_har, trace_file]:
            if f.exists():
                f.unlink()

        print(f"🔄 重放模块: {module_name}")
        print(f"   脚本: {raw_script}")

        # 预处理 raw_script（时间戳+等待+跳过登录），生成 _preprocessed.py
        preprocessed = self._preprocess_raw_script(str(raw_script), output_dir)

        wrapper_content = self._generate_wrapper_script(
            raw_script_path=str(preprocessed),
            har_path=str(api_har),
            trace_path=str(trace_file),
            storage_state=self.storage_state,
            har_url_filter="",
            headless=headless,
        )
        wrapper_path = output_dir / "_wrapper_recording.py"
        wrapper_path.write_text(wrapper_content, encoding='utf-8')
        print(f"   wrapper: {wrapper_path}")

        pytest_cmd = [
            sys.executable, "-m", "pytest",
            str(wrapper_path),
            "-x", "-v", "-s",
        ]
        try:
            result = subprocess.run(
                pytest_cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
            # 输出 pytest 的 stdout（包含调试信息）
            if result.stdout:
                for line in result.stdout.split('\n'):
                    if line.strip():
                        print(f"   {line}")
            if result.returncode != 0 and result.stderr:
                for line in (result.stderr or "").split('\n')[-10:]:
                    if line.strip():
                        print(f"   {line}")
        except subprocess.TimeoutExpired:
            print(f"   ⚠️ 回放超时（300s）")

        # 检查 HAR 结果
        har_exists = api_har.exists()
        trace_exists = trace_file.exists()
        business = []

        if har_exists:
            from recorder.har_parser import HARParser
            parser = HARParser()
            all_calls = parser.parse(str(api_har))
            business = parser.parse_api_sequence(str(api_har))
            print(f"\n✅ HAR 已生成: {api_har}")
            print(f"   总请求数: {len(all_calls)}")
            print(f"   业务API: {len(business)}")
            for c in business:
                print(f"     {c.method:6s} {c.path}")

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(api_har, output_dir / f"api_{ts}.har")
            if trace_exists:
                shutil.copy2(trace_file, output_dir / f"trace_{ts}.zip")
        else:
            print(f"\n⚠️ HAR 未生成")

        return {
            "har_path": str(api_har) if har_exists else None,
            "trace_path": str(trace_file) if trace_exists else None,
            "api_count": len(business) if har_exists else 0,
        }

    def _save_login_state(self, target_url: str, storage_state: str):
        """弹出浏览器让用户手动登录，登录完成后自动保存登录态

        流程:
          1. 启动 Chromium 浏览器，打开目标 URL
          2. 用户在浏览器中手动完成登录操作
          3. 登录成功后在终端按回车确认
          4. 自动保存 cookies + localStorage 到 storage_state 文件

        Args:
            target_url: 目标系统 URL
            storage_state: 登录态保存路径
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("❌ 请先安装 playwright: pip install playwright")
            return

        Path(storage_state).parent.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                viewport={"width": 1366, "height": 768},
                ignore_https_errors=True,
            )
            page = context.new_page()
            page.goto(target_url)

            print(f"\n{'='*60}")
            print(f"🔑 请在浏览器中完成登录操作")
            print(f"   登录成功后，回到终端按【回车】保存登录态...")
            print(f"{'='*60}\n")
            input()

            # 保存登录态
            context.storage_state(path=storage_state)
            print(f"✅ 登录态已保存: {storage_state}")
            browser.close()

    def _preprocess_raw_script(self, raw_script_path: str, output_dir: Path) -> Path:
        """预处理 raw_script：给 fill 加时间戳、goto 后加守卫、提取登录操作"""
        import time as _time
        source = Path(raw_script_path).read_text(encoding="utf-8")

        # 1. 先提取登录操作（用原始 source，不加时间戳）
        login_actions = []
        gotos = list(re.finditer(r'\.goto\(["\']([^"\']+)["\']\)', source))
        if len(gotos) >= 2:
            first_url = gotos[0].group(1)
            if 'login' in first_url.lower():
                between = source[gotos[0].end():gotos[1].start()]
                for line in between.split('\n'):
                    stripped = line.strip()
                    if stripped and any(kw in stripped for kw in ['.fill(', '.click(', '.press(', '.check(']):
                        login_actions.append(stripped)
                lines = between.split('\n')
                cleaned = []
                for line in lines:
                    stripped = line.strip()
                    if (not stripped or stripped.startswith('#')
                        or 'wait_for_load_state' in stripped
                        or 'wait_for_timeout' in stripped):
                        cleaned.append(line)
                    elif any(kw in stripped for kw in ['.fill(', '.click(', '.press(', '.check(']):
                        continue
                    else:
                        cleaned.append(line)
                source = (source[:gotos[0].end()] + '\n'.join(cleaned) + source[gotos[1].start():])
                if login_actions:
                    print(f"   📋 已提取 {len(login_actions)} 个登录操作（SSO 失败时自动使用）")

        # 登录操作存到全局目录
        global_login_actions = Path("login_state/login_actions.py")
        if login_actions:
            global_login_actions.parent.mkdir(parents=True, exist_ok=True)
            global_login_actions.write_text('\n'.join(login_actions), encoding='utf-8')
            print(f"   📋 登录操作已保存到全局: {global_login_actions}")
        elif not global_login_actions.exists():
            global_login_actions.parent.mkdir(parents=True, exist_ok=True)
            global_login_actions.write_text('', encoding='utf-8')

        # 给 fill 的值拼上时间戳，保证每次回放数据不重复
        _ts = _time.strftime("%Y%m%d%H%M%S")
        def _add_ts(match):
            quote = match.group(1)
            value = match.group(2)
            if not value or value.replace(".", "").isdigit():
                return match.group(0)
            if value.startswith("http") or value.startswith("/"):
                return match.group(0)
            if len(value) <= 2:
                return match.group(0)
            return f'.fill({quote}{value}_{_ts}{quote})'
        source = re.sub(r"""\.fill\((["'])([^"']*?)\1\)""", _add_ts, source)

        # goto 后面插一段等待+登录检查
        def _add_guarded_wait(match):
            goto_line = match.group(1)
            return (goto_line + '\n'
                    '    page.wait_for_load_state("networkidle")\n'
                    '    ensure_logged_in(page, page.url)')
        source = re.sub(r'(\.goto\([^)]+\))', _add_guarded_wait, source)

        preprocessed = output_dir / "_preprocessed.py"
        preprocessed.write_text(source, encoding='utf-8')
        return preprocessed

    def _smart_analyze(
        self,
        module_name: str,
        operations: list,
        api_calls: list,
    ) -> Dict[str, Any]:
        """AI 分析：从响应里提取变量、推断模块间依赖"""
        analysis: Dict[str, Any] = {
            "extract_vars": [],
            "dependencies": [],
        }

        if not api_calls:
            return analysis

        # 从响应里找 ID 类字段，这些通常是可提取的变量
        for call in api_calls:
            resp = call.response_body
            if not isinstance(resp, dict):
                continue
            ids = self._extract_ids_from_response(resp)
            for field_path, value in ids.items():
                var_name = f"{module_name}_{field_path.replace('.', '_').replace('[', '_').replace(']', '')}"
                analysis["extract_vars"].append({
                    "name": var_name,
                    "from_api": f"{call.method} {call.path}",
                    "from_field": field_path,
                    "example_value": str(value)[:100],
                })

        # 4b. 从请求体里推断这个模块需要啥外部参数
        for call in api_calls:
            body = call.request_body
            if not isinstance(body, dict):
                continue
            params = self._extract_params_from_request(body)
            for p in params:
                analysis["input_params"] = analysis.get("input_params", [])
                analysis["input_params"].append({
                    "field": p["field"],
                    "value": p["value"],
                    "from_api": f"{call.method} {call.path}",
                })

        # 4c. 试着让 AI 推断一下依赖关系
        try:
            from orchestrator.smart_inference import CrossModuleInferencer
            inferencer = CrossModuleInferencer()
            inferred_deps = inferencer.infer_all()
            for dep in inferred_deps:
                analysis["dependencies"].append({
                    "from_sequence": dep.get("from_sequence"),
                    "from_field": dep.get("from_field"),
                    "to_sequence": dep.get("to_sequence"),
                    "to_field": dep.get("to_field"),
                    "confidence": dep.get("confidence", 0.9),
                    "reasoning": dep.get("reasoning", ""),
                    "source": "ai",
                })
        except Exception:
            pass

        # 4d. 跟已有的模块比对一下，看看有没有依赖
        try:
            from knowledge import list_modules, load_module_definition
            existing_modules = list_modules()
            for existing_name in existing_modules:
                if existing_name == module_name:
                    continue
                existing_def = load_module_definition(existing_name)
                if not existing_def:
                    continue
                dep = self._infer_dependency(module_name, api_calls, existing_name, existing_def)
                if dep:
                    dep["source"] = "cross_module"
                    analysis["dependencies"].append(dep)
        except Exception:
            pass

        if analysis["extract_vars"]:
            print(f"   可提取变量: {len(analysis['extract_vars'])} 个")
        if analysis.get("dependencies"):
            print(f"   推断依赖: {len(analysis['dependencies'])} 个")

        return analysis

    def _extract_ids_from_response(
        self, data: Any, prefix: str = "", max_depth: int = 5
    ) -> Dict[str, Any]:
        """从响应数据里挖 ID 类的字段"""
        if max_depth <= 0:
            return {}

        ids = {}
        # 常见的 ID 关键字
        id_keywords = {"id", "Id", "ID", "uuid", "code", "no", "number", "seq"}

        if isinstance(data, dict):
            for key, value in data.items():
                path = f"{prefix}.{key}" if prefix else key
                if any(kw in key for kw in id_keywords) and value:
                    if isinstance(value, (str, int)) and len(str(value)) < 100:
                        ids[path] = value
                if isinstance(value, dict):
                    ids.update(self._extract_ids_from_response(value, path, max_depth - 1))
                elif isinstance(value, list) and value:
                    for i, item in enumerate(value[:3]):  # 翻前几个就够了
                        if isinstance(item, dict):
                            ids.update(
                                self._extract_ids_from_response(item, f"{path}[{i}]", max_depth - 1)
                            )
        return ids

    @staticmethod
    def _truncate_for_inference(data: Any, max_str_len: int = 500, max_list: int = 10, depth: int = 0) -> Any:
        """砍掉太大的数据，别撑爆 AI prompt"""
        if depth > 5:
            return "...(截断)"
        if isinstance(data, dict):
            return {k: TwoStepRecorder._truncate_for_inference(v, max_str_len, max_list, depth + 1)
                    for k, v in data.items()}
        if isinstance(data, list):
            if len(data) > max_list:
                items = [TwoStepRecorder._truncate_for_inference(i, max_str_len, max_list, depth + 1)
                         for i in data[:max_list]]
                items.append(f"...(共{len(data)}项)")
                return items
            return [TwoStepRecorder._truncate_for_inference(i, max_str_len, max_list, depth + 1)
                    for i in data]
        if isinstance(data, str) and len(data) > max_str_len:
            return data[:max_str_len] + "...(截断)"
        return data

    def _extract_params_from_request(self, data: Any, prefix: str = "", max_depth: int = 4) -> List[Dict]:
        """把请求体里的参数名和值捞出来"""
        params = []
        id_keywords = {"id", "Id", "ID", "uuid", "code"}

        if max_depth <= 0 or not isinstance(data, dict):
            return params

        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else key
            if any(kw in key for kw in id_keywords) and value:
                params.append({"field": path, "value": str(value)[:100]})
            if isinstance(value, dict):
                params.extend(self._extract_params_from_request(value, path, max_depth - 1))
        return params

    def _infer_dependency(
        self,
        current_module: str,
        current_api_calls: list,
        existing_module_name: str,
        existing_module_def: Dict,
    ) -> Optional[Dict]:
        """看看当前模块是不是依赖了某个已有模块的输出"""
        existing_vars = existing_module_def.get("smart_analysis", {}).get("extract_vars", [])
        if not existing_vars:
            return None

        for call in current_api_calls:
            body = call.request_body
            if not isinstance(body, dict):
                continue
            # 把请求体里的值都摊平
            request_values = self._flatten_values(body)
            for var in existing_vars:
                example_val = var.get("example_value", "")
                if example_val and example_val in request_values:
                    return {
                        "depends_on": existing_module_name,
                        "var_mapping": {var["name"]: var.get("from_field", "")},
                        "confidence": 0.85,
                        "reasoning": f"请求中包含 {existing_module_name} 的输出值",
                    }
        return None

    @staticmethod
    def _flatten_values(data: Any) -> List[str]:
        """递归地把 dict 里的字符串值都捞出来"""
        values = []
        if isinstance(data, dict):
            for v in data.values():
                values.extend(TwoStepRecorder._flatten_values(v))
        elif isinstance(data, list):
            for v in data:
                values.extend(TwoStepRecorder._flatten_values(v))
        elif isinstance(data, str) and data:
            values.append(data)
        return values

    def _generate_wrapper_script(
        self,
        raw_script_path: str,
        har_path: str,
        trace_path: str,
        storage_state: str,
        storage_exists: bool,
        har_url_filter: str,
        headless: bool,
    ) -> str:
        """拼一个临时 pytest 脚本出来，用来回放+录 HAR+Trace

        用 Template 而不是 f-string，因为里面有 JSON 花括号会报错。
        """
        # 统一用正斜杠，Windows 也不怕
        raw_script_path = raw_script_path.replace("\\", "/")
        har_path = har_path.replace("\\", "/")
        trace_path = trace_path.replace("\\", "/")
        storage_state = storage_state.replace("\\", "/")

        template = Template('''
import json
import sys
import os
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

# 守卫：登录恢复、弹窗处理
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath("__file__"))))
from recorder.guards import ensure_logged_in, dismiss_dialogs, wait_for_page_ready


def test_record_with_har():
    """回放录制脚本 + HAR + Trace"""
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                channel="chrome",
                headless=$headless_flag,
                args=[
                    "--ignore-certificate-errors",
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
        except Exception:
            # 没装 Chrome 就用默认 Chromium
            browser = p.chromium.launch(
                headless=$headless_flag,
                args=[
                    "--ignore-certificate-errors",
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
        context = browser.new_context(
            $storage_state_option
            record_har_path="$har_path",
            $har_url_filter_option
            record_har_content="embed",
            ignore_https_errors=True,
            viewport={"width": 1366, "height": 768},
            permissions=["local-network-access"],
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        )
        context.tracing.start(screenshots=True, snapshots=True)

        page = context.new_page()

        # headless 回放可能比较慢
        page.set_default_timeout(30000)
        page.set_default_navigation_timeout(60000)

        # 读取预处理好的脚本
        raw_path = Path("$raw_script_path")
        raw_source = raw_path.read_text(encoding="utf-8")

        # 准备 exec 环境
        exec_globals = {
            "page": page,
            "context": context,
            "browser": browser,
            "playwright": p,
            "__name__": "recording_wrapper",
            "pytest": __import__("pytest"),
            "re": __import__("re"),
            "json": __import__("json"),
            "time": __import__("time"),
            "ensure_logged_in": ensure_logged_in,
            "dismiss_dialogs": dismiss_dialogs,
            "wait_for_page_ready": wait_for_page_ready,
        }
        try:
            from playwright.sync_api import Page, expect as _expect
            exec_globals["Page"] = Page
            exec_globals["expect"] = _expect
        except ImportError:
            pass
        try:
            exec(raw_source, exec_globals)

            # 找到 codegen 生成的 test 函数并调用
            test_fn = None
            for name, obj in exec_globals.items():
                if callable(obj) and (name.startswith("test_") or name == "run"):
                    test_fn = obj
                    print(f"   📋 找到 test 函数: {name}")
                    break

            if test_fn:
                try:
                    import inspect
                    sig = inspect.signature(test_fn)
                    params = list(sig.parameters.keys())
                    print(f"   📋 test 函数参数: {params}")
                    if "page" in params:
                        test_fn(page=page)
                    elif params:
                        kwargs = {}
                        for pname in params:
                            if pname in exec_globals:
                                kwargs[pname] = exec_globals[pname]
                        test_fn(**kwargs)
                    else:
                        test_fn()
                    print(f"   📋 test 函数执行完毕")
                except TypeError as te:
                    print(f"   ⚠️ TypeError: {te}, 尝试无参调用")
                    test_fn()
            else:
                print(f"   ⚠️ 未找到 test 函数，raw_script 已通过 exec 执行")

        except Exception as e:
            import traceback
            print(f"⚠️ 回放执行错误: {e}")
            traceback.print_exc()

        finally:
            # 不管成功失败，Trace 和 HAR 都得保存
            try:
                context.tracing.stop(path="$trace_path")
            except Exception as trace_err:
                print(f"⚠️ Trace 保存失败: {trace_err}")

            # 回放结束后保存登录态（首次录制时浏览器已手动登录，cookies 已拿到）
            try:
                import os
                save_path = "$storage_state"
                save_dir = os.path.dirname(save_path)
                if save_dir:
                    os.makedirs(save_dir, exist_ok=True)
                context.storage_state(path=save_path)
                print(f"🔑 登录态已更新: {save_path}")
            except Exception as save_err:
                print(f"⚠️ 登录态保存失败: {save_err}")

            try:
                context.close()
            except Exception as close_err:
                print(f"⚠️ context.close() 失败: {close_err}")
            browser.close()

    print("✅ HAR + Trace 录制完成")
''')

        return template.substitute(
            headless_flag="True" if headless else "False",
            storage_state=storage_state,
            storage_state_option=f'storage_state="{storage_state}",' if storage_exists else "",
            har_path=har_path,
            har_url_filter=har_url_filter,
            har_url_filter_option=f'record_har_url_filter="{har_url_filter}",' if har_url_filter else "",
            raw_script_path=raw_script_path,
            trace_path=trace_path,
        )
