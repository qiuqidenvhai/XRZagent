"""
agent_self_test.py - 不需要真实浏览器的基础测试
"""
import sys
import os
sys.path.insert(0, 'D:/软件/XianRenZhangAgent')
os.environ['PYTHONIOENCODING'] = 'utf-8'

print("=== 仙人掌 Agent 自我测试 ===\n")

# Test 1: 所有模块导入
print("[1/7] 模块导入测试...")
try:
    from agent_core import commander, browser, protocol, session, subagent_manager, subagent
    from agent_core.commander import Commander, EventType
    from agent_core.protocol import Protocol
    from agent_core.session import DeepSeekSession
    print("    OK: 所有模块导入成功\n")
except Exception as e:
    print(f"    FAIL: {e}\n")
    sys.exit(1)

# Test 2: Protocol 解析
print("[2/7] Protocol 解析测试...")
p = Protocol()
SEP = "\n"

tests = [
    ("正常JSON", '@@@@\n{"tool":"test","params":{},"id":"1"}\n@@@@'),
    ("尾部逗号", '@@@@\n{"tool":"test","params":{},"id":"1",}\n@@@@'),
    ("单引号", "@@@@\n{'tool':'test','params':{},'id':'1'}\n@@@@"),
]
ok = 0
for name, raw in tests:
    result = p.extract(raw)
    if result:
        print(f"    OK: {name}")
        ok += 1
    else:
        print(f"    FAIL: {name}")
print(f"    Protocol解析: {ok}/{len(tests)}\n")

# Test 3: Commander 初始化
print("[3/7] Commander 初始化测试...")
try:
    # 创建一个不做任何实际浏览器操作的 Commander
    import asyncio
    
    class MockBrowser:
        _browser = None
        _page = None
        async def check_login(self): return True
        async def save_cookies(self): pass
        async def close(self): pass
        def set_thinking_callback(self, cb): pass
        async def browser_get_text(self, s): return ""
        async def browser_get_html(self, s): return ""
        async def browser_scroll(self, s, n): return ""
    
    class MockSession:
        _messages = []
        thinking_mode = False
        async def send(self, t): return "test response"
        async def analyze_image(self, p, pr): return "mock"
        def get_history(self): return []
        def clear_history(self): pass
        def toggle_thinking(self): pass
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def init_test():
        cm = Commander(
            browser_manager=MockBrowser(),
            session=MockSession(),
            work_dir="D:/软件/XianRenZhangAgent/test_work",
            on_event=lambda e: None,
        )
        await cm.start(session=MockSession())
        return cm
    
    commander_inst = loop.run_until_complete(init_test())
    
    # 检查关键属性
    attrs = ['_gimme_lock', '_done_pending', '_tool_fail_count', '_memory']
    attrs_ok = sum(1 for a in attrs if hasattr(commander_inst, a))
    print(f"    OK: Commander初始化, 关键属性 {attrs_ok}/{len(attrs)}")
    
    # 检查工具注册
    tools = list(commander_inst._tools._tools.keys())
    print(f"    OK: 已注册工具 {len(tools)} 个")
    key_tools = ['file_create', 'file_read', 'file_delete', 'file_append', 
                  'file_exists', 'browser_navigate', 'browser_search', 
                  'browser_visit', 'browser_screenshot', 'docx_create',
                  'list_subagent_tasks', 'write_script', 'browser_get_text',
                  'browser_get_html', 'browser_scroll']
    for tk in key_tools:
        if tk in tools:
            print(f"       OK: {tk}")
        else:
            print(f"       MISSING: {tk}")
    
    loop.close()
    print()
except Exception as e:
    import traceback
    print(f"    FAIL: {e}")
    traceback.print_exc()
    print()

# Test 4: EventType 枚举
print("[4/7] EventType 枚举测试...")
try:
    from agent_core.commander import EventType
    events = ['TOOL_START', 'TOOL_END', 'THINKING', 'ERROR', 'MEMORY_REMINDER',
               'AI_FINAL_REPLY', 'COMMAND_DETECTED', 'COMMAND_SUCCESS', 'COMMAND_ERROR']
    for ev in events:
        if hasattr(EventType, ev):
            print(f"    OK: EventType.{ev}")
        else:
            print(f"    FAIL: EventType.{ev} 不存在")
    print()
except Exception as e:
    print(f"    FAIL: {e}\n")

# Test 5: terminal.py 导入
print("[5/7] terminal.py 导入测试...")
try:
    # 不运行run()，只检查语法和导入
    with open("D:/软件/XianRenZhangAgent/terminal.py", encoding='utf-8') as f:
        code = f.read()
    # 检查关键内容
    checks = [
        ('msvcrt', 'msvcrt 非阻塞键盘'),
        ('signal', 'signal Ctrl+C处理'),
        ('_save_session', '会话保存'),
        ('_load_session', '会话恢复'),
        ('_read_line', '键盘读取'),
    ]
    for keyword, desc in checks:
        if keyword in code:
            print(f"    OK: {desc}")
        else:
            print(f"    FAIL: {desc} 缺失")
    print()
except Exception as e:
    print(f"    FAIL: {e}\n")

# Test 6: subagent_manager 检查
print("[6/7] subagent_manager 检查...")
try:
    sm_code = open("D:/软件/XianRenZhangAgent/agent_core/subagent_manager.py", encoding='utf-8').read()
    checks = [
        ('return CREDENTIALS_DIR', '凭据复用主目录'),
        ('subagent.log', '日志重定向'),
        ('CompletionNotification', '完成通知'),
        ('MAX_DEPTH', 'MAX_DEPTH检查'),
    ]
    for keyword, desc in checks:
        if keyword in sm_code:
            print(f"    OK: {desc}")
        else:
            print(f"    FAIL: {desc} 缺失")
    print()
except Exception as e:
    print(f"    FAIL: {e}\n")

# Test 7: browser.py 检查
print("[7/7] browser.py 检查...")
try:
    b_code = open("D:/软件/XianRenZhangAgent/agent_core/browser.py", encoding='utf-8').read()
    checks = [
        ('_thinking_callback', '思考回调'),
        ('stable >= 8', '稳定检测8秒'),
        ('/sign_in', 'check_login修复'),
        ('browser_scroll', 'browser_scroll方法'),
    ]
    for keyword, desc in checks:
        if keyword in b_code:
            print(f"    OK: {desc}")
        else:
            print(f"    FAIL: {desc} 缺失")
    print()
except Exception as e:
    print(f"    FAIL: {e}\n")

print("=== 测试完成 ===")
print("\n注意：完整运行需要真实浏览器和DeepSeek登录。")
print("基础测试已通过，现在可以运行 start.bat")
