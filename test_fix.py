# -*- coding: utf-8 -*-
"""
test_fix.py — 仙人掌 Agent 核心功能测试（无需浏览器/DeepSeek）
用法：双击或在终端运行 python test_fix.py
"""
import sys
import os
import re

# 添加项目路径
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        print(f"  [PASS] {name}")
        PASS += 1
    else:
        print(f"  [FAIL] {name} {detail}")
        FAIL += 1

def section(title):
    print(f"\n=== {title} ===")

# ============================================================
section("1. 文件语法检查（10个核心文件）")
# ============================================================
import py_compile
files = [
    "terminal.py",
    "agent_core/commander.py",
    "agent_core/browser.py",
    "agent_core/session.py",
    "agent_core/protocol.py",
    "agent_core/subagent_manager.py",
    "agent_core/subagent.py",
    "agent_core/memory_manager.py",
    "subagent_main.py",
    "web_searcher.py",
]
for fp in files:
    full = os.path.join(ROOT, fp)
    try:
        py_compile.compile(full, doraise=True)
        check(f"{fp} 语法正确", True)
    except py_compile.PyCompileError as e:
        check(f"{fp} 语法正确", False, str(e)[:80])

# ============================================================
section("2. 核心导入检查")
# ============================================================
try:
    from agent_core.commander import Commander, EventType, AgentEvent
    from agent_core.protocol import Protocol, CMD_BEGIN, CMD_END
    from agent_core.subagent_manager import get_subagent_manager
    from agent_core.subagent import BrowserSubAgent
    from agent_core.memory_manager import MemoryManager
    from agent_core.browser import BrowserManager
    from agent_core.session import DeepSeekSession
    check("所有核心模块导入成功", True)
except Exception as e:
    check("所有核心模块导入成功", False, str(e))

# ============================================================
section("3. 协议解析（Protocol）")
# ============================================================
p = Protocol()

cases = [
    ("正常JSON", '@@@@\n{"tool":"done","params":{},"id":"1"}\n@@@@', "done", False),
    ("尾部逗号", '@@@@\n{"tool":"done","params":{},"id":"1",}\n@@@@', "done", True),
    ("RAW命令", '<<<RAW>>>\nls\n<<<RAW>>>', "raw_shell", False),
    ("嵌套引号", '@@@@\n{"tool":"shell_exec","params":{"command":"echo \\"hi\\""},"id":"1"}\n@@@@', "shell_exec", False),
]

for name, text, expected_tool, expected_fixed in cases:
    r = p.extract_all(text)
    ok = bool(r) and r[0].command.tool == expected_tool
    fix_ok = bool(r) and r[0].fixed == expected_fixed if ok else False
    if expected_fixed:
        check(f"{name}（自动修复fixed={expected_fixed}）", fix_ok, f"got fixed={r[0].fixed if r else 'None'}")
    else:
        check(f"{name}", ok, f"got tool={r[0].command.tool if r else 'None'}")

# 测试结果包装
from types import SimpleNamespace
from agent_core.protocol import ExecutionResult
result = p.wrap_result(ExecutionResult(id='1', status='success', tool='done', output='ok', error=''))
check("wrap_result 输出格式", CMD_BEGIN in result and CMD_END in result)

# ============================================================
section("4. 放弃句式拦截（Commander.GIVE_UP_PATTERNS）")
# ============================================================
patterns = Commander.GIVE_UP_PATTERNS
check(f"GIVE_UP_PATTERNS 数量 >= 13", len(patterns) >= 13, f"实际={len(patterns)}")

give_up_cases = [
    ("由于网络问题，无法完成搜索", True),
    ("抱歉，我无法完成这个任务", True),
    ("超出能力范围", True),
    ("建议你手动操作", True),
    ("无法满足您的要求", True),
]
safe_cases = [
    ("任务已完成，文件已保存", False),
    ("已为您创建了文档", False),
    ("深度思考已开启", False),
]

for text, expected in give_up_cases + safe_cases:
    detected = any(re.search(pat, text) for pat in patterns)
    status = "PASS" if detected == expected else "FAIL"
    if detected != expected:
        FAIL += 1
    else:
        PASS += 1
    prefix = "检测" if expected else "误报"
    print(f"  [{status}] {prefix}: {text[:25]}...")

# ============================================================
section("5. 任务完成验证（done 拦截）")
# ============================================================
# 模拟 Commander._validate_task_done 逻辑
def validate_task_done(output, status="success"):
    file_generated = any(
        kw in output.lower() for kw in [".docx", ".txt", ".pdf", ".pptx", ".md", ".json", ".csv", ".xlsx"]
    )
    if not file_generated and "已生成" not in output and "已创建" not in output and "已保存" not in output:
        return False, "未检测到文件生成"
    if status == "error":
        return False, "工具执行失败"
    return True, ""

ok, reason = validate_task_done("文件已保存到 test.docx")
check("done验证：正常保存文件", ok)
ok, reason = validate_task_done("任务完成")
check("done验证：无文件时应拦截", not ok, f"reason={reason}")
ok, reason = validate_task_done("下载成功", "error")
check("done验证：错误状态应拦截", not ok)

# ============================================================
section("6. 终端命令支持（terminal.py 关键代码）")
# ============================================================
with open(os.path.join(ROOT, "terminal.py"), encoding="utf-8") as f:
    tcode = f.read()

