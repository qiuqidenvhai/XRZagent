#!/usr/bin/env python3
"""Verify protocol.py _try_fix is correct"""
import sys
sys.path.insert(0, r"D:\软件\XianRenZhangAgent")

# Read and check the esc function's return string
with open(r"D:\软件\XianRenZhangAgent\agent_core\protocol.py", encoding="utf-8") as f:
    content = f.read()

lines = content.split('\n')
for i, line in enumerate(lines, 1):
    if 'return' in line and 'm.group' in line and 'def esc' not in line:
        print(f"Line {i}: {repr(line)}")
        # Extract the string between quotes
        idx1 = line.find('"')
        idx2 = line.find('"', idx1 + 1)
        inner = line[idx1+1:idx2]
        print(f"  String content: {repr(inner)}, len={len(inner)}, backslashes={inner.count(chr(92))}")
