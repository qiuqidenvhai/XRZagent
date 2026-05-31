#!/usr/bin/env python3
"""Generate the new subagent.py with independent browser architecture"""
import sys
sys.path.insert(0, r"D:\软件\XianRenZhangAgent\agent_core")

# Read existing browser.py to understand its structure
with open(r"D:\软件\XianRenZhangAgent\agent_core\browser.py", encoding="utf-8") as f:
    browser_code = f.read()

# Read existing subagent.py 
with open(r"D:\软件\XianRenZhangAgent\agent_core\subagent.py", encoding="utf-8") as f:
    old_subagent = f.read()

print("Files read successfully")
print(f"browser.py: {len(browser_code)} chars")
print(f"subagent.py: {len(old_subagent)} chars")
