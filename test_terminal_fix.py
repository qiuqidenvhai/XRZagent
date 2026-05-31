"""Test terminal.py with simulated input"""
import asyncio
import sys
sys.path.insert(0, r"D:\软件\XianRenZhangAgent")

from agent_core.browser import BrowserManager
from agent_core.session import DeepSeekSession
from agent_core.commander import Commander, EventType
from agent_core.protocol import ExecutionResult
from agent_core.memory_manager import MemoryManager

TEST_TASK = "帮我在桌面创建一个文件夹，生成一个关于MCP协议的报告放在里面，给我word，要使用浏览器代理搜索"

async def main():
    print("=" * 50)
    print("  仙人掌 Agent — 测试")
    print("=" * 50)

    # 1. Browser
    print("[1] 启动浏览器...")
    browser = BrowserManager(headless=False)
    await browser.launch()
    print("    浏览器已启动")

    # 2. Session
    print("[2] 初始化 DeepSeek...")
    session = DeepSeekSession(browser)
    await session.initialize()
    print("    会话已就绪")

    # 3. Work dir
    from pathlib import Path
    desktop = Path.home() / "Desktop"
    work_dir = desktop / "MCP_测试任务"
    work_dir.mkdir(exist_ok=True)
    print(f"[3] 工作目录: {work_dir}")

    # 4. Commander
    print("[4] 启动 Commander...")
    commander = Commander(
        browser_manager=browser,
        session=session,
        work_dir=str(work_dir),
        on_event=lambda e: None,
    )
    await commander.start(session=session)
    commander._memory = MemoryManager(str(work_dir))
    print(f"    Commander 就绪")
    print(f"    系统提示词长度: {len(commander._system_prompt)} 字符")
    
    # Show first 200 chars of system prompt
    sp = commander._system_prompt
    print(f"    提示词开头: {sp[:150]}...")

    # 5. 构建首条消息（带系统提示词）
    first_message = (
        sp + "\n\n"
        + "=" * 40 + "\n"
        + "当前任务\n" + TEST_TASK + "\n"
        + "=" * 40 + "\n"
    )
    print(f"\n[5] 首条消息长度: {len(first_message)} 字符")
    print(f"    是否包含 @@@@ : {'@@@@' in first_message}")
    print(f"    是否以 You are 开头: {first_message.startswith('You')}")

    # 6. 发送并检查回复
    print("\n[6] 发送给 DeepSeek...")
    reply = await session.send(first_message)
    print(f"    回复长度: {len(reply)} 字符")
    print(f"    回复是否包含 @@@@ : {'@@@@' in reply}")
    
    # 检查是否有 tool_call
    blocks = commander._protocol.extract_all(reply)
    print(f"    提取到 tool_call 数量: {len(blocks)}")
    if blocks:
        for b in blocks:
            print(f"    工具: {b.command.tool}, 参数: {str(b.command.params)[:100]}")
    else:
        # 没有 tool_call，显示前300字
        print(f"    回复内容（前300字）:")
        print(f"    {reply[:300]}")

    # 收尾
    await browser.save_cookies()
    await browser.close()
    print("\n[完成]")

asyncio.run(main())
