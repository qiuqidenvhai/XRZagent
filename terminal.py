import signal
import sys

# ════════════════════════════════════════════════════════════
# Ctrl+C 优雅关闭
# ════════════════════════════════════════════════════════════
_SHUTDOWN_REQUESTED = False

def _sigint_handler(signum, frame):
    global _SHUTDOWN_REQUESTED
    if not _SHUTDOWN_REQUESTED:
        _SHUTDOWN_REQUESTED = True
        print("\n\n[Ctrl+C] 正在关闭，请稍候...（Agent 将在当前命令完成后退出）", end="", flush=True)

# Windows 控制台 UTF-8 支持（解决 emoji 等 Unicode 字符显示问题）
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

"""
terminal.py — 仙人掌 Agent 终端
"""
import asyncio
from pathlib import Path
from types import SimpleNamespace
import shutil
import time

def c(text, *styles):
    RESET = "\033[0m"
    return "".join(styles) + text + RESET

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
GRAY = "\033[90m"
BOLD = "\033[1m"

from agent_core.browser import BrowserManager, COOKIE_DIR, COOKIE_FILE
from agent_core.session import DeepSeekSession
from agent_core.commander import Commander, EventType
from agent_core.protocol import ExecutionResult
from agent_core.memory_manager import MemoryManager
from agent_core.subagent_manager import get_subagent_manager


class PauseManager:
    def __init__(self):
        self._paused = asyncio.Event()
        self._paused.set()

    def pause(self):
        self._paused.clear()

    def resume(self):
        self._paused.set()

    def is_paused(self):
        return not self._paused.is_set()

    async def wait_if_paused(self):
        """等待直到未暂停（支持 Ctrl+C 中断）"""
        while not self._paused.is_set():
            try:
                await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                # Ctrl+C received during pause wait
                raise


