#!/usr/bin/env python3
"""Test extract_all with simulated reply"""
import sys
sys.path.insert(0, r"D:\软件\XianRenZhangAgent")

from agent_core.protocol import Protocol
import json

p = Protocol()

# Simulated reply with tool call (from the actual agent run)
reply = """用的，工具调用将上传至远程服务器处理。

@@@@
{"type":"tool_call","tool":"dir_create","params":{"path":"C:\\Users\\用户名\\Desktop\\MCP报告"},"id":"550e8400-e29b-41d4-a716-446655440001"}
@@@@

如果需要立即查看结果或有其他要求，请告诉我。"""

print(f"Reply length: {len(reply)}")
print(f"Has @@@@: {'@@@@' in reply}")
print(f"@@@@ count: {reply.count('@@@@')}")

# Test extract
blocks = p.extract_all(reply)
print(f"\nextract_all result: {len(blocks)} blocks")
if blocks:
    for i, b in enumerate(blocks):
        print(f"  Block {i}: tool={b.command.tool}, params={b.command.params}")
else:
    print("No blocks found!")
    
    # Debug: find positions
    import re
    positions = [m.start() for m in re.finditer(re.escape('@@@@'), reply)]
    print(f"\nPositions of @@@@: {positions}")
    
    for i in range(len(positions) - 1):
        start = positions[i] + 4
        end = positions[i + 1]
        raw = reply[start:end].strip()
        print(f"\nBlock {i}: raw = {repr(raw[:100])}")
        try:
            obj, _ = json.JSONDecoder().raw_decode(raw)
            print(f"  raw_decode OK: tool={obj.get('tool')}")
        except Exception as e:
            print(f"  raw_decode FAIL: {e}")
            # Try _try_fix
            fixed = p._try_fix(raw)
            try:
                obj2 = json.loads(fixed)
                print(f"  _try_fix + json.loads OK: {obj2}")
            except Exception as e2:
                print(f"  _try_fix + json.loads FAIL: {e2}")
