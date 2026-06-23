"""
terminal.py — 仙人掌 Agent 终端
"""
import asyncio
import sys
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

# 确保 stdin/stdout 使用 UTF-8 编码（解决中文输入乱码）
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stdin.reconfigure(encoding='utf-8', errors='replace')

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
        "  多平台 LLM | 工具执行 | 子代理支持\n"
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
        self._memory_reminder_issued = 0
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

        # 8. 初始化多平台浏览器管理器（共享母代理 cookie）
        from agent_core.multi_browser import MultiBrowserManager, set_multi_browser_manager
        self.multi_browser = MultiBrowserManager()
        await self.multi_browser.init_from_existing_context(self.browser)
        set_multi_browser_manager(self.multi_browser)
        await self.multi_browser.launch_all()
        print(c(f"[多平台] 已初始化 {len(self.multi_browser._pages)} 个平台\n", GREEN))

        # 9. 初始化子代理管理器
        self._sam = get_subagent_manager(str(self.current_task_dir))
        self._register_subagent_callback()

        # 10. 初始化会话和 Commander
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
                    print(c("[已继续]\n", GREEN))
                else:
                    self.pause.pause()
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
            if cmd in ("deep", "think"):
                self.session.toggle_thinking()
                mode = "深度思考" if self.session.thinking_mode else "快速模式"
                print(c(f"[思考模式] 已切换为：{mode}\n", CYAN))
                continue
            if cmd == "thinklog":
                await self._show_thinking_log()
                continue
            if cmd == "gui":
                await self._launch_gui()
                continue
            if cmd == "upload":
                parts = raw.split(maxsplit=1)
                file_path = parts[1] if len(parts) > 1 else None
                await self._handle_upload(file_path)
                continue
            if cmd == "platform":
                parts = raw.split(maxsplit=1)
                platform_name = parts[1].strip().lower() if len(parts) > 1 else None
                await self._switch_platform(platform_name)
                continue
            if cmd == "history":
                await self._show_history()
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
            print(c(f"\n[AI 回复]\n{reply}\n", GREEN))
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
        print(c("  upload <文件>    — 上传文件", GRAY))
        print(c("  platform <平台名> — 切换平台", GRAY))
        print(c("  history          — 显示会话历史", GRAY))
        print(c("  gui              — 打开图形界面", GRAY))
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

    async def _switch_platform(self, platform_name: str = None):
        """切换多平台 LLM"""
        from agent_core.multi_browser import get_multi_browser_manager
        global PLATFORMS
        if not platform_name:
            available = ", ".join(get_multi_browser_manager()._platform_configs.keys()) if get_multi_browser_manager() else "deepseek,tongyi,doubao,yuanbao,gpt,gemini,ollama"
            print(c(f"[平台] 当前使用 DeepSeek。可用平台: {available}", YELLOW))
            return
        mb = get_multi_browser_manager()
        if not mb:
            print(c("[平台] 多平台浏览器未初始化，请先登录并启动\n", YELLOW))
            return
        if platform_name not in mb._platform_configs:
            print(c(f"[错误] 不支持的平台: {platform_name}", RED))
            return
        pp = mb._pages.get(platform_name)
        if not pp or not pp.page:
            print(c(f"[错误] 平台 {platform_name} 未加载", RED))
            return
        await pp.page.bring_to_front()
        print(c(f"[平台] 已切换到: {mb._platform_configs[platform_name]['name']} ({platform_name})", GREEN))
        if not pp.is_logged_in:
            print(c(f"[提示] 请在浏览器中为 {platform_name} 完成登录", YELLOW))

    async def _show_history(self):
        """显示会话历史"""
        from agent_core.session import get_conversation_history
        history = get_conversation_history()
        records = history.list_records(limit=10)
        if not records:
            print(c("[历史] 暂无对话记录", YELLOW))
            return
        print(c("\n=== 最近会话历史 ===", GREEN))
        for i, rec in enumerate(reversed(records), 1):
            msg_count = len(rec.messages)
            print(c(f"  {i}. [{rec.platform}] session={rec.session_id}", CYAN))
            print(c(f"     消息: {msg_count} 条  时间: {rec.created_at}", GRAY))
            if rec.url:
                print(c(f"     URL: {rec.url[:80]}...", GRAY))
        print(c("=" * 40 + "\n", GREEN))

    async def _shutdown(self):
        if self.browser:
            await self.browser.close()
        print(c("\n再见\n", CYAN))

    async def _launch_gui(self):
        """启动 GUI 图形界面"""
        print(c("\n[GUI] 正在启动图形界面...\n", CYAN))
        try:
            gui_script = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>仙人掌 Agent</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#111827;color:#e5e7eb;height:100vh;display:flex;flex-direction:column;overflow:hidden}
