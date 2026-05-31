#!/usr/bin/env python3
"""
run_agent.py - 仙人掌Agent 自动测试入口
直接执行完整任务，读取命令行参数作为任务
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, r"D:\软件\XianRenZhangAgent")

# 默认任务
DEFAULT_TASK = (
    "帮我在桌面创建一个文件夹，"
    "生成一个关于MCP协议的报告放在里面，给我word，"
    "要使用浏览器代理搜索"
)
TASK = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TASK

# ANSI colors
G = "\033[92m"
Y = "\033[93m"
R = "\033[91m"
B = "\033[94m"
C = "\033[96m"
W = "\033[0m"

def p(msg, color=W):
    print(f"{color}{msg}{W}")

async def main():
    p("\n" + "=" * 50, C)
    p("  仙人掌 Agent — 自动测试", C)
    p("=" * 50 + "\n", C)

    from agent_core.browser import BrowserManager
    from agent_core.session import DeepSeekSession
    from agent_core.commander import Commander
    from agent_core.memory_manager import MemoryManager
    from agent_core.protocol import ExecutionResult

    # ---- 1. Browser ----
    p("[1] 启动浏览器...", B)
    browser = BrowserManager(headless=False)
    await browser.launch()
    p("    浏览器已启动\n", G)

    # ---- 2. Session ----
    p("[2] 初始化 DeepSeek 会话...", B)
    session = DeepSeekSession(browser)
    await session.initialize()
    p("    会话已就绪\n", G)

    # ---- 3. Work dir ----
    desktop = Path.home() / "Desktop"
    work_dir = desktop / "MCP_报告任务"
    work_dir.mkdir(exist_ok=True)
    p(f"[3] 工作目录: {work_dir}\n", B)

    # ---- 4. Commander ----
    p("[4] 启动 Commander...", B)
    commander = Commander(
        browser_manager=browser,
        session=session,
        work_dir=str(work_dir),
        on_event=lambda e: None,
    )
    await commander.start(session=session)
    commander._memory = MemoryManager(str(work_dir))
    p("    Commander 就绪\n", G)

    # ---- 5. 构建首条消息 ----
    system_prompt = commander._system_prompt
    first_message = (
        system_prompt + "\n\n"
        + "=" * 40 + "\n"
        + "当前任务\n" + TASK + "\n"
        + "=" * 40 + "\n"
    )

    # ---- 6. 自动任务循环 ----
    p(f"[5] 开始执行任务...\n", B)
    p(f"    任务: {TASK}\n", Y)

    done = False
    current_input = first_message
    step = 0
    max_steps = 60

    while not done and step < max_steps:
        step += 1
        p(f"\n--- Step {step} ---", C)
        p(" [思考中...]", B)

        try:
            reply = await session.send(current_input)
        except Exception as e:
            p(f"\n[发送失败] {e}", R)
            break

        # 解析 tool_call
        blocks = commander._protocol.extract_all(reply)
        block = blocks[0] if blocks else None

        if block is None:
            p(f"\n{'='*40}", G)
            p("最终回复:", Y)
            p(reply[:800], C)
            p(f"{'='*40}\n", G)
            done = True
            continue

        tool_name = block.command.tool
        tool_params = block.command.params or {}
        brief = str(tool_params)
        if len(brief) > 100:
            brief = brief[:100] + "..."

        p(f"\n>>> 工具: {tool_name}  参数: {brief}", Y)

        # 执行工具
        try:
            result = await commander._tools.execute(tool_name, tool_params)
        except Exception as e:
            p(f"    [X] {e}", R)
            current_input = (
                f"[系统] 工具 {tool_name} 执行失败: {e}\n"
                "请修复错误后继续完成任务，完成后调用done工具。"
            )
            continue

        # done -> 结束
        if tool_name == "done":
            out = result.output or "任务完成"
            p(f"    [OK] {str(out)[:300]}", G)
            p(f"\n{'='*40}", G)
            p("最终回复:", Y)
            p(str(out), C)
            p(f"{'='*40}\n", G)
            done = True
            continue

        # 显示结果
        if result.status == "success":
            p(f"    [OK] {str(result.output or '')[:300]}", G)
        else:
            p(f"    [X] {str(result.error or '未知错误')[:300]}", R)

        # 包装结果并继续
        exec_result = commander._protocol.wrap_result(ExecutionResult(
            id=block.command.id,
            status=result.status,
            tool=result.tool,
            output=result.output or "",
            error=result.error or "",
        ))

        current_input = (
            f"[工具执行完成: {tool_name}]\n"
            + exec_result + "\n\n"
            "请根据以上结果继续执行任务，直到调用 done 工具结束。"
        )

    # ---- 7. 收尾 ----
    p(f"\n循环结束 (step={step}, done={done})", C)
    p("[6] 保存 cookies 并关闭浏览器...", B)
    await browser.save_cookies()
    await browser.close()
    p("    完成\n", G)

    if done:
        p("[OK] 任务完成", G)
    else:
        p(f"[FAIL] 未能完成 (step={step})", R)

asyncio.run(main())