class Terminal:
    BANNER = (
        "\033[96m"
        "==================================================\n"
        "  仙人掌 Agent — 终端\n"
        "  DeepSeek 驱动 | 工具执行 | 子代理支持\n"
        "==================================================\033[0m\n"
    )

    def __init__(self):
        self.commander: Commander = None
        self.session: DeepSeekSession = None
        self.browser: BrowserManager = None
        self.running = True
        self.pause = PauseManager()
        self.current_task_name = "任务 1"
        self.current_task_dir: Path = None
        # ask 命令队列
        self._ask_event: asyncio.Event = asyncio.Event()
        self._ask_pending_q: list = []
        self._ask_future: asyncio.Future = None
        # 轮次计数器
        self._turn_count = 0
        self._memory_reminder_issued = False
        self._force_stop = False
        # 子代理管理器单例
        from agent_core.subagent_manager import get_subagent_manager, CompletionNotification
        self._sam = None  # 延迟初始化
        self._notify_callback_registered = False

    async def run(self):
        print(Terminal.BANNER)
        print(c("\n=== 初始化 ===\n", CYAN))

        # 1. 启动浏览器
        print(c("浏览器启动中...\n", CYAN))
        self.browser = BrowserManager(headless=False)
        await self.browser.launch()

        # 2. 导航到 DeepSeek 并检查登录
        print(c("检查 DeepSeek 登录状态...\n", CYAN))
        await self.browser.navigate()
        was_logged_out = not await self.browser.check_login()

        if was_logged_out:
            print(c("⚠️  未检测到登录，请扫码/登录...\n", YELLOW))
            await self.browser.wait_login(timeout=180)
            print(c("[OK] 登录成功！保存凭据并重启浏览器...\n", GREEN))
            
            # 3. 保存凭据
            await self.browser.save_cookies()
            
            # 4. 关闭浏览器
            print(c("关闭浏览器...\n", CYAN))
            await self.browser.close()
            self.browser = None
            
            # 5. 复制凭据到管理目录
            print(c("复制凭据到管理目录...\n", CYAN))
            self._copy_credentials_to_managed_dir()
            
            # 6. 重启浏览器（此时会自动加载凭据）
            print(c("重启浏览器...\n", CYAN))
            self.browser = BrowserManager(headless=False)
            await self.browser.launch()
            await self.browser.navigate()
            
            # 验证登录
            if await self.browser.check_login():
                print(c("[OK] 浏览器重启完成，已保持登录状态\n", GREEN))
            else:
                print(c("[WARN] 重启后未检测到登录，但凭据已保存\n", YELLOW))
        else:
            print(c("✅ 已登录，保存现有凭据...\n", GREEN))
            await self.browser.save_cookies()

        # 7. 创建任务目录
        task_root = Path.home() / "XianRenZhang_tasks"
        task_root.mkdir(exist_ok=True)
        self.current_task_dir = task_root / self.current_task_name
        self.current_task_dir.mkdir(exist_ok=True)
        print(c(f"[任务目录] {self.current_task_name}\n", GREEN))

        # 8. 初始化子代理管理器
        self._sam = get_subagent_manager(str(self.current_task_dir))
        self._register_subagent_callback()

        # 9. 初始化会话和 Commander
        self.session = DeepSeekSession(self.browser)
        self.commander = Commander(
            browser_manager=self.browser,
            session=self.session,
            work_dir=str(self.current_task_dir),
            on_event=self._on_event,
        )
        await self.commander.start(session=self.session)
        self.commander._memory = MemoryManager(str(self.current_task_dir))

        print(c("=== 初始化完成 ===\n", GREEN))
        self._print_help()
        print(c("-" * 40 + "\n", GRAY))

        # 主循环
        while self.running:
            # Ctrl+C 触发优雅关闭
            if _SHUTDOWN_REQUESTED:
                print("\n[关闭] 正在保存状态...\n")
                self.running = False
                break
            # 处理 ask 队列
            if self._ask_event.is_set():
                self._ask_event.clear()
                question = self._ask_pending_q.pop(0) if self._ask_pending_q else "请输入回答"
                answer = await self._wait_user_input(question)
                if self._ask_future and not self._ask_future.done():
                    self._ask_future.set_result(answer)
                continue

            try:
                raw = await asyncio.get_event_loop().run_in_executor(None, self._read_line)
            except KeyboardInterrupt:
                print(c("\n[中断] 输入新命令继续\n", YELLOW))
                continue
            if raw is None:
                break

            cmd = raw.strip().lower()
            if cmd in ("quit", "exit", "q"):
                self.running = False
                break
            if cmd == "clear":
                print("\n" * 60)
                continue
            if cmd == "p":
                if self.pause.is_paused():
                    self.pause.resume()
                    if self.commander:
                        self.commander.resume()
                    print(c("[已继续]\n", GREEN))
                else:
                    self.pause.pause()
                    if self.commander:
                        self.commander.pause()
                    print(c("[已暂停，输入 p 继续]\n", YELLOW))
                continue
            if cmd == "new":
                self._new_task_folder()
                self.commander._memory = MemoryManager(str(self.current_task_dir))
                # 重新初始化子代理管理器
                self._sam = get_subagent_manager(str(self.current_task_dir))
                self._register_subagent_callback()
                print(c("任务已创建，从头开始\n", GREEN))
                continue
            if cmd in ("continue", "c", "继续"):
                self.pause.resume()
                if self.commander:
                    self.commander.resume()
                print(c("[已继续执行]\n", GREEN))
                continue

            if cmd in ("pause", "暂停", "中断"):
                self.pause.pause()
                if self.commander:
                    self.commander.pause()
                print(c("[已暂停，输入 p 或 继续 恢复]\n", YELLOW))
                continue

            if cmd in ("deep", "think"):
                self.session.toggle_thinking()
                mode = "深度思考" if self.session.thinking_mode else "快速模式"
                print(c(f"[思考模式] 已切换为：{mode}\n", CYAN))
                continue
            if cmd == "upload":
                parts = raw.split(maxsplit=1)
                file_path = parts[1] if len(parts) > 1 else None
                await self._handle_upload(file_path)
                continue
            if cmd == "thinklog":
                await self._show_thinking_log()
                continue

            await self._handle_command(raw)

            # 检查子代理通知
            notifs = self._sam.get_and_clear_notifications()
            for notif in notifs:
                icon = "[OK]" if notif.success else "[FAIL]"
                print(c("\n" + "="*40, YELLOW))
                print(c(f"[子代理完成] {icon} {notif.task_id} | {notif.task_type}", YELLOW, BOLD))
                print(c(f"查询：{notif.query[:60]}", CYAN))
                if notif.success:
                    print(c(f"结果文件：{notif.result_path}", GREEN))
                else:
                    print(c(f"错误：{notif.error or '未知错误'}", RED))
                print(c("="*40 + "\n", YELLOW))

        await self._shutdown()

    def _copy_credentials_to_managed_dir(self):
        """将凭据复制到管理目录 ~/.xianrenzhang_agent/credentials/"""
        from agent_core.subagent_manager import CREDENTIALS_DIR
        CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
        target_cookie = CREDENTIALS_DIR / "deepseek_cookies.json"
        
        if COOKIE_FILE.exists():
            shutil.copy2(COOKIE_FILE, target_cookie)
            print(c(f"[OK] 凭据已复制到：{target_cookie}\n", GREEN))
        else:
            print(c("[WARN] 未找到凭据文件\n", YELLOW))

    def _register_subagent_callback(self):
        """注册子代理完成通知回调"""
        from agent_core.subagent_manager import CompletionNotification
        
        def _on_subagent_done(notif: CompletionNotification):
            icon = "[OK]" if notif.success else "[FAIL]"
            print(c(f"\n{'='*40}", YELLOW))
            print(c(f"[子代理任务完成] {icon} {notif.task_id}", YELLOW, BOLD))
            print(c(f"类型：{notif.task_type} | 查询：{notif.query[:50]}", CYAN))
            if notif.success:
                print(c(f"结果文件：{notif.result_path}", GREEN))
                if notif.findings_preview:
                    print(c(f"摘要：{notif.findings_preview[:100]}...", GRAY))
            else:
                print(c(f"错误：{notif.error}", RED))
            print(c(f"{'='*40}\n", YELLOW))
        
        if self._sam:
            self._sam.set_notify_callback(_on_subagent_done)

    def _read_line(self):
        try:
            return input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            return None

    async def _wait_user_input(self, question: str) -> str:
        """等待用户输入回答"""
        print(c(f"\n[提问] {question}\n", CYAN))
        try:
            answer = await asyncio.get_event_loop().run_in_executor(None, self._read_line)
            return answer or ""
        except Exception:
            return ""

    async def _handle_command(self, raw: str):
        """处理用户命令"""
        await self.pause.wait_if_paused()
        print()

        # 构建包含系统提示词的上下文
        system_prompt = self.commander._system_prompt
        context_hints = (
            "=== 系统提示词 ===\n"
            + system_prompt + "\n\n"
            + "=" * 40 + "\n"
            + "当前任务\n" + raw + "\n"
            + "=" * 40 + "\n"
        )

        try:
            # 发送命令给 Commander 执行
            reply = await self.commander.run_with_loop(
                user_instruction=raw,
                file_path=None,
                context_hints=context_hints,
            )
            
            # 显示 AI 思考内容（如果开启深度思考模式）
            if self.session and self.session.thinking_mode:
                try:
                    thinking = await self.browser.browser_get_thinking_content()
                    if thinking:
                        print(c(f"\n{'='*40}", YELLOW))
                        print(c("[思考过程]", YELLOW, BOLD))
                        print(c('='*40, YELLOW))
                        # 截取前 800 字，避免刷屏
                        preview = thinking[:800] if len(thinking) > 800 else thinking
                        print(c(preview, GRAY))
                        if len(thinking) > 800:
                            print(c(f"... (还有 {len(thinking)-800} 字未显示)", GRAY))
                        print(c('='*40 + '\n', YELLOW))
                except Exception:
                    pass
            
            print(c(f"\n[AI 回复]\n{reply}\n", GREEN))
            print(c(f"{'─'*40}", GRAY))
        except KeyboardInterrupt:
            print(c("\n[用户中断]\n", YELLOW))
        except Exception as e:
            print(c(f"\n[错误] {e}\n", RED))

    def _new_task_folder(self):
        task_root = Path.home() / "XianRenZhang_tasks"
        task_root.mkdir(exist_ok=True)
        existing = sorted([d.name for d in task_root.iterdir() if d.is_dir()])
        num = 1
        while f"任务{num}" in existing:
            num += 1
        self.current_task_name = f"任务{num}"
        self.current_task_dir = task_root / self.current_task_name
        self.current_task_dir.mkdir(exist_ok=True)
        print(c(f"[任务目录] {self.current_task_name}\n", GREEN))

    def _print_help(self):
        print(c("命令:", CYAN, BOLD))
        print(c("  quit / exit / q   - 退出", GRAY))
        print(c("  clear            — 清屏", GRAY))
        print(c("  new              — 新建任务", GRAY))
        print(c("  p                — 暂停/恢复 Agent", GRAY))
        print(c("  deep / think     — 切换深度思考模式", GRAY))
        print(c("  upload <文件>    — 上传文件到 DeepSeek", GRAY))
        print(c("  thinklog         — 显示当前思考内容", GRAY))
        print(c("  Ctrl+C           — 中断当前命令\n", GRAY))

    async def _handle_upload(self, file_path: str = None):
        """处理文件上传到 DeepSeek"""
        from pathlib import Path
        
        if not file_path:
            print(c("[上传] 用法: upload <文件路径>", YELLOW))
            return
        
        path = Path(file_path)
        if not path.exists():
            print(c(f"[错误] 文件不存在: {file_path}", RED))
            return
        
        print(c(f"[上传] 正在上传: {file_path}", CYAN))
        
        try:
            # 方法1: 通过 browser 上传
            if self.browser and self.browser._page:
                await self.browser._page.goto("https://chat.deepseek.com", wait_until="networkidle", timeout=15000)
                await asyncio.sleep(1)
                
                # 查找上传按钮
                try:
                    upload_btn = self.browser._page.locator("input[type='file']").first
                    await upload_btn.set_input_files(str(path))
                    print(c(f"[OK] 文件已上传: {file_path}", GREEN))
                    return
                except Exception as e:
                    print(c(f"[尝试备选方案]", YELLOW))
            
            # 方法2: 如果是 PDF，先用 wkhtmltopdf 转换
            if path.suffix.lower() == '.pdf':
                pdf_path = path
            else:
                # 调用 wkhtmltopdf 转换
                import subprocess
                pdf_path = path.with_suffix('.pdf')
                wkhtmltopdf = r"D:\软件\wkhtmltopdf\bin\wkhtmltopdf.exe"
                
                if Path(wkhtmltopdf).exists():
                    result = subprocess.run(
                        [wkhtmltopdf, str(path), str(pdf_path)],
                        capture_output=True, timeout=30
                    )
                    if result.returncode != 0:
                        print(c(f"[警告] PDF 转换失败: {result.stderr}", YELLOW))
                        pdf_path = path
                else:
                    print(c(f"[警告] wkhtmltopdf 不存在，跳过转换", YELLOW))
                    pdf_path = path
            
            print(c(f"[上传] 文件已准备好: {pdf_path}", GREEN))
            print(c(f"[提示] 请在浏览器中手动上传文件", CYAN))
            
        except Exception as e:
            print(c(f"[错误] 上传失败: {e}", RED))

    async def _show_thinking_log(self):
        """显示当前深度思考内容"""
        if not self.browser or not self.browser._page:
            print(c("[思考] 浏览器未初始化", YELLOW))
            return
        
        content = await self.browser.browser_get_thinking_content()
        if content:
            print(c("\n" + "="*40, CYAN))
            print(c("[思考内容]", CYAN, BOLD))
            print(c("="*40, CYAN))
            print(content[:2000])
            print(c("="*40 + "\n", CYAN))
        else:
            print(c("[思考] 当前无思考内容", GRAY))
    
    async def _shutdown(self):
        """优雅关闭：关闭浏览器 + 保存 cookie"""
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
        if hasattr(self, 'session') and self.session:
            try:
                self.session.save_cookies()
            except Exception:
                pass
        print(c("\n再见！仙人掌 Agent 下次见 🏜️\n", CYAN))

    def _on_event(self, event):
        etype = event.event_type
        prefix = "  "
        if etype == EventType.TOOL_START:
            tool_name = event.data.get("tool", "unknown") if event.data else "unknown"
            print(c(f"\n{prefix}┌─ [执行工具] {tool_name}", BLUE))
        elif etype == EventType.TOOL_END:
            tool_name = event.data.get("tool", "unknown") if event.data else "unknown"
            status = event.data.get("status", "") if event.data else ""
            icon = "✓" if status == "success" else "✗"
            color = GREEN if status == "success" else RED
            print(c(f"{prefix}└─ [完成] {icon} {tool_name} ({status})", color))
        elif etype == EventType.COMMAND_DETECTED:
            tool_name = event.data.get("tool", "unknown") if event.data else "unknown"
            print(c(f"\n{prefix}▶ 命令检测: {tool_name}", CYAN))
        elif etype == EventType.COMMAND_SUCCESS:
            result = event.data
            if result and result.output:
                out_preview = result.output[:150].replace('\n', ' ') if result.output else ""
                print(c(f"{prefix}✓ 结果预览: {out_preview}...", GRAY))
        elif etype == EventType.COMMAND_ERROR:
            result = event.data
            if result and result.error:
                print(c(f"{prefix}✗ 错误: {result.error[:100]}", RED))
        elif etype == EventType.AI_FINAL_REPLY:
            pass
        elif etype == EventType.ERROR:
            print(c(f"[事件] 错误：{event.data}", RED))
        elif etype == EventType.MEMORY_REMINDER:
            print(c(f"\n[记忆提醒] 已运行 {self._memory_reminder_issued + 1} 轮，建议调用 remember() 保存记忆\n", YELLOW))
            self._memory_reminder_issued += 1


async def main():
    # 注册 Ctrl+C 信号处理器
    if sys.platform != "win32":
        signal.signal(signal.SIGINT, _sigint_handler)
    terminal = Terminal()
    await terminal.run()


if __name__ == "__main__":
    asyncio.run(main())
