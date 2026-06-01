"""
subagent_manager.py - 子代理管理器（真实子代理架构）
- 母代理 = 浏览器主实例，完整功能，可派生子代理
- 子代理 = 母代理同一浏览器，执行特定任务，不能派生新子代理
- 凭据管理：~/.xianrenzhang_agent/credentials/（主凭据，永不移动）
- 子代理从主凭据复制一份到临时目录使用，避免锁冲突
- 任务完成自动通知母代理（写入通知队列）
"""
import asyncio
import json
import time
import sys
import os
import shutil
import uuid
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum

# 全局单例
_global_manager: Optional["SubAgentManager"] = None

def get_subagent_manager(work_dir: str = None) -> "SubAgentManager":
    global _global_manager
    if _global_manager is None:
        _global_manager = SubAgentManager(work_dir)
    return _global_manager


# ─────────────────────────────────────────────────────────
# 凭据管理路径（固定在 ~/.xianrenzhang_agent/credentials/）
# ─────────────────────────────────────────────────────────
CREDENTIALS_DIR = Path.home() / ".xianrenzhang_agent" / "credentials"
CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
COOKIE_FILE = CREDENTIALS_DIR / "deepseek_cookies.json"
SESSION_FILE = CREDENTIALS_DIR / "session_info.json"


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"

    @property
    def label(self) -> str:
        return self.value


@dataclass
class SubAgentResult:
    success: bool
    findings: str = ""
    output: str = ""
    files: List[Dict] = field(default_factory=list)
    scraped_count: int = 0
    error: Optional[str] = None


@dataclass
class SubAgentTask:
    task_id: str
    task_type: str = "browse"           # "browse" | "research" | "custom"
    query: str = ""
    status: TaskStatus = TaskStatus.PENDING
    result_path: str = ""
    result: Optional[SubAgentResult] = None
    started_at: float = 0.0
    finished_at: float = 0.0
    # 子代理用临时凭据目录（每次不同，避免锁冲突）
    temp_cred_dir: str = ""
    error: Optional[str] = None


@dataclass
class CompletionNotification:
    """子代理任务完成通知"""
    task_id: str
    task_type: str
    query: str
    success: bool
    result_path: str
    findings_preview: str  # 前200字摘要
    scraped_count: int
    error: Optional[str] = None
    finished_at: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.finished_at))
        return d


