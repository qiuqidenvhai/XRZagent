#!/usr/bin/env python3
"""测试协议解析"""
import sys
import re
sys.path.insert(0, r'D:\软件\XianRenZhangAgent')

from agent_core.protocol import Protocol, CMD_BEGIN, CMD_END, RAW_BEGIN, RAW_END

p = Protocol()

# AI 实际输出
test = '''我来帮您完成这个任务。首先，我需要在桌面上创建一个文件夹，然后使用浏览器代理搜索MCP协议的相关信息，最后生成Word报告。

让我先创建桌面文件夹：

@@@@
{
"tool": "shell_exec",
"params": {
"command": "mkdir -p "$HOME/Desktop/MCP协议报告""
},
"id": "1"
}
@@@@
'''

print(f"CMD_BEGIN = {repr(CMD_BEGIN)}")
print(f"CMD_END = {repr(CMD_END)}")
print()
print(f"测试字符串包含 CMD_BEGIN: {CMD_BEGIN in test}")
print(f"测试字符串包含 CMD_END: {CMD_END in test}")
print()

# 手动调试
positions = [m.start() for m in re.finditer(re.escape(CMD_BEGIN), test)]
print(f"CMD_BEGIN 出现位置: {positions}")

if len(positions) >= 2:
    start = positions[0] + len(CMD_BEGIN)
    end = positions[1]
    raw = test[start:end].strip()
    print(f"提取的 JSON: {raw[:100]}")
    try:
        import json
        obj = json.loads(raw)
        print(f"解析成功: {obj['tool']}")
    except Exception as e:
        print(f"解析失败: {e}")

print()
cmds = p.extract_all(test)
print(f"extract_all 返回: {len(cmds)} 个命令")
if cmds:
    print(f"  工具: {cmds[0].command.tool}")
else:
    print("  没有找到命令")