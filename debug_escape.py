#!/usr/bin/env python3
"""Minimal test of _try_fix"""
import sys, re, json
sys.path.insert(0, r"D:\软件\XianRenZhangAgent")

# Simulate the actual _try_fix function from the file
def _try_fix(raw):
    result = re.sub(r",\s*([}\]])", r"\1", raw)
    def esc(m):
        # Read the actual string from file
        with open(r"D:\软件\XianRenZhangAgent\agent_core\protocol.py", encoding="utf-8") as f:
            content = f.read()
        # Find the return line
        for line in content.split('\n'):
            if 'return' in line and 'm.group' in line and 'def esc' not in line:
                import re as re2
                m_match = re2.search(r'return "([^"]*)"', line)
                if m_match:
                    s = m_match.group(1)
                    print(f"File return string: {repr(s)}, len={len(s)}")
                    print(f"Backslash count in return string: {s.count(chr(92))}")
                    return s + m.group(1)
        return "\\" + m.group(1)
    
    result2 = re.sub(r'\\([A-Za-z])', esc, result)
    return result2

raw = '{"path":"C:\\Users"}'
fixed = _try_fix(raw)
print(f"Fixed: {repr(fixed)}")
print(f"Same as input? {raw == fixed}")

try:
    obj = json.loads(fixed)
    print(f"json.loads SUCCESS: {obj}")
except Exception as e:
    print(f"json.loads FAILED: {e}")
