#!/usr/bin/env python3
"""Test _try_fix directly"""
import sys
sys.path.insert(0, r"D:\软件\XianRenZhangAgent")

# Force reload of protocol module
import agent_core.protocol
import importlib
importlib.reload(agent_core.protocol)

from agent_core.protocol import Protocol
import json

p = Protocol()

# Test _try_fix with actual file content
raw = '{"path":"C:\\Users"}'
print(f"Input: {repr(raw)}")
print(f"Input chars: {[c for c in raw]}")

# Call _try_fix
fixed = p._try_fix(raw)
print(f"Fixed: {repr(fixed)}")
print(f"Fixed chars: {[c for c in fixed]}")

# Test json.loads on both
print()
print("json.loads on input:")
try:
    obj = json.loads(raw)
    print(f"  OK: {obj}")
except Exception as e:
    print(f"  FAIL: {e}")

print("json.loads on fixed:")
try:
    obj = json.loads(fixed)
    print(f"  OK: {obj}")
except Exception as e:
    print(f"  FAIL: {e}")
