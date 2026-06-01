"""
commander.py — 仙人掌 Agent 主控制器
- 总工程师：调度工具 + 子代理 + 记忆
- 支持 continue/remember/recall 指令
- 自动摘要提醒
"""
import asyncio
import time
import logging
import uuid
import re
import os
import sys
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable
from types import SimpleNamespace

from .protocol import Protocol, ExecutionResult
from .session import DeepSeekSession, SessionConfig, MessageRole
from .subagent import BrowserSubAgent, SubAgentResult
from .memory_manager import MemoryManager

logger = logging.getLogger("commander")


class EventType(Enum):
    THINKING = "thinking"
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    TOOL_ERROR = "tool_error"
    COMMAND_DETECTED = "command_detected"
    COMMAND_EXECUTING = "command_executing"
    COMMAND_SUCCESS = "command_success"
    COMMAND_ERROR = "command_error"
    AI_FINAL_REPLY = "ai_final_reply"
    MEMORY_REMINDER = "memory_reminder"
    CONTINUE_READY = "continue_ready"
    CORRECTION_SENT = "correction_sent"
    ERROR = "error"


@dataclass
class AgentEvent:
    event_type: EventType
    data: any = None


# ============================================================
# 工具注册表
# ============================================================
class ToolRegistry:
    """工具注册表，支持子代理工具"""

    def __init__(self, commander):
        self._commander = commander
        self._tools: dict = {}
        self._browser_subagent: Optional[BrowserSubAgent] = None

    def set_browser_subagent(self, bm):
        """设置浏览器子代理（兼容旧接口，不再使用）"""
        self._browser_subagent = BrowserSubAgent(bm, depth=1)

    def register(self, name: str, description: str, fn: Callable):
        self._tools[name] = {"description": description, "fn": fn}

    def list_tools(self) -> list:
        return [
            {"name": name, "description": info["description"]}
            for name, info in self._tools.items()
        ]

    async def execute(self, tool_name: str, params: dict) -> "ExecutionResult":
        """异步执行工具（由 Commander 调用）"""
        import uuid
        if tool_name not in self._tools:
            return ExecutionResult(id=str(uuid.uuid4()), status="error",
                                  error=f"未知工具: {tool_name}", tool=tool_name)
        fn = self._tools[tool_name]["fn"]
        try:
            result = await fn(**params) if asyncio.iscoroutinefunction(fn) else fn(**params)
            return ExecutionResult(id=str(uuid.uuid4()), status="success", output=str(result), tool=tool_name)
        except Exception as e:
            return ExecutionResult(id=str(uuid.uuid4()), status="error", error=str(e), tool=tool_name)


# ============================================================
# 主控制器 Commander
# ============================================================

