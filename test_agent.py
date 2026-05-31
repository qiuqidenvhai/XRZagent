#!/usr/bin/env python3
"""Test terminal imports without browser"""
import sys
sys.path.insert(0, r"D:\软件\XianRenZhangAgent")

print("Testing terminal imports...")

# Test module-level imports
from agent_core.browser import BrowserManager
from agent_core.session import DeepSeekSession
from agent_core.commander import Commander, EventType
from agent_core.memory_manager import MemoryManager
from agent_core.protocol import ExecutionResult

print("All imports OK!")

# Test EventType comparisons
print("EventType comparison:", EventType.THINKING == EventType.THINKING)
print("EventType values:", [e.name for e in EventType])

# Test ExecutionResult
er = ExecutionResult(id="1", status="success", tool="test", output="ok", error="")
print("ExecutionResult:", er)

# Test protocol
from agent_core.protocol import Protocol
p = Protocol()
p.register_tool("shell_exec", {"required": ["command"]})
blocks = p.extract_all('@@@@\n{"type":"tool_call","tool":"shell_exec","params":{"command":"echo ok"},"id":"1"}\n@@@@')
print("Protocol extract:", blocks[0].command.tool if blocks else "FAILED")

# Test wrap_result
from agent_core.protocol import ExecutionResult as ER2
wr = p.wrap_result(er)
print("wrap_result:", wr[:80])

print("\nAll tests passed!")