class SubAgentManager:
    """
    子代理管理器 - 真实子代理架构
    - 母代理用同一浏览器实例执行子代理任务
    - 主凭据目录永不移动，子代理每次复制到临时目录使用
    - 任务完成写入通知队列，母代理主动提示用户
    """

    def __init__(self, work_dir: str = None):
        self.work_dir = Path(work_dir) if work_dir else (Path.home() / ".xianrenzhang_agent" / "tasks")
        self.work_dir.mkdir(parents=True, exist_ok=True)

        # 任务表
        self._tasks: Dict[str, SubAgentTask] = {}
        self._notification_queue: List[CompletionNotification] = []
        # 完成通知回调（母代理可注册）
        self._notify_callback: Optional[Callable[[CompletionNotification], None]] = None
        self._closed = False

    # ─────────────────────────────────────────────────────────
    # 凭据管理 API（给母代理/子代理共用）
    # ─────────────────────────────────────────────────────────

    @staticmethod
    def get_credentials_dir() -> Path:
        """返回主凭据目录（永不移动）"""
        return CREDENTIALS_DIR

    @staticmethod
    def get_cookie_file() -> Path:
        return COOKIE_FILE

    @staticmethod
    def is_logged_in() -> bool:
        """检测是否已登录（cookie存在且未过期）"""
        if not COOKIE_FILE.exists():
            return False
        try:
            cookies = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
            if not cookies:
                return False
            # 检查是否有重要cookie（ds_uid等）
            important = [c for c in cookies if any(k in c.get("name", "") for k in ["session", "token", "uid", "sid"])]
            if not important and len(cookies) < 3:
                return False
            return True
        except Exception:
            return False

    @staticmethod
    def create_temp_cred_dir(prefix: str = "subagent") -> Path:
        """
        为子代理创建临时凭据目录。
        从主凭据复制cookie到临时目录，子代理使用临时目录。
        原始凭据目录永远不动，避免被锁。
        """
        import tempfile
        temp_dir = Path(tempfile.mkdtemp(prefix=f"{prefix}_cred_"))
        cred_file = temp_dir / "deepseek_cookies.json"
        if COOKIE_FILE.exists():
            shutil.copy2(COOKIE_FILE, cred_file)
        return temp_dir

    @staticmethod
    def copy_credentials_to(target_dir: Path) -> bool:
        """复制主凭据到目标目录（供子代理使用）"""
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            if COOKIE_FILE.exists():
                shutil.copy2(COOKIE_FILE, target_dir / "deepseek_cookies.json")
            session = {}
            if SESSION_FILE.exists():
                shutil.copy2(SESSION_FILE, target_dir / "session_info.json")
            return True
        except Exception as e:
            print(f"[CredentialManager] 复制凭据失败: {e}")
            return False

    @staticmethod
    def save_session_info(info: dict):
        """保存当前会话信息（对话ID等）"""
        try:
            SESSION_FILE.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────
    # 任务派发（由母代理调用，子代理执行）
    # ─────────────────────────────────────────────────────────

    async def dispatch_browse(self, url: str, task_id: str = None) -> str:
        """
        派发URL浏览任务。母代理立即返回 task_id，
        子代理（母代理自身）执行任务，完成后写入结果并触发通知。
        """
        if task_id is None:
            task_id = f"browse_{int(time.time()*1000)}"
        result_path = str(self.work_dir / f"result_{task_id}.json")
        task = SubAgentTask(
            task_id=task_id,
            task_type="browse",
            query=url,
            status=TaskStatus.RUNNING,
            result_path=result_path,
            started_at=time.time(),
        )
        self._tasks[task_id] = task
        return task_id

    async def dispatch_research(self, query: str, max_pages: int = 5, task_id: str = None) -> str:
        """
        派发深度研究任务。立即返回 task_id。
        任务在后台执行（当前实现：派发给脚本；未来改为母代理浏览器执行）。
        """
        if task_id is None:
            task_id = f"research_{int(time.time()*1000)}"
        result_path = str(self.work_dir / f"result_{task_id}.json")
        script_path = str(self.work_dir / f"agent_{task_id}.py")

        task = SubAgentTask(
            task_id=task_id,
            task_type="research",
            query=query,
            status=TaskStatus.RUNNING,
            result_path=result_path,
            script_path=script_path,
            started_at=time.time(),
        )
        self._tasks[task_id] = task

        # 派发给脚本执行（临时方案，最终改为母代理浏览器执行）
        self._write_research_script(query, max_pages, result_path, task_id, script_path)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # 监控脚本执行结果
        asyncio.create_task(self._monitor_script(task_id, proc, result_path))

        print(f"[SubAgent] 已派发 {task_id}，查询: {query[:50]}")
        return task_id

    async def dispatch_custom(self, task_name: str, params: dict, task_id: str = None) -> str:
        """派发自定义任务（未来：基于skill执行）"""
        if task_id is None:
            task_id = f"custom_{int(time.time()*1000)}"
        result_path = str(self.work_dir / f"result_{task_id}.json")
        task = SubAgentTask(
            task_id=task_id,
            task_type="custom",
            query=task_name,
            status=TaskStatus.RUNNING,
            result_path=result_path,
            started_at=time.time(),
        )
        self._tasks[task_id] = task
        # 未来：调用对应skill执行
        return task_id

    # ─────────────────────────────────────────────────────────
    # 任务状态查询（非阻塞）
    # ─────────────────────────────────────────────────────────

    def check_task(self, task_id: str) -> Optional[SubAgentTask]:
        """检查单个任务状态"""
        if task_id not in self._tasks:
            return None
        task = self._tasks[task_id]
        if task.status == TaskStatus.RUNNING:
            self._refresh_task_status(task)
        return task

    def check_all_tasks(self) -> List[SubAgentTask]:
        """刷新所有任务状态"""
        for task in list(self._tasks.values()):
            self._refresh_task_status(task)
        return list(self._tasks.values())

    def get_done_tasks(self) -> List[SubAgentTask]:
        self.check_all_tasks()
        return [t for t in self._tasks.values() if t.status == TaskStatus.DONE]


    async def _monitor_script(self, task_id: str, proc: asyncio.subprocess.Process, result_path: str):
        """监控脚本执行结果"""
        try:
            await proc.wait()
            # 脚本完成后检查结果
            task = self._tasks.get(task_id)
            if task and task.status == TaskStatus.RUNNING:
                if Path(result_path).exists():
                    task.result = self._read_result(result_path)
                    task.status = TaskStatus.DONE if task.result.success else TaskStatus.FAILED
                    task.finished_at = time.time()
                    self._push_notification(task)
                else:
                    task.status = TaskStatus.FAILED
                    task.error = "脚本执行后未生成结果文件"
        except Exception as e:
            task = self._tasks.get(task_id)
            if task:
                task.status = TaskStatus.FAILED
                task.error = str(e)

    def _refresh_task_status(self, task: SubAgentTask):
        """刷新单个任务状态（检测是否完成）"""
        if task.status != TaskStatus.RUNNING:
            return

        # 检查结果文件
        if task.result_path:
            rp = Path(task.result_path)
            if rp.exists():
                task.status = TaskStatus.DONE
                task.finished_at = time.time()
                task.result = self._read_result(task.result_path)
                self._push_notification(task)
                return

        # 检查进程（如果有）
        # ...进程检查逻辑...

    def _read_result(self, result_path: str) -> SubAgentResult:
        p = Path(result_path)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return SubAgentResult(
                    success=data.get("success", True),
                    findings=data.get("findings", ""),
                    output=data.get("output", ""),
                    scraped_count=data.get("scraped_count", 0),
                    files=data.get("files", []),
                )
            except Exception as e:
                return SubAgentResult(success=False, error=str(e))
        return SubAgentResult(success=False, error="结果文件不存在")

    # ─────────────────────────────────────────────────────────
    # 完成通知队列
    # ─────────────────────────────────────────────────────────

    def _push_notification(self, task: SubAgentTask):
        """任务完成，写入通知队列，并触发回调"""
        preview = ""
        if task.result and task.result.findings:
            preview = task.result.findings[:200]

        notif = CompletionNotification(
            task_id=task.task_id,
            task_type=task.task_type,
            query=task.query,
            success=task.result.success if task.result else True,
            result_path=task.result_path,
            findings_preview=preview,
            scraped_count=task.result.scraped_count if task.result else 0,
            error=task.result.error if task.result else None,
            finished_at=task.finished_at,
        )
        self._notification_queue.append(notif)
        print(f"\n[通知] 任务 {task.task_id} 已完成！结果: {task.result_path}\n")

        if self._notify_callback:
            try:
                self._notify_callback(notif)
            except Exception as e:
                print(f"[SubAgent] 通知回调失败: {e}")

    def get_and_clear_notifications(self) -> List[CompletionNotification]:
        """获取并清空通知队列（给母代理显示给用户）"""
        notifs = self._notification_queue.copy()
        self._notification_queue.clear()
        return notifs

    def set_notify_callback(self, callback: Callable[[CompletionNotification], None]):
        """注册通知回调（母代理调用，收到通知时执行）"""
        self._notify_callback = callback

    # ─────────────────────────────────────────────────────────
    # 等待任务
    # ─────────────────────────────────────────────────────────

    async def spawn_subagent(self, query: str, task_type: str = "research") -> str:
        """
        启动真正的独立子代理进程
        - 返回 task_id 立即给母代理（非阻塞）
        - 子代理在独立进程中运行
        - 母代理可以继续执行其他任务
        """
        import subprocess
        
        task_id = f"subagent_{int(time.time()*1000)}"
        task_dir = self.work_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        
        result_path = str(task_dir / "result.json")
        status_path = str(task_dir / "status.txt")
        
        task = SubAgentTask(
            task_id=task_id,
            task_type=task_type,
            query=query,
            status=TaskStatus.RUNNING,
            result_path=result_path,
            started_at=time.time(),
        )
        self._tasks[task_id] = task
        
        # 启动独立子代理进程
        project_root = Path(__file__).parent.parent
        subagent_script = project_root / "subagent_main.py"
        
        cmd = [
            sys.executable,
            str(subagent_script),
            "--task-dir", str(task_dir),
            "--query", query,
            "--type", task_type,
            "--parent-pid", str(os.getpid()),
        ]
        
        print(f"[SubAgent] 启动子代理: {task_id}")
        print(f"[SubAgent] 工作目录: {task_dir}")
        print(f"[SubAgent] 查询: {query[:60]}...")
        
        # 使用 Popen 非阻塞启动
        # 日志文件（子代理输出重定向到文件，不开独立窗口）
        log_file = self.work_dir / f"subagent_{task_id}.log"
        log_handle = open(log_file, "w", encoding="utf-8")
        
        process = subprocess.Popen(
            cmd,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=0,
        )
        
        # 后台监控进程，传递 log_handle 引用
        asyncio.create_task(self._monitor_subagent(task_id, process, task_dir, log_file, log_handle))
        
        return task_id
    
    async def _monitor_subagent(self, task_id: str, process: subprocess.Popen, task_dir: Path, log_file=None, log_handle=None):
        """后台监控子代理进程"""
        task = self._tasks.get(task_id)
        if not task:
            return
        
        status_file = task_dir / "status.txt"
        result_file = task_dir / "result.json"
        
        # 轮询等待子代理完成
        while process.poll() is None:
            # 检查状态文件更新
            if status_file.exists():
                try:
                    status_data = json.loads(status_file.read_text(encoding="utf-8"))
                    if status_data.get("status") == "STARTED":
                        print(f"[SubAgent] {task_id} 已启动，工作目录: {status_data.get('task_dir')}")
                except Exception:
                    pass
            await asyncio.sleep(1)
        
        # 进程结束，读取结果
        return_code = process.returncode
        task.finished_at = time.time()
        
        if result_file.exists():
            try:
                result_data = json.loads(result_file.read_text(encoding="utf-8"))
                task.result = SubAgentResult(
                    success=result_data.get("success", False),
                    findings=result_data.get("output", ""),
                    output=result_data.get("output", ""),
                    files=result_data.get("files", []),
                    error=result_data.get("error"),
                )
                task.status = TaskStatus.DONE if result_data.get("success") else TaskStatus.FAILED
                print(f"[SubAgent] {task_id} 完成")
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.result = SubAgentResult(success=False, error=f"读取结果失败: {e}")
                print(f"[SubAgent] {task_id} 读取结果失败: {e}")
        else:
            task.status = TaskStatus.FAILED
            stderr = process.stderr.read().decode("utf-8", errors="ignore") if process.stderr else ""
            task.result = SubAgentResult(success=False, error=f"子代理异常退出，返回码: {return_code}\n{stderr}")
            print(f"[SubAgent] {task_id} 异常退出，返回码: {return_code}")
        
        # 关闭日志文件
        if log_handle:
            try:
                log_handle.close()
                print(f"[SubAgent] {task_id} 日志已关闭: {log_file}")
            except Exception:
                pass
        # 推送通知
        self._push_notification(task)
    
    async def wait_task(self, task_id: str, timeout: float = 300.0) -> Optional[SubAgentTask]:
        """等待指定任务完成"""
        start = time.time()
        while time.time() - start < timeout:
            task = self.check_task(task_id)
            if task and task.status in (TaskStatus.DONE, TaskStatus.FAILED):
                return task
            await asyncio.sleep(2)
        return self.check_task(task_id)

    # ─────────────────────────────────────────────────────────
    # 任务摘要
    # ─────────────────────────────────────────────────────────

    def get_all_summary(self) -> str:
        """生成所有任务状态摘要"""
        self.check_all_tasks()
        lines = ["=== 子代理任务状态 ==="]
        for t in self._tasks.values():
            icon = {"pending": "⏳", "running": "🔄", "done": "✅", "failed": "❌"}[t.status.value]
            lines.append(f"{icon} [{t.task_id}] {t.task_type}: {t.query[:40]}")
        return "\n".join(lines) if lines else "暂无任务"

    def get_task_summary(self, task_id: str) -> str:
        task = self.check_task(task_id)
        if not task:
            return f"任务 {task_id} 不存在"
        icon = {"pending": "⏳", "running": "🔄", "done": "✅", "failed": "❌"}[task.status.value]
        info = f"{icon} {task.task_type} | {task.status.label}\n"
        info += f"查询: {task.query[:60]}\n"
        if task.status == TaskStatus.DONE and task.result:
            info += f"完成: 爬取 {task.result.scraped_count} 页，{len(task.result.findings)} 字"
        return info

    # ─────────────────────────────────────────────────────────
    # 脚本生成（临时方案，最终删除）
    # ─────────────────────────────────────────────────────────

    def _write_research_script(self, query: str, max_pages: int, result_path: str, task_id: str, script_path: str):
        """生成研究脚本（临时方案：urllib爬取）"""
        # 从凭据文件读取cookie（供脚本使用）
        cookie_data = "{}"
        if COOKIE_FILE.exists():
            cookie_data = json.dumps(json.loads(COOKIE_FILE.read_text(encoding="utf-8")))

        script = f'''# -*- coding: utf-8 -*-
import sys, json, time, urllib.request, urllib.parse

QUERY = {json.dumps(query)}
MAX_PAGES = {max_pages}
RESULT_PATH = {json.dumps(result_path)}
TASK_ID = {json.dumps(task_id)}
COOKIES = {cookie_data}

def main():
    # Bing搜索
    encoded = urllib.parse.quote(QUERY)
    url = f"https://www.bing.com/search?q={{encoded}}&first=0&FORM=PERE"
    headers = {{
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }}
    for name, val in COOKIES.items():
        if isinstance(val, dict) and "value" in val:
            headers["Cookie"] = f"{{name}}={{val['value']}}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        findings = f"[Bing搜索结果] {{QUERY}}\\n长度: {{len(html)}}字符"
        result = {{
            "success": True,
            "findings": findings,
            "scraped_count": 1,
            "output": "完成",
        }}
    except Exception as e:
        result = {{"success": False, "error": str(e), "findings": "", "scraped_count": 0, "output": ""}}

    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[{{TASK_ID}}] 完成，结果: {{RESULT_PATH}}")

if __name__ == "__main__":
    main()
'''
        Path(script_path).write_text(script, encoding="utf-8")