class Commander:
    """
    Agent 主控制器（总工程师模式）
    - 对话管理：维护 session + 事件回调
    - 工具执行：调用工具注册表
    - 子代理管理：维护 SubAgentManager（任务状态 + 凭据共享）
    - 记忆管理：自动摘要 + 长期记忆（remember/recall）
    - 错误纠正：commander fix
    """

    # === 放弃句式黑名单（检测到这些模式，强制继续任务）===
    GIVE_UP_PATTERNS = [
        r"由于.*无法",
        r"抱歉.*无法",
        r"抱歉.*不能",
        r"我无法完成",
        r"我不能完成",
        r"很抱歉.*无法",
        r"无法满足",
        r"超出.*能力",
        r"无法.*执行",
        r"任务.*已.*完成[^\u4e00-\u9fa5]*$",  # 虚报完成
        r"没有.*更多.*可以",
        r"已经.*足够",      # 提前收工
        r"请.*自行.*",      # 把活推给用户
        r"建议你.*手动",
    ]

    def __init__(
        self,
        browser_manager,
        session: Optional[DeepSeekSession] = None,
        work_dir: str = "",
        on_event: Optional[Callable[[AgentEvent], None]] = None,
    ):
        self._bm = browser_manager
        self._session = session
        self._work_dir = work_dir or os.getcwd()
        self._on_event = on_event
        self._tools = ToolRegistry(self)
        self._subagent_manager: Optional[SubAgentManager] = None
        self._memory: Optional[MemoryManager] = None
        self._history_turns: int = 0
        self._accumulated_prompt: str = ""
        self._correction_pending: Optional[str] = None
        self._running = False
        self._protocol = Protocol()
        # 记录当前任务描述（用于 done 验证）
        self._current_task: str = ""
        self._task_start_turn: int = 0
        # 统计放弃次数（超过阈值更强力纠正）
        self._give_up_count: int = 0
        # 记录上一个工具执行结果（用于 done 验证）
        self._last_tool_result: Optional[ExecutionResult] = None
        # 统计每个工具连续失败次数，连续失败3次以上建议写脚本
        self._tool_error_count: dict = {}
        # 任务清单状态
        self._checklist_require: bool = True   # 强制要求先建清单
        self._current_checklist: dict = {}      # {"task": "...", "items": [...]}

        # 先注册工具，再构建系统提示词（提示词依赖工具列表）
        self._register_tools()
        self._system_prompt = self._build_system_prompt()

    def _escape_json(s: str) -> str:
        """转义字符串用于 JSON 嵌入（处理换行、引号、反斜杠）"""
        if not s:
            return ""
        return s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")

    def _register_tools(self):
        """注册所有工具（包括子代理工具）"""
        import os, json as _json
        from pathlib import Path
        from datetime import datetime as _datetime

        # ══════════════════════════════════════════════════════
        # 任务清单工具（强制要求：每个任务开始前必须先建清单）
        # ══════════════════════════════════════════════════════
        async def task_checklist(**params):
            """mode=create(task,items)|mode=update(index,done)|mode=list: 创建/更新/查看任务清单，强制要求先建清单再干活"""
            mode = params.get("mode", "create")
            work_dir = Path(self._work_dir)
            checklist_file = work_dir / "_current_checklist.json"

            if mode == "list":
                if not checklist_file.exists():
                    return "[清单] 当前无进行中的任务清单。"
                data = _json.loads(checklist_file.read_text(encoding="utf-8"))
                remaining = [f"[ ] {item['desc']}" for item in data["items"] if not item.get("done")]
                done = [f"[x] {item['desc']}" for item in data["items"] if item.get("done")]
                lines = [f"任务: {data['task']}", f"进度: {len(done)}/{len(data['items'])} 项完成"]
                if remaining: lines.append("--- 未完成 ---") + remaining
                if done: lines.append("--- 已完成 ---") + done
                return "\n".join(lines)

            if mode == "create":
                task = params.get("task", self._current_task or "未命名任务")
                items = params.get("items", [])
                if isinstance(items, str):
                    items = [i.strip() for i in items.split(",") if i.strip()]
                if not items:
                    return "[错误] 缺少 items（清单项目列表）"
                data = {
                    "task": task,
                    "items": [{"desc": desc, "done": False} for desc in items],
                    "created_at": str(_datetime.now()),
                }
                checklist_file.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                self._current_checklist = data
                self._checklist_require = False  # 清单已创建，不再强制
                lines = [f"[清单已创建] 任务: {task}", f"共 {len(items)} 项："]
                for i, desc in enumerate(items):
                    lines.append(f"  [{i}] [ ] {desc}")
                return "\n".join(lines)

            if mode == "update":
                index = params.get("index", 0)
                done = params.get("done", True)
                if not checklist_file.exists():
                    return "[错误] 没有进行中的清单，请先 task_checklist(mode=create)"
                data = _json.loads(checklist_file.read_text(encoding="utf-8"))
                if index < 0 or index >= len(data["items"]):
                    return f"[错误] index {index} 超出范围（0-{len(data['items'])-1}）"
                old_desc = data["items"][index]["desc"]
                data["items"][index]["done"] = done
                checklist_file.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                self._current_checklist = data
                remaining = [i for i, it in enumerate(data["items"]) if not it.get("done")]
                done_count = len(data["items"]) - len(remaining)
                status = "[x] 完成" if done else "[ ] 恢复"
                return f"{status}: [{index}] {old_desc}\n进度: {done_count}/{len(data['items'])}"

            return "[错误] unknown mode, use: create / update / list"

        self._tools.register(
            "task_checklist",
            "mode=create(task,items)|mode=update(index,done)|mode=list: 强制先建清单再干活",
            task_checklist
        )

        async def wait_minutes(**params):
            """等待指定分钟数（Agent 自我等待，不消耗 AI 配额）。

            用途：
            - 等待任务完成（如等待子代理、文件处理等）
            - 轮询检查状态（如等待某个条件满足）
            - 避免频繁调用 AI

            参数：
            - minutes: float, 等待分钟数（支持小数，如 0.5 = 30 秒）
            - check_interval: float, 检查间隔秒数（默认 5 秒）

            返回：等待完成后返回 "[等待完成] 已等待 N 分钟"
            """
            minutes = float(params.get("minutes", 1))
            total_secs = minutes * 60
            await asyncio.sleep(total_secs)
            return f"[等待完成] 已等待 {minutes:.1f} 分钟（{int(total_secs)} 秒）"

        self._tools.register(
            "wait_minutes",
            "wait_minutes(minutes): 等待指定分钟数，不消耗 AI 配额，适合轮询等待",
            wait_minutes
        )

        # ══════════════════════════════════════════════════════
        # 自我诊断工具
        # ══════════════════════════════════════════════════════
        async def list_capabilities(**params):
            """列出 Agent 所有已安装的能力（工具）"""
            categories = {
                "文件操作": ["file_write", "file_read", "file_append", "file_exists", "file_list", "dir_create", "file_delete", "file_append"],
                "浏览器自动化": ["browser_search", "browser_visit", "browser_screenshot", "browser_fill", "browser_click"],
                "任务管理": ["task_checklist", "done", "ask", "wait_minutes", "list_tasks"],
                "联网获取": ["web_fetch", "browser_search"],
                "剪贴板": ["clipboard_read", "clipboard_write"],
                "等待工具": ["wait_minutes"],
                "记忆系统": ["remember", "recall", "list_summaries"],
                "自我修复": ["write_script", "shell_exec"],
                "子代理": ["browser_research", "browser_visit", "check_task", "wait_task", "list_tasks"],
                "文档生成": ["docx_create", "docx_append", "pptx_create", "pptx_append"],
                "深度思考": ["deep_think", "deep", "think"],
            }
            lines = ["=== 仙人掌 Agent 能力清单 ==="]
            for cat, tools in categories.items():
                lines.append(f"\n[{cat}]")
                for t in tools:
                    if t in self._tools._tools:
                        lines.append(f"  ✓ {t}")
                    else:
                        lines.append(f"  - {t} (未注册)")
            lines.append(f"\n总工具数: {len(self._tools._tools)}")
            return "\n".join(lines)

        async def get_status(**params):
            """获取当前运行状态：任务、清单进度、轮次、失败统计"""
            checklist_file = Path(self._work_dir) / "_current_checklist.json"
            checklist_info = "无"
            if checklist_file.exists():
                try:
                    data = _json.loads(checklist_file.read_text(encoding="utf-8"))
                    remaining = len([i for i in data["items"] if not i.get("done")])
                    total = len(data["items"])
                    checklist_info = f"任务: {data['task']} | 进度: {total-remaining}/{total} 项完成"
                except Exception:
                    checklist_info = "存在但读取失败"
            lines = [
                f"当前任务: {self._current_task[:60] if self._current_task else '无'}",
                f"清单状态: {checklist_info}",
                f"运行轮次: {self._history_turns}",
                f"累计失败工具: {dict(self._tool_error_count)}",
                f"工作目录: {self._work_dir}",
            ]
            return "\n".join(lines)

        self._tools.register("list_capabilities", "列出所有已安装的能力和工具，Agent 自我诊断用", list_capabilities)
        self._tools.register("get_status", "获取当前运行状态：任务、清单进度、轮次、失败统计", get_status)

        # ─── 文件操作工具 ───
        async def file_write(**params):
            p = Path(params.get("path", ""))
            content = params.get("content", "")
            full_path = Path(self._work_dir) / p if not p.is_absolute() else p
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
            return f"文件已写入: {full_path}"

        async def file_read(**params):
            p = Path(params.get("path", ""))
            full_path = Path(self._work_dir) / p if not p.is_absolute() else p
            if not full_path.exists():
                return f"错误: 文件不存在 {full_path}"
            return full_path.read_text(encoding="utf-8")

        async def file_list(**params):
            p = Path(params.get("path", "."))
            full_path = Path(self._work_dir) / p if not p.is_absolute() else p
            if not full_path.exists():
                return "目录不存在"
            items = list(full_path.iterdir())
            return "\n".join([f"{'[DIR]' if i.is_dir() else '[FILE]'} {i.name}" for i in items])

        async def dir_create(**params):
            """创建目录，支持中文路径别名和已知乱码模式自动修复

            自动识别：桌面/Desktop（GBK截断→esktop）、CP_Report→MCP_Report 等
            """
            import asyncio, subprocess, os as _os
            p = Path(params.get("path", ""))
            path_raw = str(p.expanduser()) if "~" in str(p) else str(p)

            # ── 检测已知 GBK 截断乱码模式 ──
            garbled_fixes = [
                # 完整小写 "esktop" → Desktop（大写D），前面没有大写字母才算乱码
                (r"(?<![A-Z])esktop$", "Desktop"),
                # 驱动器号截断（如 C:sers → C:\Users）
                (r"^(?=[A-Za-z]:sers\\)", lambda m: m.group(0).replace('sers', '\\Users')),
                # MCP_Report 被截断成 CP_Report，前面无大写字母才算乱码
                (r"(?<![A-Z])CP_Report", "MCP_Report"),
            ]
            for pattern, replacement in garbled_fixes:
                if re.search(pattern, path_raw):
                    path_raw = re.sub(pattern, replacement, path_raw)

            # ── 中文路径别名展开 ──
            for alias, ps_expr in [
                ("桌面", "[Environment]::GetFolderPath('Desktop')"),
                ("Desktop", "[Environment]::GetFolderPath('Desktop')"),
                ("下载", "[Environment]::GetFolderPath('Download')"),
                ("Downloads", "[Environment]::GetFolderPath('Download')"),
                ("文档", "[Environment]::GetFolderPath('MyDocuments')"),
                ("Documents", "[Environment]::GetFolderPath('MyDocuments')"),
            ]:
                if alias in path_raw:
                    try:
                        r = subprocess.run(["powershell","-NoProfile","-Command",ps_expr],
                            capture_output=True, encoding="utf-8", errors="replace", timeout=5)
                        if r.returncode == 0:
                            path_raw = path_raw.replace(alias, r.stdout.strip())
                    except Exception:
                        pass

            # ── 环境变量展开 ──
            for ev in ["USERPROFILE", "HOME", "APPDATA", "TEMP"]:
                if ev in _os.environ:
                    path_raw = path_raw.replace(f"%{ev}%", _os.environ[ev]).replace(f"${ev}", _os.environ[ev])

            # ── PowerShell 创建（Unicode 安全）──
            ps_path = path_raw.replace("'", "''")
            ps_cmd = (f"New-Item -ItemType Directory -Force -Path '{ps_path}' | Out-Null; "
                      f"Write-Host 'DIR_OK:' + (Resolve-Path '{ps_path}').Path")
            try:
                proc = await asyncio.create_subprocess_exec(
                    "powershell", "-NoProfile", "-Command", ps_cmd,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
                if proc.returncode == 0:
                    for line in stdout.decode('utf-8', errors='replace').splitlines():
                        if line.startswith("DIR_OK:"):
                            return f"目录已创建: {line.split('DIR_OK:',1)[1].strip()}"
                    return f"目录已创建: {path_raw}"
                else:
                    return f"[错误] {stderr.decode('utf-8', errors='replace').strip()}"
            except asyncio.TimeoutExpired:
                try: proc.kill()
                except Exception: pass
                return "[错误] dir_create 超时"
            except Exception as e:
                return f"[错误] {e}"

        async def file_delete(**params):
            p = Path(params.get("path", ""))
            full_path = Path(self._work_dir) / p if not p.is_absolute() else p
            if full_path.exists():
                if full_path.is_file():
                    full_path.unlink()
                else:
                    import shutil
                    shutil.rmtree(full_path)
                return f"已删除: {full_path}"
            return f"文件不存在: {full_path}"

        self._tools.register("file_write", "写入文件", file_write)
        self._tools.register("file_read", "读取文件", file_read)
        self._tools.register("file_list", "列出目录", file_list)
        self._tools.register("dir_create", "创建目录", dir_create)
        self._tools.register("file_delete", "删除文件/目录", file_delete)

        # ─── 追加/检查工具（补充缺失功能）───
        async def file_append(**params):
            p = Path(params.get("path", ""))
            content = params.get("content", "")
            full_path = Path(self._work_dir) / p if not p.is_absolute() else p
            full_path.parent.mkdir(parents=True, exist_ok=True)
            with open(full_path, "a", encoding="utf-8") as f:
                f.write(content)
            return f"内容已追加到: {full_path}"

        async def file_exists(**params):
            p = Path(params.get("path", ""))
            full_path = Path(self._work_dir) / p if not p.is_absolute() else p
            return f"{'存在' if full_path.exists() else '不存在'}: {full_path}"

        async def list_tasks(**params):
            """列出当前所有活跃子代理任务"""
            if not self._subagent_manager:
                return "子代理管理器未初始化"
            all_tasks = self._subagent_manager.check_all_tasks()
            if not all_tasks:
                return "当前无活跃任务"
            lines = []
            for task_info in all_tasks:
                tid = task_info.get("task_id", "?")
                status = task_info.get("status", "?")
                stype = task_info.get("task_type", "?")
                lines.append(f"[{status}] {tid} ({stype})")
            return "\n".join(lines) if lines else "当前无活跃任务"

        self._tools.register("file_append", "追加内容到文件", file_append)
        self._tools.register("file_exists", "检查文件是否存在", file_exists)
        self._tools.register("list_tasks", "列出所有子代理任务", list_tasks)

        # ─── Shell 执行工具 ───
        async def shell_exec(**params):
            import asyncio, re, subprocess, os as _os
            cmd = params.get("command", "")
            timeout = params.get("timeout", 60)

            # ── 检测是否需要 PowerShell（乱码模式/非ASCII/中文别名）──
            has_garbled = bool(re.search(r"(?<![A-Z])esktop$|(?<![A-Z])CP_Report|C:\\sers", cmd, re.IGNORECASE))
            has_non_ascii = bool(re.search(r"[^\x00-\x7F]", cmd))
            has_alias = any(a in cmd for a in ["桌面","Desktop","下载","Downloads","文档","Documents"])

            if has_garbled or has_non_ascii or has_alias:
                # 展开中文路径别名
                expanded = cmd
                for alias, ps_expr in [
                    ("桌面", "[Environment]::GetFolderPath('Desktop')"),
                    ("Desktop", "[Environment]::GetFolderPath('Desktop')"),
                    ("下载", "[Environment]::GetFolderPath('Download')"),
                    ("Downloads", "[Environment]::GetFolderPath('Download')"),
                ]:
                    if alias in expanded:
                        try:
                            r = subprocess.run(["powershell","-NoProfile","-Command",ps_expr],
                                capture_output=True, encoding="utf-8", errors="replace", timeout=5)
                            if r.returncode == 0:
                                expanded = expanded.replace(alias, r.stdout.strip())
                        except Exception:
                            pass
                pwsh_cmd = ["powershell", "-NoProfile", "-Command", expanded]
                try:
                    proc = await asyncio.create_subprocess_exec(*pwsh_cmd,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                    return (f"[退出码 {proc.returncode}]\n"
                            f"{stdout.decode('utf-8', errors='replace')}"
                            f"{stderr.decode('utf-8', errors='replace')}")
                except asyncio.TimeoutExpired:
                    try: proc.kill()
                    except Exception: pass
                    return f"命令超时（>{timeout}s）"
                except Exception as e:
                    return f"执行错误: {e}"
            else:
                try:
                    proc = await asyncio.create_subprocess_shell(cmd,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                    return (f"[退出码 {proc.returncode}]\n"
                            f"{stdout.decode('utf-8', errors='replace')}"
                            f"{stderr.decode('utf-8', errors='replace')}")
                except asyncio.TimeoutExpired:
                    try: proc.kill()
                    except Exception: pass
                    return f"命令超时（>{timeout}s）"
                except Exception as e:
                    return f"执行错误: {e}"

        self._tools.register("shell_exec", "执行Shell命令", shell_exec)

        # ─── 剪贴板工具 ───
        async def clipboard_read(**params):
            """读取系统剪贴板内容。"""
            try:
                import tkinter as tk
                r = tk.Tk()
                r.withdraw()
                content = r.clipboard_get()
                r.destroy()
                if not content:
                    return "[剪贴板] 内容为空"
                preview = content[:500]
                suffix = f"\n...[共 {len(content)} 字符]" if len(content) > 500 else ""
                return f"[剪贴板内容，共 {len(content)} 字符]\n{preview}{suffix}"
            except Exception as e:
                return f"[剪贴板读取错误] {str(e)}"

        async def clipboard_write(**params):
            """写入内容到系统剪贴板。"""
            content = params.get("content", "")
            if not content:
                return "[错误] 缺少 content 参数"
            try:
                import tkinter as tk
                r = tk.Tk()
                r.withdraw()
                r.clipboard_clear()
                r.clipboard_append(content)
                r.update()
                r.destroy()
                return f"[剪贴板] 已写入 {len(content)} 字符"
            except Exception as e:
                return f"[剪贴板写入错误] {str(e)}"

        self._tools.register("clipboard_read", "读取系统剪贴板内容", clipboard_read)
        self._tools.register("clipboard_write", "clipboard_write(content): 写入内容到系统剪贴板", clipboard_write)

        # ─── 自我修复工具：遇到错误时自动写脚本 ──
        async def write_script(**params):
            """遇到工具错误时，写 Python 脚本绕过并执行。
            
            当 browser_search 或其他工具连续失败时，用此工具写并执行 Python 脚本。
            Python 代码直接在系统 Python 环境执行，可调用 urllib、requests 等库。
            """
            import tempfile, subprocess, sys as _sys, os
            from pathlib import Path

            code = params.get("content", "")
            filename = params.get("filename", "")
            timeout = params.get("timeout", 60)
            work_dir = Path(self._work_dir)

            if not code:
                return "[错误] 缺少 Python 代码 content 参数"

            # 确定脚本路径
            if filename:
                script_path = work_dir / filename if not Path(filename).is_absolute() else Path(filename)
            else:
                script_path = work_dir / f"_fix_script_{int(__import__('time').time()*1000)}.py"

            script_path.parent.mkdir(parents=True, exist_ok=True)

            # 写入脚本（自动添加 UTF-8 编码声明）
            header = "# -*- coding: utf-8 -*-\nimport sys\n"
            if "sys.stdout" not in code and "reconfigure" not in code:
                header += "sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
            if "Path(" in code and "from pathlib" not in code:
                header += "from pathlib import Path\n"

            full_code = header + code
            script_path.write_text(full_code, encoding="utf-8")

            # 执行脚本
            try:
                result = subprocess.run(
                    [_sys.executable, str(script_path)],
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    cwd=str(work_dir),
                )
                output = result.stdout if result.stdout else ""
                err = result.stderr if result.stderr else ""
                msg = f"[脚本执行完毕] {script_path.name}\n[退出码 {result.returncode}]"
                if output:
                    msg += f"\n--- stdout ---\n{output[:2000]}"
                if err:
                    msg += f"\n--- stderr ---\n{err[:500]}"
                return msg
            except subprocess.TimeoutExpired:
                return f"[错误] 脚本执行超时（>{timeout}秒）"
            except Exception as e:
                return f"[错误] 脚本执行失败: {e}"

        self._tools.register(
            "write_script",
            "遇到工具错误时写Python脚本绕过：content=Python代码, filename=可选脚本名, timeout=超时(秒)",
            write_script
        )

        # ─── 浏览器操作工具（母代理直接执行）───

        async def browser_click(**params):
            return await self._bm.browser_click(params.get("selector", ""))

        async def browser_fill(**params):
            return await self._bm.browser_fill(params.get("selector", ""), params.get("text", ""))

        async def browser_screenshot(**params):
            path = params.get("path", "screenshot.png")
            full_path = Path(self._work_dir) / path
            return await self._bm.browser_screenshot(str(full_path))

        async def browser_search(**params):
            """网页搜索工具 - 不使用浏览器，直接用 HTTP 请求抓取页面
            
            通过 Bing 搜索获取结果，抓取页面内容后返回给 AI。
            不会占用母代理的浏览器状态。
            """
            import subprocess
            import json
            from pathlib import Path
            
            query = params.get("query", "")
            max_pages = params.get("max_pages", 3)
            output_file = params.get("output_file", "")
            
            if not query:
                return "[错误] 缺少 query 参数"
            
            # 确定输出文件路径
            if not output_file:
                output_file = str(Path(self._work_dir) / "search_results.json")
            
            # 调用网页搜索脚本
            script_path = Path(__file__).parent.parent / "web_searcher.py"
            
            try:
                import os
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                result = subprocess.run(
                    [sys.executable, str(script_path), query, str(max_pages), output_file],
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                    env=env,
                )
                
                if result.returncode == 0:
                    # 读取结果文件
                    if Path(output_file).exists():
                        with open(output_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        return f"[搜索完成] 抓取 {data.get('scraped_count', 0)} 个页面\n\n{data.get('findings', '')}"
                    else:
                        return result.stdout
                else:
                    return f"[搜索错误] {result.stderr}"
                    
            except subprocess.TimeoutExpired:
                return "[错误] 搜索超时（60秒）"
            except Exception as e:
                return f"[错误] {str(e)}"

        # ─── Web Fetch 工具（联网获取任意 URL 内容）───
        async def web_fetch(**params):
            """从指定 URL 获取可读内容，类似于 OpenClaw 的 web_fetch 工具。

            用途：
            - 抓取任意网页的文本内容（去除 HTML 标签）
            - 支持中文编码自动检测
            - 适合获取文档、API JSON、新闻文章等纯文本内容

            参数：
            - url: str, 目标 URL（必填）
            - max_chars: int, 最大返回字符数，默认 5000
            - timeout: int, 超时秒数，默认 30

            返回：抓取到的纯文本内容，或错误信息
            """
            import urllib.request
            import urllib.error
            import html as html_module
            import re as regex_module

            url = params.get("url", "").strip()
            max_chars = int(params.get("max_chars", 5000))
            timeout = int(params.get("timeout", 30))

            if not url:
                return "[错误] 缺少 url 参数"

            if not url.startswith(("http://", "https://")):
                return f"[错误] url 必须以 http:// 或 https:// 开头: {url}"

            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    }
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    content = resp.read()
                    encoding = resp.headers.get_content_charset() or "utf-8"
                    try:
                        text = content.decode(encoding, errors="replace")
                    except Exception:
                        text = content.decode("utf-8", errors="replace")

            except urllib.error.HTTPError as e:
                return f"[HTTP 错误] {e.code} {e.reason}"
            except urllib.error.URLError as e:
                return f"[URL 错误] {str(e.reason)}"
            except Exception as e:
                return f"[错误] {str(e)}"

            # HTML 标签清理
            text = regex_module.sub(r'<script[^>]*>.*?</script>', '', text, flags=regex_module.DOTALL | regex_module.IGNORECASE)
            text = regex_module.sub(r'<style[^>]*>.*?</style>', '', text, flags=regex_module.DOTALL | regex_module.IGNORECASE)
            text = regex_module.sub(r'<[^>]+>', ' ', text)
            # HTML 实体解码
            try:
                text = html_module.unescape(text)
            except Exception:
                pass
            # 清理多余空白
            text = regex_module.sub(r'[ \t]+', ' ', text)
            text = regex_module.sub(r'\n\s*\n', '\n\n', text).strip()

            if len(text) > max_chars:
                text = text[:max_chars] + f"\n\n[...内容已截断至 {max_chars} 字符，原文共 {len(text)} 字符]"

            return text

        self._tools.register("web_fetch", "web_fetch(url, max_chars=5000): 抓取任意 URL 的可读文本内容，去除 HTML 标签", web_fetch)

        # ─── 深度思考工具（母代理执行，AI 调用）───
        async def _deep_think_tool(**params):
            """深度思考工具 - 由 AI 调用，实际控制浏览器按钮
            
            当 AI 认为当前问题需要深度思考时，调用此工具开启 DeepSeek 的深度思考模式。
            系统会在 AI 输出完成后自动关闭此模式。
            """
            enable_str = params.get("enable", "true")
            enable = enable_str.lower() in ("true", "1", "yes", "on")
            await self._session.set_deep_think(enable)
            return f"深度思考模式已{'开启' if enable else '关闭'}"

        self._tools.register("browser_click", "点击元素", browser_click)
        self._tools.register("browser_fill", "填写输入框", browser_fill)
        self._tools.register("browser_screenshot", "截图", browser_screenshot)
        self._tools.register("browser_search", "搜索", browser_search)
        self._tools.register("deep_think", "深度思考：AI认为需要深度思考时调用此指令开启DeepSeek深度思考模式，完成后自动关闭", _deep_think_tool)

        # ─── 研究代理工具（独立子代理进程）───
        async def _browser_research(**params):
            """启动研究子代理（独立进程）"""
            from .subagent_manager import get_subagent_manager
            sam = get_subagent_manager(self._work_dir)
            
            query = params.get("query", "")
            max_pages = params.get("max_pages", 5)
            
            # 构建完整查询
            full_query = f"深度研究: {query} (最多访问 {max_pages} 个页面)"
            
            # 启动子代理进程（非阻塞）
            task_id = await sam.spawn_subagent(full_query, task_type="research")
            
            return f"[子代理已启动] task_id={task_id}\n查询: {query[:50]}...\n使用 check_task('{task_id}') 查看进度"

        async def _browser_visit(**params):
            """启动访问子代理（独立进程）"""
            from .subagent_manager import get_subagent_manager
            sam = get_subagent_manager(self._work_dir)
            
            url = params.get("url", "")
            
            # 构建完整查询
            full_query = f"访问并分析网页: {url}"
            
            # 启动子代理进程（非阻塞）
            task_id = await sam.spawn_subagent(full_query, task_type="visit")
            
            return f"[子代理已启动] task_id={task_id}\nURL: {url}\n使用 check_task('{task_id}') 查看进度"
        
        async def _check_task(**params):
            """检查子代理任务状态"""
            from .subagent_manager import get_subagent_manager
            sam = get_subagent_manager(self._work_dir)
            
            task_id = params.get("task_id", "")
            task = sam.check_task(task_id)
            
            if not task:
                return f"任务 {task_id} 不存在"
            
            status_info = f"任务: {task_id}\n状态: {task.status.value}\n类型: {task.task_type}\n查询: {task.query[:60]}"
            
            if task.result:
                status_info += f"\n结果: {'成功' if task.result.success else '失败'}"
                if task.result.output:
                    preview = task.result.output[:200] + "..." if len(task.result.output) > 200 else task.result.output
                    status_info += f"\n输出预览: {preview}"
                if task.result.files:
                    status_info += f"\n文件数: {len(task.result.files)}"
            
            return status_info
        
        async def _wait_task(**params):
            """等待子代理任务完成"""
            from .subagent_manager import get_subagent_manager
            sam = get_subagent_manager(self._work_dir)
            
            task_id = params.get("task_id", "")
            timeout = params.get("timeout", 300)
            
            task = await sam.wait_task(task_id, timeout=timeout)
            
            if not task:
                return f"等待任务 {task_id} 超时或任务不存在"
            
            if task.result and task.result.success:
                return f"任务 {task_id} 完成！\n输出: {task.result.output[:500]}"
            else:
                error = task.result.error if task.result else "未知错误"
                return f"任务 {task_id} 失败: {error}"

        self._tools.register("browser_research", "启动研究子代理（独立进程）", _browser_research)
        self._tools.register("browser_visit", "启动访问子代理（独立进程）", _browser_visit)
        self._tools.register("check_task", "检查子代理任务状态", _check_task)
        self._tools.register("wait_task", "等待子代理任务完成", _wait_task)

        # ─── Word 文档生成工具（母代理直接执行）───
        async def docx_tool_fn(**params):
            import os
            from pathlib import Path
            content_text = params.get("content", "")
            filename = params.get("filename", "report.docx")
            path = params.get("path", "")
            # 展开 %USERPROFILE% 等环境变量
            filename = os.path.expandvars(filename)
            if path:
                path = os.path.expandvars(path)
            # 如果指定了 path 参数，使用 path 作为目录
            if path:
                out_path = Path(path) / filename
            else:
                out_path = Path(self._work_dir) / filename
            out_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                from docx import Document
                doc = Document()
                doc.add_heading(filename.replace(".docx", ""), 0)
                for para in content_text.split("\n"):
                    if para.strip():
                        doc.add_paragraph(para)
                doc.save(str(out_path))
                return f"Word 文档已生成: {out_path}"
            except ImportError:
                # 降级为 txt
                txt_path = out_path.with_suffix(".txt")
                txt_path.write_text(content_text, encoding="utf-8")
                return f"python-docx 未安装，生成文本文件: {txt_path}"

        self._tools.register("docx_create", "生成 Word 文档（python-docx）", docx_tool_fn)

        # ─── PPT 生成工具 ───
        async def pptx_tool_fn(**params):
            content_text = params.get("content", "")
            filename = params.get("filename", "slides.pptx")
            out_path = Path(self._work_dir) / filename
            out_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                from pptx import Presentation
                prs = Presentation()
                lines = content_text.split("\n")
                slide = prs.slides.add_slide(prs.slide_layouts[1])
                slide.shapes.title.text = filename.replace(".pptx", "")
                body = slide.shapes.placeholders[1]
                tf = body.text_frame
                for line in lines[:10]:
                    p = tf.add_paragraph()
                    p.text = line
                prs.save(str(out_path))
                return f"PPT 已生成: {out_path}"
            except ImportError:
                return "python-pptx 未安装，无法生成 PPT"

        self._tools.register("pptx_create", "生成 PPT（python-pptx）", pptx_tool_fn)

        # ─── 记忆工具（母代理直接执行）───
        async def remember_tool(**params):
            if self._memory is None:
                return "错误：记忆管理器未初始化"
            content = params.get("content", "")
            tags = params.get("tags", [])
            mid = self._memory.save(content, tags=tags if isinstance(tags, list) else [tags])
            return f"[记忆已保存] ID={mid}"

        async def recall_tool(**params):
            if self._memory is None:
                return "错误：记忆管理器未初始化"
            query = params.get("query", "")
            results = self._memory.search(query)
            if not results:
                return "[回忆] 未找到相关记忆"
            lines = [f"- [{r.id}] {r.content[:60]}... (相关度: {r.score:.2f})" for r in results]
            return "[回忆结果]\n" + "\n".join(lines)

        async def summarize_tool(**params):
            if self._memory is None:
                return "错误：记忆管理器未初始化"
            period = params.get("period", "today")
            results = self._memory.summarize(period=period)
            return f"[摘要] 共 {len(results)} 条记忆"

        async def list_summaries_tool(**params):
            if self._memory is None:
                return "错误：记忆管理器未初始化"
            limit = params.get("limit", 10)
            return self._memory.list(limit=limit)

        self._tools.register("remember", "保存记忆", remember_tool)
        self._tools.register("recall", "回忆记忆", recall_tool)
        self._tools.register("summarize", "生成摘要", summarize_tool)
        self._tools.register("list_summaries", "列出记忆摘要", list_summaries_tool)

        # ─── 子代理结果查询工具 ───
        async def get_subagent_result_tool(**params):
            if self._subagent_manager is None:
                return "错误：子代理管理器未初始化"
            task_id = params.get("task_id", "")
            task = self._subagent_manager.check_task(task_id)
            if not task:
                return f"任务 {task_id} 不存在"
            if task.status.value != "done":
                return f"任务 {task_id} 状态: {task.status.value}"
            return f"[子代理结果] {task.result.output[:500]}"

        self._tools.register("get_subagent_result", "获取子代理结果", get_subagent_result_tool)

    # ============================================================
    # 系统提示词
    # ============================================================

    def pause(self):
        """暂停 Agent（terminal 调用），Agent 在当前回合结束后等待"""
        self._paused = True

    def resume(self):
        """恢复 Agent 执行（terminal 调用）"""
        if self._paused:
            self._paused = False

    def _build_system_prompt(self) -> str:
        """构建系统提示词（包含所有可用工具）"""
        tool_desc_list = []
        for name, info in self._tools._tools.items():
            tool_desc_list.append(f"- {name}: {info['description']}")
        tools_block = "\n".join(tool_desc_list)

        return f"""你是仙人掌 Agent（XianRenZhang Agent），一个自主 AI 助手，由 DeepSeek 驱动。

=== 核心指令 ===
当用户提出任务时，你必须根据需要使用工具来完成任务。工具调用格式：

@@@@
{{
    "tool": "工具名称",
    "params": {{...}},
    "id": "唯一标识"
}}
@@@@

RAW 命令格式（直接执行shell）：
<<<RAW>>>
命令内容
<<<RAW>>>

=== 可用工具 ===
{tools_block}

=== 关键规则 ===
1. **禁止直接在 DeepSeek 界面搜索** - 所有搜索必须使用 `browser_search` 工具
2. 一次只能执行一个工具调用
3. 工具执行后，系统会返回结果，你需要根据结果决定下一步
4. 如需多步骤，请分多次发送工具调用
5. 任务完成后，发送 done() 表示结束
6. 如需用户输入，使用 ask("问题")
7. **遇到工具错误 → 必须用 write_script 写 Python 脚本绕过，不准放弃**

=== 强制规则（绝对禁止违反）===
🚫 不准找借口：遇到错误继续尝试，不准说"由于...无法..."
🚫 不准放弃：任务没100%完成不准调用 done()，不准说"无法完成"
🚫 不准推卸：不能要求用户手动操作，必须AI自己完成
🚫 不准虚报：不能说任务完成了但实际上文件都没生成
🚫 不准退出：在用户目标真正达成之前，不准结束任务
🚫 工具连续失败3次 → 必须写脚本绕过，不准停
🚫 **任务开始前必须先建清单**：收到新任务后，第一步调用 task_checklist(mode=create)，把任务拆成 N 项，逐项完成
🚫 **清单没建完不准开始干活**：在 task_checklist 完成后才能调用其他工具

=== 子代理规则 ===
- browser_research: 启动独立研究子代理（后台运行，不阻塞母代理）
- browser_visit: 启动独立访问子代理
- 子代理启动后返回 task_id，使用 check_task(task_id) 查询进度
- 子代理不能再创建子代理（MAX_DEPTH=1）

=== 记忆系统 ===
- remember(content, tags): 保存重要信息到长期记忆
- recall(query): 搜索相关记忆
- 每运行约 20 轮会自动提醒保存记忆

=== 工作目录 ===
所有文件操作默认相对于: {self._work_dir}
"""

    # ============================================================
    # 公共 API
    # ============================================================

    async def start(self, session: Optional[DeepSeekSession] = None):
        """启动 Commander（复用外部 session）"""
        if session:
            self._session = session
        self._running = True
        # 设置系统提示词到 session，这样每轮对话都会包含
        if self._session:
            self._session.set_system_prompt(self._system_prompt)

    async def run(self, user_instruction: str, file_path: Optional[str] = None,
                  context_hints: str = "") -> str:
        """
        单轮执行（自动循环直到 AI 认为完成）
        返回最终回复内容
        """
        if self._session is None:
            raise RuntimeError("Session 未初始化")

        # 构建第一轮输入（包含系统提示词只在这一轮，后续已存入session）
        current_input = user_instruction
        if file_path:
            current_input += f"\n\n[参考文件: {file_path}]"
        if context_hints:
            current_input += f"\n\n[上下文提示: {context_hints}]"

        final_reply = ""
        max_turns, turn = 12, 0
        self._current_task = user_instruction
        self._task_start_turn = turn
        self._give_up_count = 0
        self._paused = False  # 暂停标志：由 terminal.py 通过 pause()/resume() 控制
        # 任务进度持久化：启动时自动恢复已有清单（新任务才强制建清单）
        checklist_file = Path(self._work_dir) / "_current_checklist.json"
        if checklist_file.exists():
            try:
                data = _json.loads(checklist_file.read_text(encoding="utf-8"))
                # 如果任务名相同或包含关系，认为是恢复任务，不需要重建清单
                saved_task = data.get("task", "")
                if saved_task and (saved_task in user_instruction or user_instruction in saved_task):
                    self._current_checklist = data
                    remaining = [i for i, it in enumerate(data["items"]) if not it.get("done")]
                    self._emit(EventType.CORRECTION_SENT, {
                        "type": "checklist_restored",
                        "task": saved_task,
                        "remaining": len(remaining),
                        "total": len(data["items"])
                    })
                    self._checklist_require = False  # 已恢复，不用强制重建
                else:
                    self._checklist_require = True  # 新任务，强制建清单
            except Exception:
                self._checklist_require = True
        else:
            self._checklist_require = True  # 无清单文件，强制建清单

        while turn < max_turns and self._running:
            # 暂停时等待用户继续
            if self._paused:
                pause_msg = (
                    "\n[PAUSED] Agent 已暂停。\n"
                    "  - 输入: 继续 / c / resume → 恢复执行\n"
                    "  - 输入: 状态 / s        → 查看当前进度\n"
                    "  - 输入: 清单 / l        → 查看任务清单\n"
                    "  - 输入: 放弃任务 / q    → 强制结束当前任务\n\n"
                    "请输入指令: "
                )
                self._emit(EventType.AI_FINAL_REPLY, {"reply": pause_msg})
                # 等待 terminal 调用 resume()
                while self._paused and self._running:
                    await asyncio.sleep(0.5)
                if not self._running:
                    return "[退出] Agent 已关闭"
            turn += 1
            self._history_turns += 1

            # 记忆提醒
            if self._memory and self._history_turns % 20 == 0:
                self._emit(EventType.MEMORY_REMINDER, {"turn": self._history_turns})

            # 发送给 AI
            try:
                response = await self._session.send(current_input)
            except Exception as e:
                logger.error(f"AI 调用失败: {e}")
                return f"[错误] AI 调用失败: {e}"

            # === 放弃句式检测 ===
            give_up_match = self._detect_give_up(response)
            if give_up_match:
                self._give_up_count += 1
                warn_level = "⚠️⚠️⚠️" if self._give_up_count >= 3 else "⚠️"
                correction = (
                    f"{warn_level} [强制继续] 检测到放弃句式: \"{give_up_match}\""
                    f"\n任务「{self._current_task[:40]}...」尚未完成！"
                    f"\n不准找借口，不准退出，不准说无法完成。"
                    f"\n必须继续执行，直到用户目标真正达成。"
                    f"\n{self._give_up_count}次放弃企图，" + ("这是最后一次警告！" if self._give_up_count >= 3 else "继续尝试。")
                )
                self._emit(EventType.CORRECTION_SENT, {"pattern": give_up_match, "count": self._give_up_count})
                current_input = (
                    f"[SYSTEM] {correction}\n\n"
                    f"原始任务：{self._current_task}\n\n"
                    f"请继续执行，必须使用 @@@@ JSON 格式的指令，不能放弃。"
                )
                continue

            # 解析指令
            cmds = self._protocol.extract_all(response)
            if not cmds:
                ai_text = response.strip()
                if ai_text:
                    # 纯文本检测，同时检查是否含放弃句式
                    give_up_in_text = self._detect_give_up(ai_text)
                    if give_up_in_text:
                        self._give_up_count += 1
                        current_input = (
                            f"[SYSTEM] ⚠️ 检测到放弃句式：{give_up_in_text}\n"
                            f"任务「{self._current_task[:40]}」未完成！"
                            f"必须继续，不准放弃。"
                            f"请用 @@@@ JSON 格式输出工具指令。"
                        )
                        continue
                    current_input = (
                        "[SYSTEM] NO @@@@ PROTOCOL. Your text was: " + ai_text[:200] + ". All responses MUST use @@@@ JSON format. Format: @@@@\\n{\"tool\":\"xxx\",\"params\":{},\"id\":\"1\"}\\n@@@@. Please retry."
                    )
                    continue
                else:
                    final_reply = response
                    break

            # 执行第一个指令
            cmd = cmds[0]

            # === 清单强制检查：清单没建好不准干活 ===
            if self._checklist_require and cmd.command.tool != "task_checklist":
                self._emit(EventType.CORRECTION_SENT, {"type": "checklist_required"})
                task_preview = self._current_task[:80] if self._current_task else ""
                # JSON 示例用单引号构造，避免 f-string 内 \" 转义问题
                _ex = ('{"tool":"task_checklist","params":{"mode":"create","task":"TASK_REPL",'
                      '"items":["第1步","第2步","第3步"]},"id":"1"}')
                _ex = _ex.replace("TASK_REPL", task_preview)
                current_input = (
                    f"[SYSTEM] \u26a0\ufe0f \u5fc5\u987b\u5148\u5efa\u4efb\u52a1\u6e05\u5355\uff01\n\n"
                    f"\u4efb\u52a1\uff1a{task_preview[:60]}\n\n"
                    f"\u7b2c\u4e00\u6b65\uff1a\u8c03\u7528 task_checklist\uff08mode=create\uff09\u521b\u5efa\u6e05\u5355\uff0c\u628a\u4efb\u52a1\u62c6\u6210\u81f3\u5c113\u987b\u4ee5\u4e0a\n\n"
                    f"\u793a\u4f8b\uff1a\n  @@@@\n{_ex}\n@@@@\n\n"
                    f"\u628a\u4efb\u52a1\u62c6\u6210\u81f3\u5c113\u987b\uff0c\u9010\u9879\u5b8c\u6210\u5e76\u6253\u52fe\uff0c\u6e05\u5355\u5efa\u597d\u4e4b\u524d\u4e0d\u51c6\u8c03\u7528\u5176\u4ed6\u5de5\u5177\uff01"
                )
                self._checklist_require = True
                continue

            # === 暂停检查：Agent 执行中途可被用户暂停 ===
            if self._paused:
                self._emit(EventType.AI_FINAL_REPLY, {
                    "reply": "\n[PAUSED] Agent 已暂停（工具执行中途）...\n请在终端输入: 继续 / c\n"
                })
                # 等待 resume() 被调用（terminal.py 会调用）
                while self._paused and self._running:
                    await asyncio.sleep(0.3)

            self._emit(EventType.COMMAND_DETECTED, {"tool": cmd.command.tool, "id": cmd.id})
            self._emit(EventType.TOOL_START, {"tool": cmd.command.tool})

            result = await self._execute_command(cmd.command)
            # 记录最后工具结果（供 done 验证用）
            self._last_tool_result = result

            # 工具连续失败3次以上 → 强制写脚本绕过
            tool_name = cmd.command.tool
            if result.status == "error":
                self._tool_error_count[tool_name] = self._tool_error_count.get(tool_name, 0) + 1
                if self._tool_error_count[tool_name] >= 3:
                    self._emit(EventType.CORRECTION_SENT, {"type": "tool_repeated_error", "tool": tool_name})
                    current_input = (
                        f"[SYSTEM] ⚠️ 工具 {tool_name} 已连续失败 3 次，错误: {str(result.error)[:80]}"
                        f"\n→ 必须使用 write_script 工具写 Python 脚本绕过此工具。"
                        f"\n→ 不准放弃，不准说无法完成。"
                    )
                    self._tool_error_count[tool_name] = 0
                    continue
            else:
                self._tool_error_count[tool_name] = 0  # 成功则重置

            self._emit(EventType.TOOL_END, {"tool": cmd.command.tool, "status": result.status})
            self._emit(EventType.COMMAND_SUCCESS if result.status == "success" else EventType.COMMAND_ERROR, result)

            # === done() 验证：任务没完成不准退出 ===
            if cmd.command.tool == "done":
                done_result = self._validate_task_done()
                if not done_result["allowed"]:
                    # 任务未完成，强制继续
                    self._emit(EventType.CORRECTION_SENT, {"reason": done_result["reason"]})
                    current_input = (
                        f"[SYSTEM] ⚠️ 不准结束！{done_result['reason']}\n"
                        f"原始任务：{self._current_task}\n"
                        f"必须继续执行，直到目标真正达成。"
                    )
                    continue
                else:
                    # 任务验证通过，允许结束
                    final_reply = result.output or "任务完成"
                    break

            # 构建下一轮输入（只包含工具结果，系统提示词已在session中）
            current_input = f"[系统] 工具 {result.tool} 执行结果:\n{result.output or result.error}\n\n请继续。"

        return final_reply if final_reply else "[完成]"

    async def run_with_loop(self, user_instruction: str, file_path: Optional[str] = None,
                            context_hints: str = "") -> str:
        """带自动循环的 run（和 run 相同，但名称更清晰）"""
        return await self.run(user_instruction, file_path, context_hints)

    async def continue_dialog(self) -> str:
        """
        继续对话（用户发送 '继续' 时调用）
        返回 AI 的回复内容
        """
        if self._correction_pending:
            correction = self._correction_pending
            self._correction_pending = None
            return await self.run(f"[系统纠正]\n{correction}")

        # 发送继续指令
        return await self.run("[系统] 用户要求继续，请接着上一步执行。")

    async def remember(self, content: str, tags: Optional[list] = None):
        """显式保存记忆"""
        if self._memory:
            mid = self._memory.save(content, tags=tags or [])
            return mid
        return None

    async def recall(self, query: str) -> list:
        """显式回忆记忆"""
        if self._memory:
            return self._memory.search(query)
        return []

    def set_memory_manager(self, mm: MemoryManager):
        """设置记忆管理器（外部注入）"""
        self._memory = mm

    def set_subagent_manager(self, sm):
        """设置子代理管理器（外部注入）"""
        self._subagent_manager = sm

    def stop(self):
        """停止运行循环"""
        self._running = False

    def inject_correction(self, correction_text: str):
        """注入系统纠正（AI 幻觉时人工干预）"""
        self._correction_pending = correction_text

    # ============================================================
    # 内部方法
    # ============================================================

    async def _execute_command(self, cmd: SimpleNamespace) -> ExecutionResult:
        """执行单个命令"""
        tool_name = getattr(cmd, "tool", None) or getattr(cmd, "action", None)
        params = getattr(cmd, "params", {}) or {}
        cmd_id = getattr(cmd, "id", str(uuid.uuid4()))

        if not tool_name:
            return ExecutionResult(id=cmd_id, status="error", error="指令缺少 tool 字段")

        # 特殊指令处理
        if tool_name == "done":
            # done 由主循环验证，不在这里直接返回
            return ExecutionResult(id=cmd_id, status="success", output="用户确认结束", tool="done")

        if tool_name == "ask":
            question = params.get("question", "请输入：")
            return ExecutionResult(id=cmd_id, status="success", output=f"ASK:{question}", tool="ask")

        # RAW 命令处理
        if tool_name == "raw_shell":
            return await self._tools.execute("shell_exec", {"command": params.get("command", "")})

        # 标准工具调用
        return await self._tools.execute(tool_name, params)

    def _detect_give_up(self, text: str) -> str:
        """检测文本中是否含放弃句式，返回匹配内容，无匹配返回空字符串"""
        if not text:
            return ""
        for pattern in self.GIVE_UP_PATTERNS:
            m = re.search(pattern, text)
            if m:
                return m.group(0)
        return ""

    def _validate_task_done(self) -> dict:
        """
        验证任务是否真的完成了。只有在以下情况才允许 done：
        1. 文件已生成（检查最后工具输出中是否含路径）
        2. 工具执行全部成功
        3. 有明确的完成标志
        """
        result = self._last_tool_result
        if result is None:
            return {"allowed": False, "reason": "没有任何工具执行记录"}

        # === 清单完成度检查 ===
        checklist_file = Path(self._work_dir) / "_current_checklist.json"
        if checklist_file.exists():
            try:
                data = _json.loads(checklist_file.read_text(encoding="utf-8"))
                remaining = [item["desc"] for item in data["items"] if not item.get("done")]
                if remaining:
                    reasons.append(f"清单还有 {len(remaining)} 项未完成: {remaining[0]}")
            except Exception:
                pass

        task_keywords = self._current_task.lower()
        output = (result.output or "").lower()
        error = (result.error or "").lower()

        reasons = []

        # 检查是否有生成文件
        file_generated = any(
            kw in output for kw in [".docx", ".txt", ".pdf", ".pptx", ".md", ".json", ".csv", ".xlsx"]
        )
        if not file_generated and ("已生成" not in output and "已创建" not in output and "已保存" not in output):
            reasons.append("未检测到文件生成（文档/报告等）")

        # 检查是否有明确失败
        if result.status == "error" or error:
            reasons.append(f"工具执行失败: {result.error[:50]}")

        # 检查关键词是否在输出中
        key_expectations = []
        if "搜索" in task_keywords or "研究" in task_keywords:
            key_expectations.append("搜索" if "搜索" in task_keywords else "研究")
        if "文档" in task_keywords or "报告" in task_keywords:
            key_expectations.append("文档" if "文档" in task_keywords else "报告")
        if "创建" in task_keywords or "生成" in task_keywords:
            key_expectations.append("创建" if "创建" in task_keywords else "生成")

        for kw in key_expectations:
            if kw not in output:
                reasons.append(f"未完成：缺少「{kw}」相关内容")

        if reasons:
            return {
                "allowed": False,
                "reason": " | ".join(reasons)
            }
        return {"allowed": True, "reason": ""}

    def _emit(self, event_type: EventType, data=None):
        """触发事件回调"""
        if self._on_event:
            try:
                self._on_event(AgentEvent(event_type=event_type, data=data))
            except Exception as e:
                logger.warning(f"事件回调错误: {e}")

    # ============================================================
    # 错误纠正（commander fix）
    # ============================================================

    async def fix(self, error_hint: str):
        """
        当检测到 AI 幻觉/错误时，注入系统级纠正
        使用方式：在 terminal.py 检测到异常后调用 commander.fix("纠正内容")
        """
        self.inject_correction(error_hint)
        return await self.continue_dialog()


# ============================================================
# 快捷函数（兼容旧代码）
# ============================================================

async def run_agent(browser_manager, session: DeepSeekSession, instruction: str, work_dir: str = "") -> str:
    """快捷函数：创建 Commander 并执行"""
    commander = Commander(
        browser_manager=browser_manager,
        session=session,
        work_dir=work_dir or os.getcwd(),
    )
    await commander.start(session=session)
    return await commander.run(instruction)