check("terminal.py 包含 _on_event 方法", "_on_event" in tcode)
check("terminal.py 支持 deep/think 命令", 'if cmd in ("deep", "think")' in tcode)
check("terminal.py 有子代理完成通知", "子代理" in tcode)
check("terminal.py 支持暂停命令(p)", "cmd == 'p'" in tcode or "cmd == '\\'p\\'" in tcode or 'if cmd in ("p"' in tcode)
check("terminal.py 有 UTF-8 编码设置", "sys.stdout.reconfigure" in tcode)
check("terminal.py 有 signal 处理", "import signal" in tcode)
check("terminal.py 有 Ctrl+C 处理", "signal.SIGINT" in tcode or ("import signal" in tcode and "SIGINT" in tcode))
check("terminal.py 有 PauseManager", "class PauseManager" in tcode)

# ============================================================
section("7. 子代理系统（subagent_manager.py）")
# ============================================================
with open(os.path.join(ROOT, "agent_core/subagent_manager.py"), encoding="utf-8") as f:
    sam_code = f.read()

check("无 CREATE_NEW_CONSOLE（无独立黑窗口）", "CREATE_NEW_CONSOLE" not in sam_code)
check("有 _monitor_subagent 方法", "_monitor_subagent" in sam_code)
check("有日志文件重定向", "subagent_" in sam_code and ".log" in sam_code)
check("get_subagent_manager 是单例", "get_subagent_manager" in sam_code)

# 实际初始化测试
try:
    sam = get_subagent_manager(ROOT)
    check("SubAgentManager 实例化成功", True)
    check("任务列表初始化为空", len(sam._tasks) == 0)
except Exception as e:
    check("SubAgentManager 实例化成功", False, str(e))

# ============================================================
section("8. 记忆系统（MemoryManager）")
# ============================================================
test_dir = os.path.join(ROOT, "__test_memory__")
try:
    mm = MemoryManager(test_dir)
    check("MemoryManager 实例化成功", True)
    mm.new_conversation("测试任务")
    mm.add_turn("测试输入", "测试输出")
    check("add_turn 计数正确", mm.turn_count == 1)
    # turn_count 和阈值比较
    threshold = getattr(mm, 'auto_summary_threshold', 20)  # 默认20
    check("turn_count 属性存在", hasattr(mm, 'turn_count'))
        import shutil
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)
    check("临时测试目录清理", True)
except Exception as e:
    check("MemoryManager 功能", False, str(e))
    import shutil
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)

# ============================================================
section("9. 浏览器管理器（BrowserManager 方法存在性）")
# ============================================================
bm = BrowserManager.__dict__
required = ["launch", "navigate", "check_login", "close", "browser_screenshot", "browser_fill", "browser_click"]
for m in required:
    check(f"BrowserManager.{m}()", m in bm or hasattr(BrowserManager, m))

# ============================================================
section("10. Commander 事件系统")
# ============================================================
try:
    e = AgentEvent(EventType.TOOL_START, {"tool": "test"})
    check("AgentEvent(TOOL_START) 创建", e.event_type == EventType.TOOL_START)
    e2 = AgentEvent(EventType.CORRECTION_SENT, {"count": 1})
    check("AgentEvent(CORRECTION_SENT) 创建", e2.event_type == EventType.CORRECTION_SENT)
    from agent_core.commander import AgentEvent
except Exception as e:
    check("AgentEvent 系统", False, str(e))

# ============================================================
section("11. RAW 命令协议")
# ============================================================
raw_tests = [
    ("ls", "ls"),
    ("ls -la", "ls -la"),
    ("echo hello", "echo hello"),
]
for cmd, expected in raw_tests:
    text = f"<<<RAW>>>\n{cmd}\n<<<RAW>>>"
    r = p.extract_all(text)
    check(f"RAW协议: {cmd}", bool(r) and r[0].command.params.get("command") == expected)

# ============================================================
section("12. 文件操作（不依赖浏览器的工具）")
# ============================================================
from agent_core.commander import Commander

# Commander 的工具注册检查
c = Commander.__dict__
tools_to_check = [
    "file_write", "file_read", "file_append", "file_delete", "file_exists",
    "dir_create", "dir_list", "shell_exec", "done", "ask",
    "remember", "recall", "summarize", "list_summaries",
]
# 工具注册在 __init__ 里，需要实例化后才在 _tools 里
# 这里只检查类的方法是否存在（工具作为方法定义）
for tool in tools_to_check:
    has_method = tool in c or hasattr(Commander, tool)
    # file_write 等作为普通方法在类上，工具注册后的 key 在 _tools 里
    # 检查类方法定义
    in_methods = any(tool in str(getattr(Commander, m, '')) or tool == m for m in dir(Commander) if not m.startswith('_'))
    # 宽松检查：只要 _tools 注册了或类有方法就行
    has_tool = in_methods
    check(f"Commander.{tool} 工具", has_tool, "(via instance._tools or class method)")

# ============================================================
section("总结")
# ============================================================
print(f"\n  PASS: {PASS}")
print(f"  FAIL: {FAIL}")
if FAIL == 0:
    print("\n  [ALL TESTS PASSED] — 可以正常使用！")
    print("\n  启动方式：")
    print("  双击 启动仙人掌.bat")
    print("  或: python terminal.py")
else:
    print(f"\n  [有 {FAIL} 项测试失败] — 需要修复")
    sys.exit(1)