.header{background:linear-gradient(135deg,#059669,#10b981);padding:16px 24px;display:flex;align-items:center;gap:12px}
.header h1{font-size:22px;font-weight:700;color:#fff}
.header .badge{background:rgba(255,255,255,.2);border-radius:20px;padding:2px 10px;font-size:12px;color:#fff}
.tabs{display:flex;gap:4px;padding:8px 24px;background:#1f2937;border-bottom:1px solid #374151}
.tab{padding:8px 16px;border-radius:6px;cursor:pointer;font-size:13px;color:#9ca3af;transition:.2s}
.tab.active{background:#059669;color:#fff}
.main{display:flex;flex:1;overflow:hidden}
.chat-panel{flex:1;display:flex;flex-direction:column;min-width:0}
.messages{flex:1;overflow-y:auto;padding:16px 24px;display:flex;flex-direction:column;gap:12px}
.msg{max-width:80%;padding:12px 16px;border-radius:12px;line-height:1.5;font-size:14px}
.msg.user{align-self:flex-end;background:#059669;color:#fff;border-bottom-right-radius:4px}
.msg.ai{align-self:flex-start;background:#374151;border-bottom-left-radius:4px}
.msg.system{align-self:center;background:#1f2937;border:1px solid #4b5563;font-size:12px;padding:8px 16px}
.input-area{display:flex;gap:8px;padding:12px 24px;background:#1f2937;border-top:1px solid #374151}
.input-area input{flex:1;padding:10px 16px;border-radius:24px;border:none;background:#111827;color:#e5e7eb;font-size:14px;outline:none}
.input-area input:focus{box-shadow:0 0 0 2px #059669}
.btn-send{width:44px;height:44px;border-radius:50%;border:none;background:#059669;color:#fff;cursor:pointer;font-size:18px;transition:.2s}
.btn-send:hover{background:#10b981}
.panel{width:280px;border-left:1px solid #374151;background:#1f2937;display:flex;flex-direction:column;overflow-y:auto}
.panel-section{padding:12px 16px;border-bottom:1px solid #374151}
.panel-section h3{font-size:13px;color:#9ca3af;margin-bottom:8px;text-transform:uppercase;letter-spacing:.5px}
.platform-btn{display:block;width:100%;padding:8px 12px;margin-bottom:4px;border-radius:6px;border:none;background:#374151;color:#d1d5db;cursor:pointer;font-size:13px;text-align:left;transition:.2s}
.platform-btn:hover{background:#4b5563}
.platform-btn.active{background:#059669;color:#fff}
.cmd-btn{display:inline-block;padding:6px 10px;margin:2px;border-radius:4px;border:none;background:#374151;color:#d1d5db;cursor:pointer;font-size:12px}
.cmd-btn:hover{background:#4b5563}
.history-item{padding:6px 10px;margin:2px 0;border-radius:4px;background:#374151;font-size:12px;cursor:pointer;color:#d1d5db}
.history-item:hover{background:#4b5563}
.typing-indicator{align-self:flex-start;background:#374151;padding:8px 16px;border-radius:12px;font-size:13px;color:#6b7280}
</style>
</head>
<body>
<div class="header">
<h1>🌵 仙人掌 Agent</h1>
<span class="badge">多平台 LLM</span>
</div>
<div class="tabs" id="tabs">
<div class="tab active" onclick="switchTab('chat')">聊天</div>
<div class="tab" onclick="switchTab('commands')">命令</div>
</div>
<div class="main">
<div class="chat-panel">
<div class="messages" id="messages"></div>
<div class="input-area">
<input id="userInput" placeholder="输入消息..." onkeydown="if(event.key==='Enter')sendMessage()">
<button class="btn-send" onclick="sendMessage()">➤</button>
</div>
</div>
<div class="panel" id="panel">
<div class="panel-section">
<h3>平台切换</h3>
<div id="platforms"></div>
</div>
<div class="panel-section">
<h3>快捷命令</h3>
<button class="cmd-btn" onclick="runCmd('deep')">深度思考</button>
<button class="cmd-btn" onclick="runCmd('new')">新任务</button>
<button class="cmd-btn" onclick="runCmd('clear')">清屏</button>
<button class="cmd-btn" onclick="runCmd('p')">暂停</button>
<button class="cmd-btn" onclick="runCmd('list')">记忆列表</button>
</div>
<div class="panel-section">
<h3>会话历史</h3>
<div id="history"></div>
</div>
</div>
</div>
<script>
const messages=document.getElementById('messages');
const input=document.getElementById('userInput');
let currentTab='chat';
const platforms=['deepseek','tongyi','doubao','yuanbao','gpt','gemini','ollama'];
let activePlatform='deepseek';
platforms.forEach(p=>{
const btn=document.createElement('button');
btn.className='platform-btn'+(p===activePlatform?' active':'');
btn.textContent=(p.toUpperCase());
btn.onclick=()=>{activePlatform=p;document.querySelectorAll('.platform-btn').forEach(b=>b.classList.remove('active'));btn.classList.add('active')};
document.getElementById('platforms').appendChild(btn);
});
function addMessage(content,type='user'){
const div=document.createElement('div');
div.className='msg '+type;
div.textContent=content;
messages.appendChild(div);
messages.scrollTop=messages.scrollHeight;
}
function addTyping(){
const div=document.createElement('div');
div.className='typing-indicator';
div.textContent='...';
div.id='typing';
messages.appendChild(div);
messages.scrollTop=messages.scrollHeight;
setTimeout(()=>{const t=document.getElementById('typing');if(t)t.remove()},2000);
}
async function sendMessage(){
const text=input.value.trim();
if(!text)return;
input.value='';
addMessage(text,'user');
addTyping();
const formData=new FormData();
formData.append('cmd',text);
try{
const res=await fetch('/api/command',{method:'POST',body:formData});
const data=await res.json();
addMessage(data.reply||'(空)','ai');
}catch(e){
addMessage('连接母代理失败: '+e.message,'system');
}
}
function runCmd(cmd){
addMessage(cmd,'system');
const fd=new FormData();
fd.append('cmd',cmd);
fetch('/api/command',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{if(d.reply)addMessage(d.reply,'system')}).catch(()=>{});
}
function switchTab(tab){
currentTab=tab;
document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
event.target.classList.add('active');
}
addMessage('欢迎使用仙人掌 Agent 🌵','system');
</script>
</body>
</html>
'''
            import tempfile
            from pathlib import Path
            import threading
            from http.server import HTTPServer, SimpleHTTPRequestHandler
            
            tmp_file = Path(tempfile.mkdtemp()) / "gui.html"
            tmp_file.write_text(gui_script, encoding="utf-8")
            
            class Handler(SimpleHTTPRequestHandler):
                def do_GET(self):
                    if self.path == '/' or self.path == '/gui.html':
                        self.send_response(200)
                        self.send_header('Content-type', 'text/html; charset=utf-8')
                        self.end_headers()
                        self.wfile.write(gui_script.encode('utf-8'))
                    elif self.path == '/api/command':
                        pass
                    else:
                        super().do_GET()
                
                def do_POST(self):
                    if self.path == '/api/command':
                        content_length = int(self.headers['Content-Length'])
                        post_data = self.rfile.read(content_length)
                        import urllib.parse
                        parsed = urllib.parse.parse_qs(post_data.decode('utf-8'))
                        cmd = parsed.get('cmd', [''])[0]
                        
                        import asyncio
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        
                        from agent_core.commander import Commander
                        from agent_core.session import DeepSeekSession
                        from agent_core.memory_manager import MemoryManager
                        from pathlib import Path as P
                        
                        task_root = P.home() / "XianRenZhang_tasks"
                        task_root.mkdir(exist_ok=True)
                        task_dir = task_root / self.current_task_name
                        task_dir.mkdir(exist_ok=True)
                        
                        # 初始化组件
                        session = DeepSeekSession(self.current_browser)
                        self.commander = Commander(
                            browser_manager=self.current_browser,
                            session=session,
                            work_dir=str(task_dir),
                        )
                        loop.run_until_complete(self.commander.start(session=session))
                        self.commander._memory = MemoryManager(str(task_dir))
                        
                        try:
                            reply = loop.run_until_complete(
                                self.commander.run_with_loop(
                                    user_instruction=cmd,
                                    file_path=None,
                                    context_hints=""
                                )
                            )
                        except Exception as e:
                            reply = f"命令执行错误: {e}"
                        
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json; charset=utf-8')
                        self.end_headers()
                        self.wfile.write({'reply': reply[:2000]}.encode('utf-8'))
                    
                    def log_message(self, format, *args):
                        pass
                
                current_task_name = "任务 1"
                current_browser = None
                commander = None
            
            # 存储 browser manager 引用
            if self.browser:
                Handler.current_browser = self.browser
            
            try:
                server = HTTPServer(('127.0.0.1', 8090), Handler)
                print(c("[GUI] 服务器启动于 http://127.0.0.1:8090\n", GREEN))
                
                import webbrowser
                webbrowser.open('http://127.0.0.1:8090')
                
                server.serve_forever()
            except Exception as e:
                print(c(f"[GUI] 启动失败: {e}\n", RED))

    async def _shutdown(self):
        if self.browser:
            await self.browser.close()
        print(c("\n再见\n", CYAN))

    def _on_event(self, event):
        etype = event.event_type
        if etype == EventType.TOOL_START:
            pass
        elif etype == EventType.TOOL_END:
            pass
        elif etype == EventType.ERROR:
            print(c(f"[事件] 错误：{event.data}", RED))
        elif etype == EventType.MEMORY_REMINDER:
            print(c(f"\n[记忆提醒] 已运行 {self._memory_reminder_issued + 1} 轮，建议调用 remember() 保存记忆\n", YELLOW))
            self._memory_reminder_issued += 1


async def main():
    terminal = Terminal()
    await terminal.run()


if __name__ == "__main__":
    asyncio.run(main())
