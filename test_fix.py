#!/usr/bin/env python3
"""
test_fix.py - 快速测试修复是否生效
"""
import asyncio
import sys
import os
from pathlib import Path

# 设置控制台编码为 UTF-8
os.system('chcp 65001 > nul 2>&1')

sys.path.insert(0, r"D:\软件\XianRenZhangAgent")

G = "\033[92m"
Y = "\033[93m"
R = "\033[91m"
B = "\033[94m"
C = "\033[96m"
W = "\033[0m"

OK = "[OK]"
FAIL = "[FAIL]"
INFO = "[INFO]"

def p(msg, color=W):
    print(f"{color}{msg}{W}")

async def test_imports():
    """测试模块导入"""
    p("\n[1] 测试模块导入...", B)
    try:
        from agent_core.browser import BrowserManager, COOKIE_DIR, COOKIE_FILE, CREDENTIALS_DIR
        p(f"    {OK} browser 模块导入成功", G)
        p(f"    {INFO} COOKIE_DIR: {COOKIE_DIR}", C)
        p(f"    {INFO} CREDENTIALS_DIR: {CREDENTIALS_DIR}", C)
    except Exception as e:
        p(f"    {FAIL} browser 模块导入失败：{e}", R)
        return False

    try:
        from agent_core.commander import Commander
        p(f"    {OK} commander 模块导入成功", G)
    except Exception as e:
        p(f"    {FAIL} commander 模块导入失败：{e}", R)
        return False

    try:
        from agent_core.protocol import Protocol
        p(f"    {OK} protocol 模块导入成功", G)
    except Exception as e:
        p(f"    {FAIL} protocol 模块导入失败：{e}", R)
        return False

    try:
        from agent_core.subagent_manager import SubAgentManager, get_subagent_manager
        p(f"    {OK} subagent_manager 模块导入成功", G)
    except Exception as e:
        p(f"    {FAIL} subagent_manager 模块导入失败：{e}", R)
        return False

    return True

async def test_protocol():
    """测试协议解析"""
    p("\n[2] 测试协议解析...", B)
    from agent_core.protocol import Protocol
    
    protocol = Protocol()
    
    # 测试 JSON 指令
    test_json = '@@@@\n{"tool": "file_write", "params": {"path": "test.txt", "content": "hello"}, "id": "1"}\n@@@@'
    blocks = protocol.extract_all(test_json)
    if blocks and blocks[0].command.tool == "file_write":
        p(f"    {OK} JSON 指令解析成功", G)
    else:
        p(f"    {FAIL} JSON 指令解析失败", R)
        return False
    
    # 测试 RAW 指令
    test_raw = '<<<RAW>>>\necho "hello world"\n<<<RAW>>>'
    blocks = protocol.extract_all(test_raw)
    if blocks and blocks[0].command.tool == "raw_shell":
        p(f"    {OK} RAW 指令解析成功", G)
    else:
        p(f"    {FAIL} RAW 指令解析失败", R)
        return False
    
    return True

async def test_credentials():
    """测试凭据管理"""
    p("\n[3] 测试凭据管理...", B)
    from agent_core.browser import CREDENTIALS_DIR, MANAGED_COOKIE_FILE
    from agent_core.subagent_manager import COOKIE_FILE as SAM_COOKIE_FILE
    
    p(f"    {INFO} 凭据目录：{CREDENTIALS_DIR}", C)
    p(f"    {INFO} 凭据文件：{MANAGED_COOKIE_FILE}", C)
    p(f"    {INFO} SAM 凭据文件：{SAM_COOKIE_FILE}", C)
    
    if MANAGED_COOKIE_FILE == SAM_COOKIE_FILE:
        p(f"    {OK} 凭据文件路径一致", G)
    else:
        p(f"    {INFO} 凭据文件路径不一致（可能正常，取决于设计）", Y)
    
    return True

async def main():
    p("\n" + "=" * 50, C)
    p("  仙人掌 Agent - 修复验证测试", C)
    p("=" * 50 + "\n", C)
    
    results = []
    
    results.append(await test_imports())
    results.append(await test_protocol())
    results.append(await test_credentials())
    
    p("\n" + "=" * 50, C)
    if all(results):
        p(f"  {OK} 所有测试通过！可以运行终端", G)
    else:
        p(f"  {FAIL} 有测试失败，请检查错误", R)
    p("=" * 50 + "\n", C)
    
    p("运行终端命令:", Y)
    p("    cd D:\\软件\\XianRenZhangAgent", W)
    p("    python terminal.py\n", W)

if __name__ == "__main__":
    asyncio.run(main())
